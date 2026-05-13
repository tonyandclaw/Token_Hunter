"""Telegram webhook entry — W1 hello-world.

Single-user only: `ALLOWED_USERS` env var is a comma-separated list of Telegram
user IDs; any other sender is silently dropped (per docs/04 §B least-privilege).
Webhook mode, not polling.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from src.agent import reply

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("fushou.main")


def _allowed_user_ids() -> set[int]:
    raw = os.environ.get("ALLOWED_USERS", "")
    return {int(x) for x in raw.split(",") if x.strip()}


ALLOWED = _allowed_user_ids()


async def on_message(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or user.id not in ALLOWED:
        log.info("dropped message from non-allowed user %s", user.id if user else None)
        return

    text = (msg.text or "").strip()
    if not text:
        return

    log.info("turn from %s: %s", user.id, text[:80])
    try:
        answer = await reply(text)
    except Exception:
        log.exception("agent call failed")
        await msg.reply_text("⚠️ agent error, see server logs")
        return

    await msg.reply_text(answer)


def build_app():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = ApplicationBuilder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return app


def main() -> None:
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
