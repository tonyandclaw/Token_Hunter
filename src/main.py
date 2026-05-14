"""Telegram webhook entry — W1 hello-world + W2/W3 wiring.

Single-user only: `ALLOWED_USERS` env var is a comma-separated list of Telegram
user IDs; any other sender is silently dropped (per docs/04 §B least-privilege).
Webhook mode, not polling.

Per-turn flow:
  1. Drop the message if the sender isn't in ALLOWED_USERS.
  2. Kill-switch check (STOP/緊急停止/KILL or KILL.flag) — abort if triggered.
  3. Append the user's input to today's L4 session log.
  4. Call the agent with this user's sticky session_id + the shared
     ConfirmRegistry. Any Tier-2 tool call the agent attempts pauses the
     agent and surfaces here as a Telegram message with ✅/❌ inline
     buttons (see _notify_confirm). The button callback resolves the
     ConfirmRegistry future, releasing the agent.
  5. Append the agent's reply to L4 and send it.
"""

from __future__ import annotations

import contextlib
import logging
import os
import uuid

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src import kill_switch, session_log
from src.agent import reply
from src.tier2_confirm import ConfirmRegistry

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("fushou.main")

CONFIRM_CALLBACK_PREFIX = "t2"  # callback_data shape: "t2:<id>:yes|no"


def _allowed_user_ids() -> set[int]:
    raw = os.environ.get("ALLOWED_USERS", "")
    return {int(x) for x in raw.split(",") if x.strip()}


ALLOWED = _allowed_user_ids()

# One session_id per Telegram user, lazily created. A new process resets these,
# which is fine for an MVP — persistent session state lands in W4.
_SESSIONS: dict[int, str] = {}
# Shared registry across agent task + Telegram button handler.
_REGISTRY = ConfirmRegistry()


def _session_for(user_id: int) -> str:
    sid = _SESSIONS.get(user_id)
    if sid is None:
        sid = uuid.uuid4().hex
        _SESSIONS[user_id] = sid
    return sid


def _confirm_keyboard(confirm_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Yes", callback_data=f"{CONFIRM_CALLBACK_PREFIX}:{confirm_id}:yes"
                ),
                InlineKeyboardButton(
                    "❌ No", callback_data=f"{CONFIRM_CALLBACK_PREFIX}:{confirm_id}:no"
                ),
            ]
        ]
    )


def _make_notify(app: Application, user_id: int):
    """Factory: returns the OnSubmit notify coroutine for a given Telegram user."""

    async def notify(confirm_id: str, prompt: str) -> None:
        await app.bot.send_message(
            chat_id=user_id,
            text=prompt,
            reply_markup=_confirm_keyboard(confirm_id),
        )

    return notify


async def on_confirm_button(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Telegram CallbackQuery handler for Tier-2 confirm inline buttons."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()  # stop the spinner

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != CONFIRM_CALLBACK_PREFIX:
        return

    _, confirm_id, decision = parts
    approved = decision == "yes"
    matched = _REGISTRY.resolve(confirm_id, approved=approved)
    if not matched:
        # Stale button — confirm already resolved or timed out
        with contextlib.suppress(Exception):
            await query.edit_message_text(query.message.text + "\n\n_(已過期)_")
        return

    suffix = "✅ 已確認" if approved else "❌ 已拒絕"
    with contextlib.suppress(Exception):
        await query.edit_message_text(f"{query.message.text}\n\n{suffix}")


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or user.id not in ALLOWED:
        log.info("dropped message from non-allowed user %s", user.id if user else None)
        return

    text = (msg.text or "").strip()
    if not text:
        return

    # Kill switch — checked before anything else, including session-log writes.
    if kill_switch.triggered(text):
        log.warning("kill switch triggered by user %s", user.id)
        await msg.reply_text(kill_switch.stop_reply())
        return

    session_log.append_entry(f"user[{user.id}]: {text[:120]}")
    log.info("turn from %s: %s", user.id, text[:80])
    try:
        answer = await reply(
            text,
            session_id=_session_for(user.id),
            confirm_registry=_REGISTRY,
            notify=_make_notify(ctx.application, user.id),
        )
    except Exception:
        log.exception("agent call failed")
        session_log.append_entry(f"agent[{user.id}]: ERROR (see logs)")
        await msg.reply_text("⚠️ agent error, see server logs")
        return

    session_log.append_entry(f"agent[{user.id}]: {answer[:120]}")
    await msg.reply_text(answer)


def build_app():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = ApplicationBuilder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(CallbackQueryHandler(on_confirm_button, pattern=f"^{CONFIRM_CALLBACK_PREFIX}:"))
    return app


def main() -> None:
    # Daily housekeeping: drop any L4 session logs older than 30 days.
    pruned = session_log.prune_old()
    if pruned:
        log.info("pruned %d old session log(s)", len(pruned))

    app = build_app()
    webhook_url = os.environ["TELEGRAM_WEBHOOK_URL"]
    secret = os.environ["TELEGRAM_WEBHOOK_SECRET"]
    port = int(os.environ.get("PORT", "8080"))
    log.info("starting webhook on :%s -> %s", port, webhook_url)
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="telegram/webhook",
        webhook_url=webhook_url,
        secret_token=secret,
    )


if __name__ == "__main__":
    main()
