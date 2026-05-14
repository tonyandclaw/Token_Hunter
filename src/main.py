"""Telegram webhook entry — W1 hello-world + W2 kill-switch / session-log wiring.

Single-user only: `ALLOWED_USERS` env var is a comma-separated list of Telegram
user IDs; any other sender is silently dropped (per docs/04 §B least-privilege).
Webhook mode, not polling.

Each Telegram conversation maps to one agent `session_id`; the agent's hooks
(`src/agent.py`) carry that session_id into audit-log entries. Kill-switch and
L4 session-log writes happen here at the turn boundary, before / after the
agent call.
"""

from __future__ import annotations

import logging
import os
import uuid

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from src import kill_switch, session_log
from src.agent import reply

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("fushou.main")


def _allowed_user_ids() -> set[int]:
    raw = os.environ.get("ALLOWED_USERS", "")
    return {int(x) for x in raw.split(",") if x.strip()}


ALLOWED = _allowed_user_ids()

# One session_id per Telegram user, lazily created. A new process resets these,
# which is fine for an MVP — persistent session state lands in W4.
_SESSIONS: dict[int, str] = {}


def _session_for(user_id: int) -> str:
    sid = _SESSIONS.get(user_id)
    if sid is None:
        sid = uuid.uuid4().hex
        _SESSIONS[user_id] = sid
    return sid


async def on_message(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
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
        answer = await reply(text, session_id=_session_for(user.id))
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
