"""Trust-curve propose-escalation flow.

Per docs/02 Scene 2 and README §Trust Escalation Curve, when a pattern hits
ESCALATION_THRESHOLD consecutive confirms while at MANUAL, the agent surfaces:

  ⚡ 你連續 5 次都直接 ✅ 沒改內容。
     要我以後遇到 "<pattern>" 自動處理嗎?

  [🤖 Auto (15s undo)]
  [🛎️ 繼續每次都問]
  [❌ 永遠別自動]

This module is the pure registry + render helpers + decision applier. It
doesn't depend on python-telegram-bot — Telegram wiring lives in src/main.py
so tests stay offline.

Hook order:
  1. `tier2_confirm.await_decision` resolves a confirm to approved=True.
  2. It calls `trust_curve.record(...)` which returns the new PatternState.
  3. If `state.is_eligible_for_escalation`, await_decision invokes the
     `on_eligible(tool, args, state)` callback.
  4. main.py's on_eligible callback calls `EscalationRegistry.submit(...)`,
     gets a short id, and sends a Telegram message with three inline buttons
     keyed by that id.
  5. User taps a button → CallbackQueryHandler decodes `esc:<id>:<action>`
     → `apply_action(curve, registry, id, action)` mutates the curve and
     returns the user-facing result string.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.trust_curve import Level, PatternState, TrustCurve

CALLBACK_PREFIX = "esc"

PROPOSAL_HEADER = "⚡ 你連續 {streak} 次都直接 ✅ 沒改內容。"
PROPOSAL_QUESTION = '要我以後遇到 "{label}" 自動處理嗎?'

ESCALATED_TEMPLATE = (
    "✅ Trust upgraded.\n\n"
    "📈 Trust Curve:\n"
    "   MANUAL ●━●━●━●━● ▶ {new_level}\n\n"
    "下次相同 pattern,我會自動處理,並透過 Telegram 通知結果。"
)
DEFERRED_TEMPLATE = "🛎️ 繼續每次都問。streak 已重置。"
LOCKED_TEMPLATE = "❌ 已加入 always-ask 清單;此 pattern 永不升級。"


class Action(Enum):
    """Encodes the three button choices. Stable wire format — used in callback_data."""

    ESCALATE = "yes"
    DEFER = "later"
    LOCK = "never"

    @classmethod
    def parse(cls, raw: str) -> Action | None:
        try:
            return cls(raw)
        except ValueError:
            return None


@dataclass
class PendingEscalation:
    eid: str
    tool: str
    args: dict[str, Any]
    streak: int
    created_at: datetime


EscalationProposer = Callable[[str, "PendingEscalation"], Awaitable[None]]


def pattern_label(tool: str, args: dict[str, Any]) -> str:
    """Human-readable label for the proposal message — derived from tool args."""
    args = args or {}
    if tool.startswith("mcp__gmail__send") or tool.startswith("mcp__gmail__reply"):
        to = str(args.get("to", "")).strip()
        return f"寫信給 {to}" if to else "寄信"
    if tool.startswith("mcp__memory__write_learning"):
        cat = str(args.get("category", "")).strip()
        return f"記下「{cat}」類規則" if cat else "寫入學習記憶"
    if tool.startswith("mcp__bluesky__"):
        return "Bluesky 發文"
    return tool


def render_proposal(state: PatternState, tool: str, args: dict[str, Any]) -> str:
    """The full propose-escalation message body (without the buttons)."""
    return "\n\n".join(
        (
            PROPOSAL_HEADER.format(streak=state.consecutive_confirms),
            PROPOSAL_QUESTION.format(label=pattern_label(tool, args)),
        )
    )


class EscalationRegistry:
    """In-process registry of pending escalation proposals keyed by short id."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingEscalation] = {}

    def submit(
        self,
        tool: str,
        args: dict[str, Any],
        *,
        streak: int,
    ) -> PendingEscalation:
        eid = uuid.uuid4().hex[:8]
        pending = PendingEscalation(
            eid=eid,
            tool=tool,
            args=dict(args),
            streak=streak,
            created_at=datetime.now(UTC),
        )
        self._pending[eid] = pending
        return pending

    def pop(self, eid: str) -> PendingEscalation | None:
        return self._pending.pop(eid, None)

    def is_pending(self, eid: str) -> bool:
        return eid in self._pending

    def pending_count(self) -> int:
        return len(self._pending)


def encode_callback(eid: str, action: Action) -> str:
    return f"{CALLBACK_PREFIX}:{eid}:{action.value}"


def decode_callback(data: str) -> tuple[str, Action] | None:
    """Return (eid, action) for a valid 'esc:<id>:<action>' callback; None otherwise."""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        return None
    action = Action.parse(parts[2])
    if action is None:
        return None
    return parts[1], action


def apply_action(
    curve: TrustCurve,
    pending: PendingEscalation,
    action: Action,
) -> str:
    """Mutate the curve according to the user's choice and return the reply text.

    Raises ValueError only on internal bugs (e.g. trying to escalate a locked
    pattern). The caller — which got `pending` from the registry — is expected
    to surface that as an error message to the user.
    """
    if action is Action.ESCALATE:
        new_state = curve.escalate(pending.tool, pending.args, new_level=Level.AUTO_AUDITED)
        return ESCALATED_TEMPLATE.format(new_level=new_state.level.name)
    if action is Action.DEFER:
        curve.defer(pending.tool, pending.args)
        return DEFERRED_TEMPLATE
    if action is Action.LOCK:
        curve.lock_always_ask(pending.tool, pending.args)
        return LOCKED_TEMPLATE
    raise ValueError(f"unknown action {action!r}")
