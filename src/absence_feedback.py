"""Per-decision feedback buttons for Absence Mode replay.

After absence ends, the structured replay log lists every auto-executed
decision. Each one is followed by a tiny message:

  🤖 已自動執行: <label>
  [✅ 沒問題] [🚫 不該自動]

The two outcomes:
  - ✅ no-op (user acknowledges; we still log it for visibility)
  - 🚫 lock the pattern back to ALWAYS_ASK so it never auto-fires again

This module is the pure registry + apply_feedback. Telegram wiring is in
main.py. Same registry pattern as the other inline-button flows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.trust_curve import TrustCurve

CALLBACK_PREFIX = "afb"  # "absence feedback"


class FeedbackAction(Enum):
    OK = "ok"  # acknowledge; no state change
    LOCK = "lock"  # 🚫 不該自動 — lock pattern back to ALWAYS_ASK


@dataclass(frozen=True)
class PendingFeedback:
    fid: str
    tool: str
    args: dict[str, Any]
    label: str
    created_at: datetime


OK_REPLY = "✅ 收到回饋,trust curve 不變動。"
LOCK_REPLY = "🚫 已將此 pattern 改為 ALWAYS_ASK,未來不會自動執行。"
STALE_REPLY = "_(回饋已過期)_"


def encode_callback(fid: str, action: FeedbackAction) -> str:
    return f"{CALLBACK_PREFIX}:{fid}:{action.value}"


def decode_callback(data: str) -> tuple[str, FeedbackAction] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        return None
    try:
        action = FeedbackAction(parts[2])
    except ValueError:
        return None
    return parts[1], action


class FeedbackRegistry:
    """Pending per-decision feedbacks keyed by short id. Pops on resolve."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingFeedback] = {}

    def submit(self, tool: str, args: dict[str, Any], label: str) -> PendingFeedback:
        fid = uuid.uuid4().hex[:8]
        pf = PendingFeedback(
            fid=fid,
            tool=tool,
            args=dict(args),
            label=label,
            created_at=datetime.now(UTC),
        )
        self._pending[fid] = pf
        return pf

    def pop(self, fid: str) -> PendingFeedback | None:
        return self._pending.pop(fid, None)

    def is_pending(self, fid: str) -> bool:
        return fid in self._pending

    def pending_count(self) -> int:
        return len(self._pending)


def apply_feedback(
    curve: TrustCurve,
    pending: PendingFeedback,
    action: FeedbackAction,
) -> str:
    """Mutate the curve per the user's button choice. Returns reply text."""
    if action is FeedbackAction.OK:
        return OK_REPLY
    if action is FeedbackAction.LOCK:
        curve.lock_always_ask(pending.tool, pending.args)
        return LOCK_REPLY
    raise ValueError(f"unknown action {action!r}")
