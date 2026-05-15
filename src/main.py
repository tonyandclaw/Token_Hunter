"""Multi-platform entry point — picks a ChatAdapter from `CHAT_PLATFORM` env.

`CHAT_PLATFORM=telegram` (default) → src.chat.telegram.TelegramAdapter
`CHAT_PLATFORM=teams`              → src.chat.teams.TeamsAdapter

All handlers below are platform-neutral: they take `IncomingText` /
`IncomingButton` from the adapter and call back into the adapter (a single
module global `_ADAPTER`) for send/edit. Adding a third platform later is
mechanical — implement `ChatAdapter`, add it to `build_adapter`, done.

Per-turn flow (unchanged semantics from the Telegram-only version):
  1. ALLOWED_USERS gate is enforced inside the adapter; handlers receive
     only messages from allowed users.
  2. Kill-switch check (STOP / 緊急停止 / KILL or KILL.flag).
  3. Absence-mode commands (`parse_enter_command` / `parse_exit_command`).
  4. Append to L4 session log.
  5. Call agent.reply with the shared registries.
  6. Adapter routes Tier-2 confirm / undo / escalation / feedback buttons
     into their respective handlers.

Slash commands (`/help`, `/trust`, `/status`, `/profile`, `/learnings`,
`/forensic`) work the same on both platforms.
"""

from __future__ import annotations

import logging
import os
import uuid

from dotenv import load_dotenv

from src import absence_feedback, forensic_log, kill_switch, session_log, undo_window, why_button
from src.absence_feedback import FeedbackAction, FeedbackRegistry
from src.absence_mode import (
    AbsenceMode,
    AbsenceState,
    DecisionKind,
    parse_enter_command,
    parse_exit_command,
)
from src.agent import reply
from src.chat.base import Button, ChatAdapter, IncomingButton, IncomingText, Keyboard
from src.cost_meter import Alert, BudgetState, Severity, usage_summary
from src.escalation import (
    Action,
    EscalationRegistry,
    PendingEscalation,
    apply_action,
    decode_callback,
    encode_callback,
    render_proposal,
)
from src.forensic import analyze as analyze_forensic
from src.memory_inspect import render_learnings, render_user_profile
from src.recipient_tracker import KnownRecipients
from src.replay import build_report_for_call
from src.session_store import SessionStore
from src.tier2_confirm import ConfirmRegistry
from src.trust_curve import PatternState, TrustCurve
from src.undo_window import UndoRegistry
from src.voice_corpus import load_user_corpus
from src.why_button import WhyRegistry

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("fushou.main")

CONFIRM_CALLBACK_PREFIX = "t2"  # callback_data shape: "t2:<id>:yes|no"
ESCALATION_CALLBACK_PREFIX = "esc"  # callback_data shape: "esc:<id>:yes|later|never"
UNDO_CALLBACK_PREFIX = "undo"  # callback_data shape: "undo:<id>"
WHY_CALLBACK_PREFIX = "why"  # callback_data shape: "why:<id>"
FEEDBACK_CALLBACK_PREFIX = "afb"  # callback_data shape: "afb:<id>:ok|lock"
MAX_FEEDBACK_BUBBLES = 5  # cap follow-up messages so absence replay doesn't spam

# Process-wide state — `user_id` is `str` across the whole codebase
# (Telegram int IDs are stringified by the adapter).
#
# Three distinct "session" concepts; the names disambiguate them:
#   _AUDIT_SESSIONS — our internal UUID, written into audit JSONL's
#                     `session_id` field. Sticky per process; reset on restart.
#   _SDK_SESSIONS   — the SDK's own session_id (captured from the init event),
#                     passed as `resume=` on subsequent turns so the agent
#                     remembers conversation context across messages. Backed
#                     by trust/sdk_sessions.json so it survives process restart.
#   memories/sessions/{date}.md — L4 daily journal (separate from both above);
#                                  managed by src/session_log.py
_AUDIT_SESSIONS: dict[str, str] = {}
_SDK_SESSIONS = SessionStore()
# First-contact tracker — populated from audit log at main() startup,
# updated on every approved gmail send. Drives the ⚠️ first-contact banner
# in the Tier-2 confirm prompt per docs/03 §不做.
_KNOWN_RECIPIENTS = KnownRecipients()
_REGISTRY = ConfirmRegistry()
_BUDGET: BudgetState | None = None
_TRUST = TrustCurve()
_ESCALATION = EscalationRegistry()
_ABSENCE = AbsenceMode()
_UNDO = UndoRegistry()
_WHY = WhyRegistry()
_FEEDBACK = FeedbackRegistry()

# Set in main(); used by every handler to send/edit messages.
_ADAPTER: ChatAdapter | None = None


def _adapter() -> ChatAdapter:
    """Assert-and-return helper so handlers don't have to None-check every time."""
    assert _ADAPTER is not None, "handler invoked before main() wired the adapter"
    return _ADAPTER


def _alert_emoji(sev: Severity) -> str:
    return {
        Severity.INFO: "💰",
        Severity.WARNING: "⚠️",
        Severity.URGENT: "🚨",
        Severity.HALT: "🛑",
    }[sev]


def _format_alert(alert: Alert) -> str:
    return f"{_alert_emoji(alert.severity)} {alert.message}"


def _audit_session_for(user_id: str) -> str:
    """Return (creating if absent) the audit-log session UUID for this user."""
    sid = _AUDIT_SESSIONS.get(user_id)
    if sid is None:
        sid = uuid.uuid4().hex
        _AUDIT_SESSIONS[user_id] = sid
    return sid


# --- Keyboards (platform-neutral) ---


def _confirm_keyboard(confirm_id: str) -> Keyboard:
    return [
        [
            Button("✅ Yes", f"{CONFIRM_CALLBACK_PREFIX}:{confirm_id}:yes"),
            Button("❌ No", f"{CONFIRM_CALLBACK_PREFIX}:{confirm_id}:no"),
        ]
    ]


def _undo_keyboard(uid: str, seconds: int, wid: str) -> Keyboard:
    """Undo + Why-this row — both buttons shown together so the user sees them together."""
    return [
        [
            Button(f"↶ Undo ({seconds}s)", undo_window.encode_callback(uid)),
            Button("🔍 Why this?", why_button.encode_callback(wid)),
        ]
    ]


def _escalation_keyboard(eid: str) -> Keyboard:
    """1+2 layout: Auto on its own row to read as the primary action."""
    return [
        [Button("🤖 Auto (15s undo)", encode_callback(eid, Action.ESCALATE))],
        [
            Button("🛎️ 繼續每次都問", encode_callback(eid, Action.DEFER)),
            Button("❌ 永遠別自動", encode_callback(eid, Action.LOCK)),
        ],
    ]


def _feedback_keyboard(fid: str) -> Keyboard:
    return [
        [
            Button("✅ 沒問題", absence_feedback.encode_callback(fid, FeedbackAction.OK)),
            Button("🚫 不該自動", absence_feedback.encode_callback(fid, FeedbackAction.LOCK)),
        ]
    ]


# --- Tier-2 confirm notifier (handed to agent.reply as `notify`) ---


def _make_notify(user_id: str):
    """Factory: returns OnSubmit closure capturing this user_id + the global adapter."""

    async def notify(confirm_id: str, prompt: str) -> None:
        await _adapter().send_message(user_id, prompt, _confirm_keyboard(confirm_id))

    return notify


# --- Undo notifier (handed to agent.reply as `undo_notify`) ---


def _make_undo_notify(user_id: str):
    """Factory: also drops a WhyRegistry snapshot so [🔍 Why this?] has context."""

    async def undo_notify(uid: str, tool: str, args: dict, prompt: str, seconds: int) -> None:
        ctx = _WHY.submit(tool, args, tier=2)
        await _adapter().send_message(user_id, prompt, _undo_keyboard(uid, seconds, ctx.wid))

    return undo_notify


# --- Escalation proposer (handed to agent.reply as `on_eligible`) ---


def _make_eligible_handler(user_id: str):
    async def on_eligible(tool: str, args: dict, state: PatternState) -> None:
        pending = _ESCALATION.submit(tool, args, streak=state.consecutive_confirms)
        text = render_proposal(state, tool, args)
        await _adapter().send_message(user_id, text, _escalation_keyboard(pending.eid))

    return on_eligible


# --- Inline button handlers ---


async def on_confirm_button(ctx: IncomingButton) -> None:
    """`t2:<id>:yes|no` — resolves the ConfirmRegistry future."""
    parts = ctx.callback_data.split(":")
    if len(parts) != 3 or parts[0] != CONFIRM_CALLBACK_PREFIX:
        return
    _, confirm_id, decision = parts
    approved = decision == "yes"
    matched = _REGISTRY.resolve(confirm_id, approved=approved)
    suffix = "_(已過期)_" if not matched else ("✅ 已確認" if approved else "❌ 已拒絕")
    # Always echo the outcome back into the source message
    if ctx.source_ref is not None:
        await _adapter().edit_message(ctx.source_ref, f"…\n\n{suffix}")


async def on_escalation_button(ctx: IncomingButton) -> None:
    decoded = decode_callback(ctx.callback_data)
    if decoded is None:
        return
    eid, action = decoded
    pending: PendingEscalation | None = _ESCALATION.pop(eid)
    if pending is None:
        if ctx.source_ref is not None:
            await _adapter().edit_message(ctx.source_ref, "…\n\n_(已過期)_")
        return
    try:
        result = apply_action(_TRUST, pending, action)
    except ValueError as e:
        log.warning("escalation apply failed: %s", e)
        if ctx.source_ref is not None:
            await _adapter().edit_message(ctx.source_ref, f"…\n\n⚠️ {e}")
        return
    if ctx.source_ref is not None:
        await _adapter().edit_message(ctx.source_ref, f"…\n\n{result}")


async def on_undo_button(ctx: IncomingButton) -> None:
    uid = undo_window.decode_callback(ctx.callback_data)
    if uid is None:
        return
    cancelled = _UNDO.cancel(uid)
    suffix = "↶ 已取消" if cancelled else "_(已逾時,行動已執行)_"
    if ctx.source_ref is not None:
        await _adapter().edit_message(ctx.source_ref, f"…\n\n{suffix}")


async def on_why_button(ctx: IncomingButton) -> None:
    """`why:<id>` — sends the ReplayReport as a new message (not an edit)."""
    wid = why_button.decode_callback(ctx.callback_data)
    if wid is None:
        return
    snapshot = _WHY.get(wid)
    if snapshot is None:
        await _adapter().send_message(ctx.user_id, "🔍 (Why 紀錄已過期或被替換)")
        return
    try:
        report = build_report_for_call(snapshot.tool, snapshot.args, tier=snapshot.tier)
    except Exception:
        log.exception("build_report_for_call failed")
        await _adapter().send_message(ctx.user_id, "🔍 Why 報告生成失敗,請查 server log。")
        return
    await _adapter().send_message(ctx.user_id, report.render())


async def on_feedback_button(ctx: IncomingButton) -> None:
    decoded = absence_feedback.decode_callback(ctx.callback_data)
    if decoded is None:
        return
    fid, action = decoded
    pending = _FEEDBACK.pop(fid)
    if pending is None:
        if ctx.source_ref is not None:
            await _adapter().edit_message(ctx.source_ref, "…\n\n" + absence_feedback.STALE_REPLY)
        return
    try:
        result = absence_feedback.apply_feedback(_TRUST, pending, action)
    except ValueError as e:
        log.warning("absence feedback apply failed: %s", e)
        return
    if ctx.source_ref is not None:
        await _adapter().edit_message(ctx.source_ref, f"…\n\n{result}")


async def _dispatch_absence_feedback(user_id: str, prior: AbsenceState) -> None:
    """One feedback bubble per AUTO_EXECUTED decision (capped at MAX_FEEDBACK_BUBBLES)."""
    auto_decisions = [d for d in prior.decisions if d.kind is DecisionKind.AUTO_EXECUTED]
    if not auto_decisions:
        return
    bubbles = auto_decisions[-MAX_FEEDBACK_BUBBLES:]
    overflow = len(auto_decisions) - len(bubbles)
    for decision in bubbles:
        pending = _FEEDBACK.submit(
            tool=decision.tool,
            args=decision.args,
            label=decision.summary or decision.tool,
        )
        await _adapter().send_message(
            user_id,
            f"🤖 已自動執行: {decision.tool}\n  {decision.summary}",
            _feedback_keyboard(pending.fid),
        )
    if overflow > 0:
        await _adapter().send_message(
            user_id,
            f"…還有 {overflow} 筆自動執行決定(超過顯示上限 {MAX_FEEDBACK_BUBBLES})。",
        )


# --- Slash commands ---


HELP_TEXT = (
    "📖 副手指令速查\n\n"
    "斜線指令:\n"
    "  /trust            — Trust Dashboard(每個 pattern 的權限級別 + 累積證據)\n"
    "  /status           — 一頁式總覽(trust + budget + absence + 最近 forensic + 待確認)\n"
    "  /profile          — 顯示 L2 user-profile.md 內容\n"
    "  /learnings        — 顯示 L3 learnings.md 最新規則\n"
    "  /forensic <text>  — 手動掃描貼上的文字(域名隱含為 unknown)\n"
    "  /help             — 看這份說明\n\n"
    "自然語意指令:\n"
    "  「我接下來 N 小時開會」/「afk Nh」/「absence Nm」\n"
    "      → 進入 absence mode,期間自動執行已升級的 pattern,其餘暫存。\n"
    "  「我回來了」/「I'm back」\n"
    "      → 結束 absence mode,我會送結構化 replay log。\n"
    "  STOP / 緊急停止 / KILL\n"
    "      → 緊急停止;放棄當前所有行動。\n\n"
    "Inline buttons(我會主動跳出):\n"
    "  Tier-2 確認: ✅ / ❌\n"
    "  升級提議:   🤖 Auto (15s undo) / 🛎️ 繼續每次都問 / ❌ 永遠別自動\n"
    "  自動執行:   ↶ Undo (15s) / 🔍 Why this?\n"
    "  Absence 回饋: ✅ 沒問題 / 🚫 不該自動\n\n"
    "離線 (shell):\n"
    "  python -m src.cli {trust,status,budget,forensic,replay,audit,scan-text}"
)


async def on_help_command(ctx: IncomingText) -> None:
    await _adapter().send_message(ctx.user_id, HELP_TEXT)


async def on_trust_command(ctx: IncomingText) -> None:
    await _adapter().send_message(ctx.user_id, _TRUST.summary())


def _render_status() -> str:
    """Pure status renderer — testable offline."""
    from datetime import UTC, datetime  # local: only this branch needs it

    lines = ["📊 副手狀態"]
    patterns = _TRUST.list_patterns()
    lines.append(f"  Trust patterns: {len(patterns)}")
    if patterns:
        top = patterns[0]
        lines.append(f"    最近活動: {top.level.name} · {top.tool} [{top.key}]")

    today = datetime.now(UTC).date()
    today_usage = usage_summary(since=today, until=today)
    if _BUDGET is not None:
        usage = usage_summary()
        pct = (usage.cost_usd / _BUDGET.budget_usd * 100) if _BUDGET.budget_usd > 0 else 0
        flag = " 🛑" if _BUDGET.halted else (" 🚨" if _BUDGET.tier2_suspended else "")
        lines.append(
            f"  Budget: {usage.cost_usd:.2f} / {_BUDGET.budget_usd:.0f} USD "
            f"({pct:.0f}%){flag} · 今日 {today_usage.cost_usd:.2f} USD"
        )
    else:
        lines.append(f"  Budget: 未啟用 (COST_BUDGET_USD=0) · 今日 {today_usage.cost_usd:.2f} USD")

    if _ABSENCE.is_active():
        state = _ABSENCE.state()
        if state is not None:
            rem = state.remaining()
            lines.append(f"  Absence: 🌙 ACTIVE — 剩餘 {rem}, 已記錄 {len(state.decisions)} 筆決定")
    else:
        lines.append("  Absence: 非啟用")

    recent = forensic_log.read_recent(limit=3, min_severity="warning")
    if recent:
        lines.append("  最近 forensic 警示:")
        for row in recent:
            hits = ",".join(row.get("injection_hits") or []) or "(no patterns)"
            lines.append(
                f"    {row.get('ts')}  {row.get('severity')}  "
                f"{row.get('sender_domain') or '?'}  hits=[{hits}]"
            )
    else:
        lines.append("  Forensic: 過去無警示等級事件")

    lines.append(
        "  Pending: "
        f"T2 confirm {_REGISTRY.pending_count()} / "
        f"Undo {_UNDO.pending_count()} / "
        f"Escalation {_ESCALATION.pending_count()} / "
        f"Feedback {_FEEDBACK.pending_count()}"
    )
    return "\n".join(lines)


async def on_status_command(ctx: IncomingText) -> None:
    await _adapter().send_message(ctx.user_id, _render_status())


async def on_profile_command(ctx: IncomingText) -> None:
    await _adapter().send_message(ctx.user_id, render_user_profile())


async def on_learnings_command(ctx: IncomingText) -> None:
    await _adapter().send_message(ctx.user_id, render_learnings())


async def on_forensic_command(ctx: IncomingText) -> None:
    """`/forensic <text>` — `ctx.text` carries everything after the command name."""
    body = ctx.text.strip()
    if not body:
        await _adapter().send_message(ctx.user_id, "用法: /forensic <要掃描的文字>")
        return
    report = analyze_forensic("unknown", body)
    await _adapter().send_message(ctx.user_id, report.render())


# --- Main turn flow ---


async def on_text(ctx: IncomingText) -> None:
    """Free-text message dispatch — kill switch, absence commands, agent."""
    user_id = ctx.user_id
    text = ctx.text

    if kill_switch.triggered(text):
        log.warning("kill switch triggered by user %s", user_id)
        await _adapter().send_message(user_id, kill_switch.stop_reply())
        return

    if _BUDGET is not None and _BUDGET.halted:
        await _adapter().send_message(
            user_id, "🛑 預算已超過 120%,agent 暫停接受新指令。請手動處理或重設預算。"
        )
        return

    parsed = parse_enter_command(text)
    if parsed is not None:
        if _ABSENCE.is_active():
            await _adapter().send_message(
                user_id,
                "⚠️ absence mode 已在執行中。先輸入「我回來了」結束才能重新進入。",
            )
            return
        duration, note = parsed
        state = _ABSENCE.enter(duration, note=note)
        session_log.append_entry(f"user[{user_id}]: ENTER absence {duration} note={note[:80]}")
        await _adapter().send_message(
            user_id,
            "🌙 已進入 absence mode。\n"
            f"  時長: {duration}\n"
            f"  結束: {state.ends_at.strftime('%Y-%m-%dT%H:%M:%SZ')}\n\n"
            "期間 AUTO_AUDITED+ pattern 會自動執行,MANUAL pattern 暫存等你回來決定。",
        )
        return

    if parse_exit_command(text) or _ABSENCE.is_expired():
        prior = _ABSENCE.exit()
        if prior is not None:
            replay = _ABSENCE.render_replay(state=prior)
            session_log.append_entry(f"user[{user_id}]: EXIT absence")
            await _adapter().send_message(user_id, "⏰ 歡迎回來。\n\n" + replay)
            await _dispatch_absence_feedback(user_id, prior)
            if parse_exit_command(text):
                return

    session_log.append_entry(f"user[{user_id}]: {text[:120]}")
    log.info("turn from %s: %s", user_id, text[:80])
    try:
        answer, sdk_sid = await reply(
            text,
            session_id=_audit_session_for(user_id),
            confirm_registry=_REGISTRY,
            notify=_make_notify(user_id),
            trust_curve=_TRUST,
            on_eligible=(None if _ABSENCE.is_active() else _make_eligible_handler(user_id)),
            absence_mode=_ABSENCE,
            undo_registry=_UNDO,
            undo_notify=_make_undo_notify(user_id),
            voice_corpus=load_user_corpus(),
            known_recipients=_KNOWN_RECIPIENTS,
            # Pass last-captured SDK session for context continuity. None on
            # the very first turn ever for this user — first turn establishes
            # the session and we capture sdk_sid from the init event below.
            # Survives process restart because _SDK_SESSIONS is file-backed.
            resume_sdk_session=_SDK_SESSIONS.get(user_id),
        )
    except Exception:
        log.exception("agent call failed")
        session_log.append_entry(f"agent[{user_id}]: ERROR (see logs)")
        await _adapter().send_message(user_id, "⚠️ agent error, see server logs")
        return

    # Persist the SDK's session_id so the next turn can resume with full context.
    # SessionStore.set is a no-op when the value hasn't changed, so we're not
    # churning the file on every turn within the same session.
    if sdk_sid:
        _SDK_SESSIONS.set(user_id, sdk_sid)

    session_log.append_entry(f"agent[{user_id}]: {answer[:120]}")
    await _adapter().send_message(user_id, answer)

    if _BUDGET is not None:
        for alert in _BUDGET.poll():
            await _adapter().send_message(user_id, _format_alert(alert))


# --- Adapter wiring ---


def build_adapter() -> ChatAdapter:
    """Pick the adapter based on CHAT_PLATFORM env var. Defaults to telegram."""
    platform = os.environ.get("CHAT_PLATFORM", "telegram").lower()
    if platform == "telegram":
        from src.chat.telegram import TelegramAdapter

        return TelegramAdapter()
    if platform == "teams":
        from src.chat.teams import TeamsAdapter

        return TeamsAdapter()
    raise ValueError(f"Unknown CHAT_PLATFORM {platform!r}; expected 'telegram' or 'teams'")


def wire_handlers(adapter: ChatAdapter) -> None:
    """Register every handler with the adapter. Same set on every platform."""
    adapter.register_text_handler(on_text)
    adapter.register_command_handler("help", on_help_command)
    adapter.register_command_handler("trust", on_trust_command)
    adapter.register_command_handler("status", on_status_command)
    adapter.register_command_handler("profile", on_profile_command)
    adapter.register_command_handler("learnings", on_learnings_command)
    adapter.register_command_handler("forensic", on_forensic_command)
    adapter.register_button_handler(CONFIRM_CALLBACK_PREFIX, on_confirm_button)
    adapter.register_button_handler(ESCALATION_CALLBACK_PREFIX, on_escalation_button)
    adapter.register_button_handler(UNDO_CALLBACK_PREFIX, on_undo_button)
    adapter.register_button_handler(WHY_CALLBACK_PREFIX, on_why_button)
    adapter.register_button_handler(FEEDBACK_CALLBACK_PREFIX, on_feedback_button)


def main() -> None:
    # Daily housekeeping: drop any L4 session logs older than 30 days.
    pruned = session_log.prune_old()
    if pruned:
        log.info("pruned %d old session log(s)", len(pruned))

    # Trust curve: load any prior state from trust/curves.json.
    _TRUST.load()
    log.info("trust curve loaded: %d known patterns", len(_TRUST.list_patterns()))

    # SDK session map: load so cross-restart context resume works.
    _SDK_SESSIONS.load()
    log.info("sdk sessions loaded: %d known users", _SDK_SESSIONS.count())

    # First-contact tracker: scan audit logs for past approved gmail sends so
    # we don't flash a "first contact" banner on every previously-trusted
    # recipient after a restart.
    from src.audit import LOGS_DIR as _AUDIT_LOGS_DIR

    _KNOWN_RECIPIENTS.load_from_audit(_AUDIT_LOGS_DIR)
    log.info("known recipients loaded: %d", _KNOWN_RECIPIENTS.count())

    # Cost budget — opt-in via COST_BUDGET_USD; missing/zero disables alerts.
    global _BUDGET, _ADAPTER
    budget_raw = os.environ.get("COST_BUDGET_USD", "0")
    try:
        budget = float(budget_raw)
    except ValueError:
        budget = 0.0
    if budget > 0:
        _BUDGET = BudgetState(budget)
        log.info("cost budget enforcement enabled: %.2f USD", budget)

    _ADAPTER = build_adapter()
    wire_handlers(_ADAPTER)
    platform = os.environ.get("CHAT_PLATFORM", "telegram").lower()
    log.info("starting %s adapter", platform)
    _ADAPTER.run()


if __name__ == "__main__":
    main()
