"""FakeChatAdapter for end-to-end tests.

Implements `ChatAdapter` in-memory:
  - send_message / edit_message record into `sent` / `edited` lists
  - feed_text(user_id, text) drives the registered text/command handler
  - feed_button(user_id, callback_data, source_ref=) drives the matching
    button handler

This lets tests exercise the full main.on_text → guards → agent → adapter
loop without a real Telegram/Teams webhook OR the Claude Agent SDK. The
agent itself is monkeypatched to a deterministic stub per scenario.

Not a production adapter — never registered via build_adapter; only used
in tests.
"""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass
class _SentMessage:
    user_id: str
    text: str
    keyboard: Keyboard | None
    ref: MessageRef


@dataclass
class _EditedMessage:
    ref: MessageRef
    text: str
    keyboard: Keyboard | None


class FakeChatAdapter(ChatAdapter):
    """In-memory adapter for E2E tests. Records sends + lets tests inject events."""

    def __init__(self, *, allowed_user_ids: set[str] | None = None) -> None:
        self.sent: list[_SentMessage] = []
        self.edited: list[_EditedMessage] = []
        self._text_handler: TextHandler | None = None
        self._command_handlers: dict[str, TextHandler] = {}
        self._button_handlers: list[tuple[str, ButtonHandler]] = []
        self._next_ref_id = 0
        # Mirror the real adapters' allowlist gate: messages from non-allowed
        # users are silently dropped. None = "allow everyone" for tests that
        # don't care about the gate.
        self._allowed = allowed_user_ids

    # --- ChatAdapter API ---

    async def send_message(
        self,
        user_id: str,
        text: str,
        keyboard: Keyboard | None = None,
    ) -> MessageRef:
        self._next_ref_id += 1
        ref = f"ref-{self._next_ref_id}"
        self.sent.append(_SentMessage(user_id=user_id, text=text, keyboard=keyboard, ref=ref))
        return ref

    async def edit_message(
        self,
        ref: MessageRef,
        text: str,
        keyboard: Keyboard | None = None,
    ) -> None:
        self.edited.append(_EditedMessage(ref=ref, text=text, keyboard=keyboard))

    def register_text_handler(self, handler: TextHandler) -> None:
        self._text_handler = handler

    def register_button_handler(self, prefix: str, handler: ButtonHandler) -> None:
        self._button_handlers.append((prefix, handler))

    def register_command_handler(self, name: str, handler: TextHandler) -> None:
        self._command_handlers[name] = handler

    def run(self) -> None:  # pragma: no cover — never called in tests
        raise RuntimeError("FakeChatAdapter.run() — tests should drive via feed_*")

    # --- Test drivers (not part of ChatAdapter) ---

    async def feed_text(self, user_id: str, text: str) -> None:
        """Simulate a user typing free-text. Routes commands by leading '/'."""
        if self._allowed is not None and user_id not in self._allowed:
            return  # mirror real adapter behavior
        if text.startswith("/"):
            parts = text[1:].split(None, 1)
            name = parts[0] if parts else ""
            rest = parts[1] if len(parts) > 1 else ""
            handler = self._command_handlers.get(name)
            if handler is not None:
                ctx = IncomingText(user_id=user_id, text=rest, source_ref=f"src-{user_id}")
                await handler(ctx)
            # Unknown slash command — silently drop (matches real adapter)
            return
        if self._text_handler is not None:
            ctx = IncomingText(user_id=user_id, text=text, source_ref=f"src-{user_id}")
            await self._text_handler(ctx)

    async def feed_button(
        self,
        user_id: str,
        callback_data: str,
        source_ref: MessageRef = "src-button",
    ) -> None:
        """Simulate a user tapping an inline button."""
        if self._allowed is not None and user_id not in self._allowed:
            return
        for prefix, handler in self._button_handlers:
            if callback_data.startswith(f"{prefix}:"):
                ctx = IncomingButton(
                    user_id=user_id,
                    callback_data=callback_data,
                    source_ref=source_ref,
                )
                await handler(ctx)
                return

    # --- Test assertions ---

    def last_sent(self) -> _SentMessage:
        assert self.sent, "no messages sent"
        return self.sent[-1]

    def sent_to(self, user_id: str) -> list[_SentMessage]:
        return [m for m in self.sent if m.user_id == user_id]

    def keyboard_callbacks(self, msg_index: int = -1) -> list[str]:
        """Flatten a sent message's keyboard buttons to a list of callback_data."""
        m = self.sent[msg_index]
        if m.keyboard is None:
            return []
        out: list[str] = []
        for row in m.keyboard:
            for btn in row:
                if isinstance(btn, Button):
                    out.append(btn.callback_data)
        return out

    def reset(self) -> None:
        self.sent.clear()
        self.edited.clear()
