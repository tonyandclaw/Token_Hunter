"""TelegramAdapter — wraps python-telegram-bot's webhook flow.

Translates the platform-neutral `ChatAdapter` API into Telegram-specific
calls (InlineKeyboardMarkup for keyboards, message_id for MessageRef,
CallbackQueryHandler for button routing). Behavior parity with the
original main.py — no UX changes, just decoupled from main.

Called by: `src/main.py:build_adapter` when `CHAT_PLATFORM=telegram`.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from typing import Any

from src.chat.base import (
    ButtonHandler,
    ChatAdapter,
    IncomingButton,
    IncomingText,
    Keyboard,
    MessageRef,
    TextHandler,
)


@dataclass(frozen=True)
class _TgMessageRef:
    """Telegram-specific MessageRef payload. Opaque to callers."""

    chat_id: int
    message_id: int


def _to_inline_keyboard(keyboard: Keyboard | None):
    """Convert a neutral Keyboard to Telegram's InlineKeyboardMarkup.

    Returns None if keyboard is None — Telegram accepts None to mean "no
    inline keyboard attached".
    """
    if keyboard is None:
        return None
    # Lazy import so the chat.base module is testable without python-telegram-bot
    # installed in environments that only care about Teams.
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [
        [InlineKeyboardButton(b.label, callback_data=b.callback_data) for b in row]
        for row in keyboard
    ]
    return InlineKeyboardMarkup(rows)


class TelegramAdapter(ChatAdapter):
    def __init__(
        self,
        *,
        bot_token: str | None = None,
        webhook_url: str | None = None,
        webhook_secret: str | None = None,
        port: int | None = None,
        allowed_user_ids: set[str] | None = None,
    ) -> None:
        self._bot_token = bot_token or os.environ["TELEGRAM_BOT_TOKEN"]
        self._webhook_url = webhook_url or os.environ.get("TELEGRAM_WEBHOOK_URL", "")
        self._webhook_secret = webhook_secret or os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        self._port = port if port is not None else int(os.environ.get("PORT", "8080"))
        self._allowed = allowed_user_ids if allowed_user_ids is not None else _read_allowed()
        self._text_handler: TextHandler | None = None
        self._command_handlers: dict[str, TextHandler] = {}
        self._button_handlers: list[tuple[str, ButtonHandler]] = []
        self._app: Any = None  # lazily built in run()

    # --- ChatAdapter API ---

    async def send_message(
        self,
        user_id: str,
        text: str,
        keyboard: Keyboard | None = None,
    ) -> MessageRef:
        assert self._app is not None, "send_message before run()"
        chat_id = int(user_id)
        msg = await self._app.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=_to_inline_keyboard(keyboard),
        )
        return _TgMessageRef(chat_id=chat_id, message_id=msg.message_id)

    async def edit_message(
        self,
        ref: MessageRef,
        text: str,
        keyboard: Keyboard | None = None,
    ) -> None:
        assert isinstance(ref, _TgMessageRef), "ref must come from this adapter"
        assert self._app is not None, "edit_message before run()"
        with contextlib.suppress(Exception):
            await self._app.bot.edit_message_text(
                chat_id=ref.chat_id,
                message_id=ref.message_id,
                text=text,
                reply_markup=_to_inline_keyboard(keyboard),
            )

    def register_text_handler(self, handler: TextHandler) -> None:
        self._text_handler = handler

    def register_button_handler(self, prefix: str, handler: ButtonHandler) -> None:
        self._button_handlers.append((prefix, handler))

    def register_command_handler(self, name: str, handler: TextHandler) -> None:
        self._command_handlers[name] = handler

    def run(self) -> None:
        from telegram import Update
        from telegram.ext import (
            ApplicationBuilder,
            CallbackQueryHandler,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )

        app = ApplicationBuilder().token(self._bot_token).build()
        self._app = app

        # --- Free-text messages ---
        async def on_text(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
            msg = update.effective_message
            user = update.effective_user
            if not msg or not user or str(user.id) not in self._allowed:
                return
            text = (msg.text or "").strip()
            if not text or self._text_handler is None:
                return
            ctx = IncomingText(
                user_id=str(user.id),
                text=text,
                source_ref=_TgMessageRef(chat_id=msg.chat_id, message_id=msg.message_id),
            )
            await self._text_handler(ctx)

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

        # --- Slash commands ---
        for name, handler in self._command_handlers.items():
            app.add_handler(CommandHandler(name, _wrap_command(handler, self._allowed)))

        # --- Inline buttons ---
        # python-telegram-bot dispatches by regex pattern. Register one
        # CallbackQueryHandler per prefix so each maps to its own handler.
        for prefix, btn_handler in self._button_handlers:
            app.add_handler(
                CallbackQueryHandler(
                    _wrap_button(btn_handler, self._allowed),
                    pattern=f"^{prefix}:",
                )
            )

        # Start the webhook listener — blocks.
        app.run_webhook(
            listen="0.0.0.0",
            port=self._port,
            url_path="telegram/webhook",
            webhook_url=self._webhook_url,
            secret_token=self._webhook_secret,
        )


def _wrap_command(handler: TextHandler, allowed: set[str]):
    """Wrap a TextHandler so it can be passed to a python-telegram-bot CommandHandler."""

    async def adapter(update: Any, _ctx: Any) -> None:
        msg = update.effective_message
        user = update.effective_user
        if not msg or not user or str(user.id) not in allowed:
            return
        text = (msg.text or "").strip()
        ctx = IncomingText(
            user_id=str(user.id),
            text=text,
            source_ref=_TgMessageRef(chat_id=msg.chat_id, message_id=msg.message_id),
        )
        await handler(ctx)

    return adapter


def _wrap_button(handler: ButtonHandler, allowed: set[str]):
    """Wrap a ButtonHandler so it can be passed to CallbackQueryHandler."""

    async def adapter(update: Any, _ctx: Any) -> None:
        query = update.callback_query
        if query is None or query.data is None:
            return
        user = update.effective_user
        if not user or str(user.id) not in allowed:
            return
        # Acknowledge to stop the Telegram spinner before doing real work
        with contextlib.suppress(Exception):
            await query.answer()
        msg = query.message
        ref = (
            _TgMessageRef(chat_id=msg.chat_id, message_id=msg.message_id)
            if msg is not None
            else None
        )
        ctx = IncomingButton(
            user_id=str(user.id),
            callback_data=query.data,
            source_ref=ref,
        )
        await handler(ctx)

    return adapter


def _read_allowed() -> set[str]:
    raw = os.environ.get("ALLOWED_USERS", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


# Public conversion helper — used by the test that needs to assert the
# Telegram-flavored keyboard layout without standing up a full Application.
def to_inline_keyboard_for_tests(keyboard: Keyboard | None) -> Any:
    """Test-only: expose the keyboard converter without going through `send_message`."""
    return _to_inline_keyboard(keyboard)
