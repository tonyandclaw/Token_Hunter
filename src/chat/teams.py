"""TeamsAdapter — Microsoft Teams via direct Bot Framework v3 HTTP.

We talk to the Bot Framework Activity protocol directly rather than going
through `botbuilder-core`, because:
  - one fewer heavyweight dep (botbuilder pulls in ~15 transitive packages)
  - explicit control over the wire format; easier to reason about
  - the codebase already prefers minimal external libraries

Wire protocol (simplified, for our subset of the activity types):

INBOUND (Teams → bot):
  POST {bot_endpoint}/api/messages
    Headers: Authorization: Bearer <JWT signed by Microsoft>
    Body: Activity JSON
      {
        "type": "message" | "invoke",      # "invoke" for Adaptive Card actions
        "id": "<activity_id>",              # used as MessageRef
        "serviceUrl": "https://smba.trafficmanager.net/...",
        "channelId": "msteams",
        "from": { "id": "...", "aadObjectId": "<user_aad_id>", "name": "..." },
        "conversation": { "id": "...", ... },
        "recipient": { "id": "...", "name": "..." },
        "text": "...",                      # for type=message
        "value": { ... }                     # for type=invoke (Adaptive Card Action.Submit data)
      }

OUTBOUND (bot → Teams):
  POST {serviceUrl}/v3/conversations/{conversation_id}/activities[/{reply_to_id}]
    Headers: Authorization: Bearer <token from MSAL>
    Body: Activity JSON

Adaptive Cards are the Teams equivalent of Telegram inline keyboards. A
Keyboard renders as a card with `Action.Submit` buttons; each button's
`data` field carries the callback_data string we'd otherwise put in
Telegram's callback_data.

Proactive messages (sending without a prior incoming activity) require
remembering the ConversationReference from each user's first message —
Teams won't let the bot DM a stranger. The reference is persisted to
`trust/teams_conversations.json` so it survives process restart.

Called by: `src/main.py:build_adapter` when `CHAT_PLATFORM=teams`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from src.chat.base import (
    Button,
    ButtonHandler,
    ChatAdapter,
    IncomingButton,
    IncomingText,
    Keyboard,
    MessageRef,
    TextHandler,
)
from src.chat.teams_auth import (
    JWTVerificationError,
    OpenIdMetadataCache,
    verify_token,
)
from src.http_retry import request_with_retry

log = logging.getLogger("fushou.chat.teams")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONVERSATIONS_PATH = REPO_ROOT / "trust" / "teams_conversations.json"

# Microsoft endpoints — pinned to the Bot Framework v3 channel.
LOGIN_URL = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
BOT_SCOPE = "https://api.botframework.com/.default"


@dataclass(frozen=True)
class _TeamsMessageRef:
    """Teams-specific MessageRef payload — needed to update a card later."""

    service_url: str
    conversation_id: str
    activity_id: str


@dataclass
class ConversationRef:
    """Persisted ConversationReference, used for proactive messages.

    Captured on the first incoming activity from a user; replayed when we
    need to send a message to that user without a triggering activity
    (e.g. cost alerts, absence-replay-on-expiry, escalation proposals).
    """

    user_aad_id: str
    service_url: str
    conversation_id: str
    bot_id: str  # the bot's recipient id from the original activity
    last_updated_ts: float = field(default_factory=time.time)


def _adaptive_card(text: str, keyboard: Keyboard | None) -> dict[str, Any]:
    """Build the Teams Adaptive Card v1.4 JSON payload.

    - The text body becomes a TextBlock (wraps long content)
    - Each button row becomes one ActionSet; rows stack vertically on cards
    - Action.Submit's `data.cb` carries our callback_data verbatim
    """
    body: list[dict[str, Any]] = [{"type": "TextBlock", "text": text, "wrap": True}]
    if keyboard:
        for row in keyboard:
            actions = [
                {
                    "type": "Action.Submit",
                    "title": b.label,
                    "data": {"cb": b.callback_data},
                }
                for b in row
            ]
            body.append({"type": "ActionSet", "actions": actions})

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
    }


def _wrap_card_attachment(text: str, keyboard: Keyboard | None) -> dict[str, Any]:
    """Adaptive cards travel as attachments on an Activity."""
    return {
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": _adaptive_card(text, keyboard),
    }


class _ConversationStore:
    """File-backed map: aad_user_id → ConversationRef. Lazy-loaded on first read."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULT_CONVERSATIONS_PATH
        self._cache: dict[str, ConversationRef] | None = None

    def _load(self) -> dict[str, ConversationRef]:
        if self._cache is not None:
            return self._cache
        if not self._path.exists():
            self._cache = {}
            return self._cache
        raw = json.loads(self._path.read_text(encoding="utf-8") or "{}")
        self._cache = {uid: ConversationRef(**payload) for uid, payload in raw.items()}
        return self._cache

    def save(self) -> None:
        if self._cache is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {uid: asdict(ref) for uid, ref in self._cache.items()}
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def get(self, user_aad_id: str) -> ConversationRef | None:
        return self._load().get(user_aad_id)

    def upsert(self, ref: ConversationRef) -> None:
        cache = self._load()
        cache[ref.user_aad_id] = ref
        self.save()


class _TokenCache:
    """MSAL-style token cache for the Bot Framework outbound calls.

    Re-uses the same access_token until it's near expiry, then refreshes.
    Call `invalidate()` to drop the cached token immediately — needed after
    a `TEAMS_APP_PASSWORD` rotation, since otherwise we'd keep using the
    pre-rotation token until natural expiry (Microsoft tokens default to
    24h, so up to a day of failed outbound calls before self-healing).
    """

    def __init__(self, app_id: str, app_password: str) -> None:
        self._app_id = app_id
        self._app_password = app_password
        self._token: str | None = None
        self._expires_at: float = 0.0

    def invalidate(self) -> None:
        """Drop the cached token so the next `get()` fetches a fresh one.

        Called after secret rotation, or proactively from any outbound call
        site that gets a 401 from Microsoft (which would indicate the cached
        token is no longer valid).
        """
        self._token = None
        self._expires_at = 0.0

    async def get(self, client: httpx.AsyncClient) -> str:
        # 60s grace window to avoid stampedes near expiry
        if self._token is not None and time.time() < self._expires_at - 60:
            return self._token

        async def _do_fetch() -> httpx.Response:
            return await client.post(
                LOGIN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._app_id,
                    "client_secret": self._app_password,
                    "scope": BOT_SCOPE,
                },
                timeout=30.0,
            )

        # Microsoft's login endpoint occasionally 503s during regional
        # failovers — retry with backoff before failing the whole turn.
        resp = await request_with_retry(_do_fetch, label="teams-token-fetch")
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._expires_at = time.time() + int(body.get("expires_in", 3600))
        return self._token


class TeamsAdapter(ChatAdapter):
    """Microsoft Teams via Bot Framework v3 HTTP, no botbuilder-core dep."""

    def __init__(
        self,
        *,
        app_id: str | None = None,
        app_password: str | None = None,
        port: int | None = None,
        allowed_user_ids: set[str] | None = None,
        conversations_path: Path | None = None,
        bind_host: str = "0.0.0.0",
        verify_inbound: bool = True,
        metadata: OpenIdMetadataCache | None = None,
    ) -> None:
        self._app_id = app_id or os.environ.get("TEAMS_APP_ID", "")
        self._app_password = app_password or os.environ.get("TEAMS_APP_PASSWORD", "")
        self._port = port if port is not None else int(os.environ.get("PORT", "3978"))
        self._bind_host = bind_host
        self._allowed = allowed_user_ids if allowed_user_ids is not None else _read_allowed()
        self._conversations = _ConversationStore(conversations_path)
        self._token_cache = _TokenCache(self._app_id, self._app_password)

        # Inbound JWT verification. Disabling is supported for local
        # Bot Framework Emulator runs, but production MUST keep this on —
        # otherwise anyone who finds the webhook URL can fake activities.
        self._verify_inbound = verify_inbound
        self._metadata = metadata or OpenIdMetadataCache()

        self._text_handler: TextHandler | None = None
        self._command_handlers: dict[str, TextHandler] = {}
        self._button_handlers: list[tuple[str, ButtonHandler]] = []

    # --- ChatAdapter API ---

    async def send_message(
        self,
        user_id: str,
        text: str,
        keyboard: Keyboard | None = None,
    ) -> MessageRef:
        ref = self._conversations.get(user_id)
        if ref is None:
            raise RuntimeError(
                f"No ConversationReference for user {user_id!r}. The user "
                "must DM the bot at least once before we can message them."
            )
        return await self._post_activity(ref, text, keyboard)

    async def edit_message(
        self,
        ref: MessageRef,
        text: str,
        keyboard: Keyboard | None = None,
    ) -> None:
        assert isinstance(ref, _TeamsMessageRef), "ref must come from this adapter"
        activity = {
            "type": "message",
            "id": ref.activity_id,
            "attachments": [_wrap_card_attachment(text, keyboard)] if keyboard is not None else [],
            "text": text if keyboard is None else "",
        }
        url = (
            f"{ref.service_url.rstrip('/')}/v3/conversations/"
            f"{ref.conversation_id}/activities/{ref.activity_id}"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            token = await self._token_cache.get(client)

            async def _do_edit() -> httpx.Response:
                return await client.put(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=activity,
                )

            with contextlib.suppress(Exception):
                await request_with_retry(_do_edit, label="teams-edit-activity")

    def register_text_handler(self, handler: TextHandler) -> None:
        self._text_handler = handler

    def register_button_handler(self, prefix: str, handler: ButtonHandler) -> None:
        self._button_handlers.append((prefix, handler))

    def register_command_handler(self, name: str, handler: TextHandler) -> None:
        self._command_handlers[name] = handler

    def run(self) -> None:
        """Start the aiohttp webhook server. Blocks until shutdown."""
        # aiohttp is imported lazily so the module loads (and is testable)
        # without aiohttp installed; only `run()` requires it.
        from aiohttp import web

        async def handle(request: web.Request) -> web.Response:
            auth_header = request.headers.get("Authorization", "")
            body = await request.read()
            status, payload = await self.handle_request(auth_header, body)
            return web.json_response(payload, status=status)

        app = web.Application()
        app.router.add_post("/api/messages", handle)
        web.run_app(app, host=self._bind_host, port=self._port)

    # --- Public for tests + run() ---

    async def handle_request(
        self,
        auth_header: str,
        body: bytes | str,
    ) -> tuple[int, dict[str, Any]]:
        """Verify the inbound JWT (when enabled), parse the body, dispatch.

        Returns (HTTP status, JSON response body) so the aiohttp handler can
        translate directly. Exposed so unit tests can drive the whole
        request lifecycle including auth — not just `handle_activity`.
        """
        # --- JWT verification ---
        if self._verify_inbound:
            if not auth_header.startswith("Bearer "):
                log.warning("inbound request missing Bearer token")
                return 401, {"error": "missing bearer token"}
            token = auth_header[len("Bearer ") :].strip()

            # Parse body first so we can cross-check serviceUrl against the claims.
            try:
                if isinstance(body, bytes):
                    body = body.decode("utf-8")
                activity_for_check = json.loads(body) if body else {}
            except Exception:
                activity_for_check = {}

            try:
                async with httpx.AsyncClient(timeout=30.0) as http:
                    await verify_token(
                        token,
                        app_id=self._app_id,
                        metadata=self._metadata,
                        http=http,
                        activity_service_url=str(activity_for_check.get("serviceUrl") or "")
                        or None,
                    )
            except JWTVerificationError as e:
                log.warning("inbound JWT verification failed: %s", e)
                return 401, {"error": "unauthorized"}

        # --- Parse + dispatch ---
        try:
            if isinstance(body, bytes):
                body = body.decode("utf-8")
            activity = json.loads(body) if body else {}
        except Exception:
            return 400, {"error": "bad json"}

        await self.handle_activity(activity)
        return 200, {"ok": True}

    async def handle_activity(self, activity: dict[str, Any]) -> None:
        """Dispatch one inbound activity. Public so tests can drive it directly."""
        kind = activity.get("type")
        from_user = activity.get("from") or {}
        user_aad = str(from_user.get("aadObjectId") or from_user.get("id") or "")
        if user_aad not in self._allowed:
            log.info("dropping activity from non-allowed user %s", user_aad)
            return

        # Capture / refresh ConversationReference on every incoming activity
        # so proactive sends always have a fresh service_url to target.
        service_url = activity.get("serviceUrl") or ""
        conversation = activity.get("conversation") or {}
        recipient = activity.get("recipient") or {}
        if user_aad and service_url and conversation.get("id"):
            self._conversations.upsert(
                ConversationRef(
                    user_aad_id=user_aad,
                    service_url=service_url,
                    conversation_id=str(conversation["id"]),
                    bot_id=str(recipient.get("id", "")),
                )
            )

        if kind == "message":
            await self._dispatch_message(activity, user_aad)
        elif kind == "invoke":
            await self._dispatch_invoke(activity, user_aad)
        # Other activity types (conversationUpdate, typing, etc.) are ignored.

    async def _dispatch_message(self, activity: dict[str, Any], user_aad: str) -> None:
        text = str(activity.get("text") or "").strip()
        if not text:
            return
        source_ref = _TeamsMessageRef(
            service_url=str(activity.get("serviceUrl", "")),
            conversation_id=str((activity.get("conversation") or {}).get("id", "")),
            activity_id=str(activity.get("id", "")),
        )

        # Slash-prefixed messages are always routed by command, even if no
        # handler is registered for that name — never fall through to the
        # free-text agent path. This matches Telegram's behavior and avoids
        # leaking "/path/to/file" or typos into agent.reply().
        if text.startswith("/"):
            parts = text[1:].split(None, 1)
            name = parts[0] if parts else ""
            handler = self._command_handlers.get(name)
            if handler is not None:
                rest = parts[1] if len(parts) > 1 else ""
                ctx = IncomingText(user_id=user_aad, text=rest, source_ref=source_ref)
                await handler(ctx)
            # Unknown slash command — silently drop.
            return

        if self._text_handler is not None:
            ctx = IncomingText(user_id=user_aad, text=text, source_ref=source_ref)
            await self._text_handler(ctx)

    async def _dispatch_invoke(self, activity: dict[str, Any], user_aad: str) -> None:
        """Adaptive Card Action.Submit arrives as `type: invoke` with the data
        we wired into the card. Adaptive Card buttons also generate a
        `messageBack` activity in some configurations; both end up here."""
        value = activity.get("value") or {}
        callback_data = str(value.get("cb", "")).strip()
        if not callback_data:
            return
        source_ref = _TeamsMessageRef(
            service_url=str(activity.get("serviceUrl", "")),
            conversation_id=str((activity.get("conversation") or {}).get("id", "")),
            # For an invoke triggered by a card, replyToId points at the card.
            activity_id=str(activity.get("replyToId") or activity.get("id") or ""),
        )
        for prefix, handler in self._button_handlers:
            if callback_data.startswith(f"{prefix}:"):
                ctx = IncomingButton(
                    user_id=user_aad,
                    callback_data=callback_data,
                    source_ref=source_ref,
                )
                await handler(ctx)
                return

    async def _post_activity(
        self,
        ref: ConversationRef,
        text: str,
        keyboard: Keyboard | None,
    ) -> _TeamsMessageRef:
        url = f"{ref.service_url.rstrip('/')}/v3/conversations/{ref.conversation_id}/activities"
        activity: dict[str, Any] = {
            "type": "message",
            "from": {"id": ref.bot_id},
            "conversation": {"id": ref.conversation_id},
        }
        if keyboard is None:
            activity["text"] = text
        else:
            activity["attachments"] = [_wrap_card_attachment(text, keyboard)]
        async with httpx.AsyncClient(timeout=30.0) as client:
            token = await self._token_cache.get(client)

            async def _do_post() -> httpx.Response:
                return await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=activity,
                )

            resp = await request_with_retry(_do_post, label="teams-post-activity")
            resp.raise_for_status()
            data = resp.json()
            return _TeamsMessageRef(
                service_url=ref.service_url,
                conversation_id=ref.conversation_id,
                activity_id=str(data.get("id", "")),
            )


def _read_allowed() -> set[str]:
    raw = os.environ.get("ALLOWED_USERS", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


# Test surface — expose the card builder so unit tests can verify the shape
# without standing up a live webhook.
def build_adaptive_card_for_tests(text: str, keyboard: Keyboard | None) -> dict[str, Any]:
    return _adaptive_card(text, keyboard)


# Suppressing the F401 for Button — re-exported only as a hint to readers
# that the same neutral type flows in here.
_ = Button


# Help asyncio.run reuse the existing loop in tests that spin up their own.
def _ensure_event_loop() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop
