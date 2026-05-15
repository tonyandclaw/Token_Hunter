"""Absence Mode — time-windowed self-running per docs/02 Scene 5 + README #5.

When the user says "我接下來 N 小時開會,你自己處理":
- Agent enters absence mode for N hours.
- During the window:
  - Tier-2 tools at AUTO_AUDITED level still auto-execute (the curve already
    earned the right; the user has just acknowledged they won't answer).
  - Tier-2 tools at MANUAL level are denied (can't ask the user in real time)
    and queued in the absence log for later review.
  - The propose-escalation callback is suppressed — no new trust escalations
    while the user is away (they can't accept in real time, and we don't want
    the system to drift toward "silence = approve").
- On exit (explicit user command, or timer expiry detected on next message):
  - A structured replay log is sent listing every queued/executed decision.

This module is pure logic + a small command parser. Telegram wiring lives in
src/main.py. State is in-memory only — a process restart clears any active
window, which is the correct behaviour (you don't want to silently resume
auto-mode after a crash).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any


class DecisionKind(Enum):
    AUTO_EXECUTED = "auto_executed"  # auto-ran because trust level allowed it
    BLOCKED_MANUAL = "blocked_manual"  # MANUAL pattern; deferred to user's return
    BLOCKED_LOCKED = "blocked_locked"  # ALWAYS_ASK pattern; deferred


# Icons for the replay log, mapped by kind.value
_DECISION_ICON: dict[str, str] = {
    DecisionKind.AUTO_EXECUTED.value: "🤖",
    DecisionKind.BLOCKED_MANUAL.value: "⏸️",
    DecisionKind.BLOCKED_LOCKED.value: "⛔",
}


@dataclass(frozen=True)
class AbsenceDecision:
    ts: str  # HH:MM:SSZ, relative timestamp within the window
    kind: DecisionKind
    tool: str
    summary: str  # short human description derived from tool args
    args: dict[str, Any]  # raw tool args, used by the per-decision feedback flow
    # to lock the right pattern (curve key derives from args).


@dataclass
class AbsenceState:
    started_at: datetime
    ends_at: datetime
    note: str  # raw user message that started the window
    decisions: list[AbsenceDecision] = field(default_factory=list)

    def is_active(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) < self.ends_at

    def is_expired(self, now: datetime | None = None) -> bool:
        return not self.is_active(now)

    def remaining(self, now: datetime | None = None) -> timedelta:
        diff = self.ends_at - (now or datetime.now(UTC))
        return diff if diff > timedelta(0) else timedelta(0)


def summarize_tool_call(tool: str, args: dict[str, Any]) -> str:
    """Best-effort short summary, used as the right-hand column in the replay log."""
    args = args or {}
    if tool.startswith("mcp__gmail__send") or tool.startswith("mcp__gmail__reply"):
        to = str(args.get("to", "")).strip() or "?"
        subj = str(args.get("subject", "")).strip()
        return f"→ {to}" + (f" / {subj[:40]}" if subj else "")
    if tool.startswith("mcp__bluesky__"):
        text = str(args.get("text", "")).strip()
        return text[:60] + ("…" if len(text) > 60 else "")
    if tool.startswith("mcp__memory__write_learning"):
        cat = str(args.get("category", "")).strip() or "?"
        return f"category={cat}"
    if tool.startswith("mcp__memory__write_user_profile"):
        note = str(args.get("note", "")).strip()
        return note[:60] + ("…" if len(note) > 60 else "")
    return ""


class AbsenceMode:
    """Per-process state for absence windows. main.py owns one instance."""

    def __init__(self) -> None:
        self._state: AbsenceState | None = None

    def enter(
        self,
        duration: timedelta,
        note: str = "",
        *,
        now: datetime | None = None,
    ) -> AbsenceState:
        if duration <= timedelta(0):
            raise ValueError("duration must be positive")
        start = now or datetime.now(UTC)
        self._state = AbsenceState(started_at=start, ends_at=start + duration, note=note)
        return self._state

    def exit(self) -> AbsenceState | None:
        """Explicit exit. Returns the prior state (for the replay log) and clears it."""
        prior = self._state
        self._state = None
        return prior

    def is_active(self, now: datetime | None = None) -> bool:
        return self._state is not None and self._state.is_active(now)

    def is_expired(self, now: datetime | None = None) -> bool:
        return self._state is not None and self._state.is_expired(now)

    def state(self) -> AbsenceState | None:
        return self._state

    def record(
        self,
        kind: DecisionKind,
        tool: str,
        args: dict[str, Any] | None = None,
        *,
        now: datetime | None = None,
    ) -> AbsenceDecision:
        if self._state is None:
            raise RuntimeError("cannot record outside an active absence window")
        ts = (now or datetime.now(UTC)).strftime("%H:%M:%SZ")
        decision = AbsenceDecision(
            ts=ts,
            kind=kind,
            tool=tool,
            summary=summarize_tool_call(tool, args or {}),
            args=dict(args or {}),
        )
        self._state.decisions.append(decision)
        return decision

    def render_replay(self, state: AbsenceState | None = None) -> str:
        target = state if state is not None else self._state
        if target is None:
            return "(無 absence 紀錄)"
        header = (
            f"📋 Absence Replay — "
            f"{target.started_at.strftime('%Y-%m-%dT%H:%M:%SZ')} → "
            f"{target.ends_at.strftime('%H:%M:%SZ')}"
        )
        lines = [header]
        if target.note:
            lines.append(f"  note: {target.note[:100]}")
        if not target.decisions:
            lines.append("  (期間沒有 agent 決定)")
            return "\n".join(lines)
        counts = {kind.value: 0 for kind in DecisionKind}
        for d in target.decisions:
            counts[d.kind.value] += 1
            icon = _DECISION_ICON[d.kind.value]
            tail = f" — {d.summary}" if d.summary else ""
            lines.append(f"  {icon} {d.ts}  {d.tool}{tail}")
        lines.append("")
        lines.append(
            f"總計: 🤖 {counts['auto_executed']} 自動執行, "
            f"⏸️ {counts['blocked_manual']} 待你回來決定, "
            f"⛔ {counts['blocked_locked']} 不可自動"
        )
        return "\n".join(lines)


# --- Command parsing ---

# Chinese phrases that signal the user is going away.
_ENTER_KEYWORDS_ZH: tuple[str, ...] = ("開會", "外出", "離開", "不在", "出去")
# Standalone English markers — match as whole words so "background" doesn't trigger "back".
_ENTER_KEYWORDS_EN_RE = re.compile(r"\b(?:absence|afk|away)\b", re.IGNORECASE)

# Duration: integer + unit. Chinese (小時 / 分 / 分鐘) and English (h / hour / m / min / minute).
# `\b` doesn't fire between two CJK chars (both are \w), so we use a negative
# lookahead instead — the unit must NOT be followed by an ASCII letter (rejects
# "5 mocha", "5 hammock") but accepts "5 小時開會" and "5 h" / "5 h." cleanly.
_DURATION_RE = re.compile(
    r"(\d+)\s*(小時|分鐘|分|hours?|hrs?|h|minutes?|mins?|m)(?![a-zA-Z])",
    re.IGNORECASE,
)

_EXIT_PHRASES_LOWER: tuple[str, ...] = (
    "我回來了",
    "回來了",
    "結束 absence",
    "結束absence",
    "exit absence",
    "i'm back",
    "im back",
    "back",
)


def parse_enter_command(text: str) -> tuple[timedelta, str] | None:
    """Detect an absence-enter command.

    Returns (duration, note) where note is the original text, or None if the
    message doesn't look like an absence command. Requires BOTH a keyword
    (開會 / 外出 / 不在 / absence / afk / away) AND a duration like "4 小時"
    or "30 min" — either alone is too ambiguous to act on.
    """
    if not text:
        return None
    has_keyword = any(k in text for k in _ENTER_KEYWORDS_ZH) or (
        _ENTER_KEYWORDS_EN_RE.search(text) is not None
    )
    if not has_keyword:
        return None
    dur_match = _DURATION_RE.search(text)
    if dur_match is None:
        return None
    n = int(dur_match.group(1))
    unit = dur_match.group(2).lower()
    if unit.startswith("小時") or unit in {"h", "hr", "hrs", "hour", "hours"}:
        return timedelta(hours=n), text
    return timedelta(minutes=n), text


def parse_exit_command(text: str) -> bool:
    """True if the message is an explicit absence-exit phrase."""
    lowered = (text or "").strip().lower()
    return lowered in _EXIT_PHRASES_LOWER
