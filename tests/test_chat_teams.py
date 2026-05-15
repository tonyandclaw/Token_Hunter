"""TeamsAdapter unit tests — no live Bot Framework calls.

Covers:
  - _adaptive_card builder (the shape Teams actually consumes)
  - encode/decode round-trip with callback_data prefixes
  - ConversationStore file roundtrip
  - handle_activity dispatches to text/command/button handlers
  - ALLOWED_USERS gating
  - Capture-on-first-activity of the ConversationReference
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from src.chat.base import Button, IncomingButton, IncomingText
from src.chat.teams import (
    ConversationRef,
    TeamsAdapter,
    _ConversationStore,
    _TeamsMessageRef,
    build_adaptive_card_for_tests,
)

# --- _adaptive_card ---


def test_adaptive_card_text_only():
    card = build_adaptive_card_for_tests("hello", None)
    assert card["type"] == "AdaptiveCard"
    assert card["version"] == "1.4"
    # Body has a single TextBlock; no ActionSet
    assert len(card["body"]) == 1
    assert card["body"][0]["type"] == "TextBlock"
    assert card["body"][0]["text"] == "hello"


def test_adaptive_card_with_one_row_of_buttons():
    kb = [[Button("Yes", "t2:abc:yes"), Button("No", "t2:abc:no")]]
    card = build_adaptive_card_for_tests("Confirm?", kb)
    # TextBlock + one ActionSet
    assert len(card["body"]) == 2
    assert card["body"][1]["type"] == "ActionSet"
    actions = card["body"][1]["actions"]
    assert len(actions) == 2
    assert actions[0]["type"] == "Action.Submit"
    assert actions[0]["title"] == "Yes"
    # The Submit's `data.cb` must carry the callback_data verbatim — this is
    # the contract that lets the button handlers stay platform-neutral.
    assert actions[0]["data"]["cb"] == "t2:abc:yes"
    assert actions[1]["data"]["cb"] == "t2:abc:no"


def test_adaptive_card_with_multiple_rows():
    """Each row becomes its own ActionSet so rows stack vertically in the card."""
    kb = [
        [Button("a", "x:a")],
        [Button("b", "x:b"), Button("c", "x:c")],
    ]
    card = build_adaptive_card_for_tests("pick", kb)
    # TextBlock + 2 ActionSets
    assert len(card["body"]) == 3
    assert all(b["type"] in ("TextBlock", "ActionSet") for b in card["body"])


def test_adaptive_card_text_wraps():
    """Long text must be marked wrap=true so Teams doesn't ellipsize."""
    card = build_adaptive_card_for_tests("x" * 1000, None)
    assert card["body"][0].get("wrap") is True


# --- _ConversationStore ---


def test_conversation_store_starts_empty(tmp_path: Path):
    store = _ConversationStore(path=tmp_path / "convos.json")
    assert store.get("unknown-user") is None


def test_conversation_store_roundtrip(tmp_path: Path):
    log = tmp_path / "convos.json"
    s1 = _ConversationStore(path=log)
    ref = ConversationRef(
        user_aad_id="aad-1",
        service_url="https://smba.example.test/",
        conversation_id="conv-1",
        bot_id="bot-x",
    )
    s1.upsert(ref)
    # Roundtrip — fresh store reads what the prior wrote
    s2 = _ConversationStore(path=log)
    out = s2.get("aad-1")
    assert out is not None
    assert out.conversation_id == "conv-1"
    assert out.service_url == "https://smba.example.test/"


def test_conversation_store_json_is_human_readable(tmp_path: Path):
    log = tmp_path / "convos.json"
    store = _ConversationStore(path=log)
    store.upsert(
        ConversationRef(
            user_aad_id="aad-1",
            service_url="https://smba.example.test/",
            conversation_id="conv-1",
            bot_id="bot-x",
        )
    )
    payload = json.loads(log.read_text(encoding="utf-8"))
    assert "aad-1" in payload
    assert payload["aad-1"]["conversation_id"] == "conv-1"


# --- handle_activity dispatch ---


def _adapter(tmp_path: Path, *, allowed: set[str] | None = None) -> TeamsAdapter:
    return TeamsAdapter(
        app_id="test-app",
        app_password="test-secret",
        allowed_user_ids=allowed if allowed is not None else {"aad-1"},
        conversations_path=tmp_path / "convos.json",
    )


def _activity(
    *,
    kind: str = "message",
    user_aad: str = "aad-1",
    text: str | None = None,
    value: dict | None = None,
    reply_to: str | None = None,
) -> dict:
    a: dict = {
        "type": kind,
        "id": "act-1",
        "serviceUrl": "https://smba.example.test/",
        "channelId": "msteams",
        "from": {"id": "29:bot-channel", "aadObjectId": user_aad, "name": "alice"},
        "conversation": {"id": "conv-1"},
        "recipient": {"id": "28:bot-id", "name": "fushou"},
    }
    if text is not None:
        a["text"] = text
    if value is not None:
        a["value"] = value
    if reply_to is not None:
        a["replyToId"] = reply_to
    return a


def test_handle_activity_routes_text_to_text_handler(tmp_path: Path):
    a = _adapter(tmp_path)
    captured: list[IncomingText] = []

    async def handler(ctx: IncomingText) -> None:
        captured.append(ctx)

    a.register_text_handler(handler)
    asyncio.run(a.handle_activity(_activity(text="hello world")))
    assert len(captured) == 1
    assert captured[0].user_id == "aad-1"
    assert captured[0].text == "hello world"
    assert isinstance(captured[0].source_ref, _TeamsMessageRef)


def test_handle_activity_routes_slash_command(tmp_path: Path):
    a = _adapter(tmp_path)
    captured: list[IncomingText] = []

    async def trust_handler(ctx: IncomingText) -> None:
        captured.append(ctx)

    a.register_command_handler("trust", trust_handler)
    asyncio.run(a.handle_activity(_activity(text="/trust")))
    assert len(captured) == 1
    # The leading slash + name is stripped; `text` carries the rest
    assert captured[0].text == ""


def test_handle_activity_command_args_passed_through(tmp_path: Path):
    """`/forensic some text here` → handler receives `some text here`."""
    a = _adapter(tmp_path)
    captured: list[IncomingText] = []

    async def forensic_handler(ctx: IncomingText) -> None:
        captured.append(ctx)

    a.register_command_handler("forensic", forensic_handler)
    asyncio.run(a.handle_activity(_activity(text="/forensic please scan this body")))
    assert captured[0].text == "please scan this body"


def test_handle_activity_unknown_command_falls_through_to_text_handler(tmp_path: Path):
    """A slash-prefixed message with no registered handler goes nowhere — by design."""
    a = _adapter(tmp_path)
    text_seen: list[IncomingText] = []

    async def handler(ctx: IncomingText) -> None:
        text_seen.append(ctx)

    a.register_text_handler(handler)
    asyncio.run(a.handle_activity(_activity(text="/unknowncmd")))
    # No command match → no fallthrough; safer than letting "/x" leak into agent
    assert text_seen == []


def test_handle_activity_invoke_routes_to_button_handler(tmp_path: Path):
    a = _adapter(tmp_path)
    seen: list[IncomingButton] = []

    async def btn(ctx: IncomingButton) -> None:
        seen.append(ctx)

    a.register_button_handler("t2", btn)
    asyncio.run(
        a.handle_activity(
            _activity(kind="invoke", value={"cb": "t2:abc:yes"}, reply_to="card-act-id")
        )
    )
    assert len(seen) == 1
    assert seen[0].callback_data == "t2:abc:yes"
    assert isinstance(seen[0].source_ref, _TeamsMessageRef)
    # replyToId from the invoke becomes the activity_id of the source_ref
    assert seen[0].source_ref.activity_id == "card-act-id"


def test_handle_activity_invoke_routes_to_correct_prefix(tmp_path: Path):
    """Multiple button handlers; only the matching prefix is called."""
    a = _adapter(tmp_path)
    t2_calls: list[str] = []
    esc_calls: list[str] = []

    async def t2(ctx: IncomingButton) -> None:
        t2_calls.append(ctx.callback_data)

    async def esc(ctx: IncomingButton) -> None:
        esc_calls.append(ctx.callback_data)

    a.register_button_handler("t2", t2)
    a.register_button_handler("esc", esc)
    asyncio.run(
        a.handle_activity(_activity(kind="invoke", value={"cb": "esc:abc:yes"}, reply_to="x"))
    )
    assert esc_calls == ["esc:abc:yes"]
    assert t2_calls == []


def test_handle_activity_drops_non_allowed_user(tmp_path: Path):
    a = _adapter(tmp_path, allowed={"aad-friend"})
    captured: list[IncomingText] = []

    async def handler(ctx: IncomingText) -> None:
        captured.append(ctx)

    a.register_text_handler(handler)
    asyncio.run(a.handle_activity(_activity(user_aad="aad-stranger", text="hi")))
    assert captured == []


def test_handle_activity_upserts_conversation_reference(tmp_path: Path):
    """First activity from a user must persist their ConversationReference."""
    log = tmp_path / "convos.json"
    a = _adapter(tmp_path)
    asyncio.run(a.handle_activity(_activity(text="hi")))
    payload = json.loads(log.read_text(encoding="utf-8"))
    assert "aad-1" in payload
    assert payload["aad-1"]["conversation_id"] == "conv-1"
    assert payload["aad-1"]["service_url"] == "https://smba.example.test/"


def test_send_message_raises_when_no_conversation_ref(tmp_path: Path):
    """Proactive send to a user we've never seen — must raise, not silently no-op."""
    a = _adapter(tmp_path)
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(a.send_message("never-seen-user", "hi"))
    assert "ConversationReference" in str(ei.value)


def test_conversation_ref_payload_round_trips_through_asdict():
    """Pinned shape — used by _ConversationStore.save and by debug tooling."""
    ref = ConversationRef(
        user_aad_id="aad-1",
        service_url="https://x.test/",
        conversation_id="conv-1",
        bot_id="bot-x",
    )
    d = asdict(ref)
    assert d["user_aad_id"] == "aad-1"
    # last_updated_ts is set automatically — present and positive
    assert d["last_updated_ts"] > 0


# --- handle_request (JWT verification wrapper) ---


def _adapter_no_verify(tmp_path: Path, *, allowed: set[str] | None = None) -> TeamsAdapter:
    """Adapter with JWT verification turned off — used by the dispatch tests above."""
    return TeamsAdapter(
        app_id="test-app",
        app_password="test-secret",
        allowed_user_ids=allowed if allowed is not None else {"aad-1"},
        conversations_path=tmp_path / "convos.json",
        verify_inbound=False,
    )


def test_handle_request_skips_jwt_when_verify_disabled(tmp_path: Path):
    """`verify_inbound=False` lets bot framework emulator runs work."""
    import json as _json

    a = _adapter_no_verify(tmp_path)
    seen: list[str] = []

    async def handler(ctx: IncomingText) -> None:
        seen.append(ctx.text)

    a.register_text_handler(handler)
    body = _json.dumps(_activity(text="hi")).encode("utf-8")
    status, payload = asyncio.run(a.handle_request("", body))
    assert status == 200
    assert payload == {"ok": True}
    assert seen == ["hi"]


def test_handle_request_rejects_missing_bearer(tmp_path: Path):
    """`verify_inbound=True` (default) — no auth header → 401."""
    a = TeamsAdapter(
        app_id="test-app",
        app_password="test-secret",
        allowed_user_ids={"aad-1"},
        conversations_path=tmp_path / "convos.json",
        # verify_inbound defaults to True
    )
    seen: list[str] = []

    async def handler(ctx: IncomingText) -> None:
        seen.append(ctx.text)

    a.register_text_handler(handler)
    import json as _json

    body = _json.dumps(_activity(text="hi")).encode("utf-8")
    status, payload = asyncio.run(a.handle_request("", body))
    assert status == 401
    assert "missing bearer" in payload.get("error", "")
    # Most importantly: handler must NOT have been invoked
    assert seen == []


def test_handle_request_returns_400_on_bad_json(tmp_path: Path):
    """Valid-shaped flow but body is garbage — 400, not 500."""
    a = _adapter_no_verify(tmp_path)
    status, payload = asyncio.run(a.handle_request("", b"{not json"))
    assert status == 400
    assert "bad json" in payload.get("error", "")


def test_handle_request_accepts_string_body(tmp_path: Path):
    """handle_request tolerates str AND bytes bodies — useful in tests."""
    import json as _json

    a = _adapter_no_verify(tmp_path)
    status, _ = asyncio.run(a.handle_request("", _json.dumps(_activity(text="hi"))))
    assert status == 200


def test_verify_inbound_default_is_true(tmp_path: Path):
    """Pinned: production-safe default. Disabling must be explicit."""
    a = TeamsAdapter(
        app_id="x",
        app_password="y",
        allowed_user_ids=set(),
        conversations_path=tmp_path / "c.json",
    )
    assert a._verify_inbound is True  # noqa: SLF001


# --- _TokenCache.invalidate ---


def test_token_cache_invalidate_drops_cached_token():
    """After a secret rotation, .invalidate() must force the next get() to refetch."""
    from src.chat.teams import _TokenCache

    cache = _TokenCache("app-id", "secret")
    # Simulate a successful prior fetch
    cache._token = "old-token"  # noqa: SLF001
    cache._expires_at = 9_999_999_999  # noqa: SLF001 — far future
    cache.invalidate()
    assert cache._token is None  # noqa: SLF001
    assert cache._expires_at == 0.0  # noqa: SLF001


def test_token_cache_invalidate_is_idempotent():
    """Calling invalidate twice in a row must not raise."""
    from src.chat.teams import _TokenCache

    cache = _TokenCache("app-id", "secret")
    cache.invalidate()
    cache.invalidate()
    assert cache._token is None  # noqa: SLF001
