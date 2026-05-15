"""Platform-neutral chat adapter abstraction.

All chat-platform glue lives behind `ChatAdapter`. The rest of the codebase
(`agent.py`, the trust/escalation/undo/feedback registries, the audit log,
the forensic engine) is platform-agnostic and talks to whichever adapter
is wired up at startup.

Two concrete adapters live in this package:
  - `src/chat/telegram.py`  — TelegramAdapter (python-telegram-bot webhook)
  - `src/chat/teams.py`     — TeamsAdapter (Bot Framework v3 HTTP + Adaptive Cards)

Platform-neutral types — used in every handler signature:
  - `Button(label, callback_data)` — single tappable button
  - `Keyboard` = `list[list[Button]]` — rows of buttons
  - `MessageRef` — opaque, platform-specific handle to a previously sent
    message; only valid as input to `edit_message` on the same adapter that
    produced it. Telegram stores it as `(chat_id, message_id, "text")`;
    Teams stores it as a dict with activity_id + serviceUrl + conversation.
  - `IncomingText` — a user-typed message
  - `IncomingButton` — a button tap on a previously-sent keyboard

Handler contract (every handler is a coroutine that takes one arg):
  - text handlers   → `async def(ctx: IncomingText) -> None`
  - button handlers → `async def(ctx: IncomingButton) -> None`
  - commands        → same as text handlers, but routed by name (e.g. /trust)

Called by: `src/main.py:main` instantiates the right adapter from env, then
registers handlers and runs it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

# Opaque handle for editing a previously-sent message. Each adapter knows how
# to interpret its own MessageRefs; never inspect or construct one yourself.
MessageRef = Any


@dataclass(frozen=True)
class Button:
    """A single tappable button. `callback_data` is the payload the adapter
    will echo back to the matching button handler when the user taps it.

    Telegram constrains callback_data to 64 bytes UTF-8; Teams has no such
    limit but we keep the same convention so handlers stay portable.
    """

    label: str
    callback_data: str


# Keyboard is a list of rows; each row is a list of Buttons. Adapters render
# this in whatever way is native: Telegram InlineKeyboardMarkup, Teams
# Adaptive Card with Action.Submit per button.
Keyboard = list[list[Button]]


@dataclass(frozen=True)
class IncomingText:
    """A user-typed message arriving from the adapter.

    `user_id` is stringified for portability (Telegram int ID → str; Teams
    AAD object ID is already a str).

    `source_ref` is an opaque MessageRef pointing at this message — the
    handler can pass it to `adapter.send_message(..., reply_to=)` if it
    needs to thread a reply (rarely needed since most replies aren't threaded).
    """

    user_id: str
    text: str
    source_ref: MessageRef


@dataclass(frozen=True)
class IncomingButton:
    """A button tap echoed back from the adapter.

    `callback_data` is the same string the keyboard's `Button` carried.
    `source_ref` points at the message whose keyboard was tapped — handlers
    typically use it to `edit_message(ref, ...)` so the user sees their
    choice reflected in the original prompt.
    """

    user_id: str
    callback_data: str
    source_ref: MessageRef


TextHandler = Callable[[IncomingText], Awaitable[None]]
ButtonHandler = Callable[[IncomingButton], Awaitable[None]]


class ChatAdapter(ABC):
    """Abstract chat adapter. Subclasses implement one platform each.

    Lifecycle:
      1. caller instantiates the adapter (with platform credentials)
      2. caller registers handlers: `register_text_handler`,
         `register_button_handler`, `register_command_handler("trust", ...)`
      3. caller calls `run()` — blocks while the adapter listens for
         incoming events and dispatches to handlers
    """

    @abstractmethod
    async def send_message(
        self,
        user_id: str,
        text: str,
        keyboard: Keyboard | None = None,
    ) -> MessageRef:
        """Send a new message. Returns an opaque MessageRef for later editing."""

    @abstractmethod
    async def edit_message(
        self,
        ref: MessageRef,
        text: str,
        keyboard: Keyboard | None = None,
    ) -> None:
        """Replace the text (and optionally the keyboard) of a previous message."""

    @abstractmethod
    def register_text_handler(self, handler: TextHandler) -> None:
        """Register the fallback handler for free-text messages (non-commands)."""

    @abstractmethod
    def register_button_handler(self, prefix: str, handler: ButtonHandler) -> None:
        """Register a button handler by callback_data prefix.

        Multiple prefixes can be registered (one per `t2:`, `esc:`, `undo:`,
        `why:`, `afb:`). The adapter routes incoming button taps to the
        handler whose prefix matches.
        """

    @abstractmethod
    def register_command_handler(self, name: str, handler: TextHandler) -> None:
        """Register a slash-command handler (e.g. `/trust`, `/status`)."""

    @abstractmethod
    def run(self) -> None:
        """Start the event loop / webhook server. Blocks until shutdown."""
