"""[🔍 Why this?] button — Telegram registry + decode for Memory Replay.

Per docs/02 Scene 3 and README mechanic #2:

  ✅ Auto-handled: ACME 交期回覆已發送
     [↶ Undo (14s)] [🔍 Why this?]

When the user taps `[🔍 Why this?]`, we build a full ReplayReport for the
decision: triggered L2/L3 memories, past similar cases, voice match,
forensic, counterfactual. The engine is `src/replay.py`; this module is
the Telegram glue (registry of pending decisions + callback decoder).

The button is attached at decision time (e.g. on the undo-window message,
before the tool actually fires) so we don't have an audit event yet —
hence we use `replay.build_report_for_call(tool, args, tier=...)` which
synthesizes a target dict without needing a JSONL row.

Same registry pattern as ConfirmRegistry / EscalationRegistry / UndoRegistry,
but `get()` does NOT pop — the user can press Why multiple times to re-read
the same report (it's read-only, no state mutation).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

CALLBACK_PREFIX = "why"


@dataclass(frozen=True)
class WhyContext:
    """Snapshot of a decision at the moment we offered the Why button."""

    wid: str
    tool: str
    args: dict[str, Any]
    tier: int
    captured_at: datetime


def encode_callback(wid: str) -> str:
    """Callback data shape: 'why:<id>'."""
    return f"{CALLBACK_PREFIX}:{wid}"


def decode_callback(data: str) -> str | None:
    parts = data.split(":")
    if len(parts) != 2 or parts[0] != CALLBACK_PREFIX:
        return None
    return parts[1]


class WhyRegistry:
    """In-process registry of pending Why contexts keyed by short id.

    Items are bounded by `max_items` (default 200) to keep memory usage
    sane during long-running webhooks. Eviction is FIFO by insertion order.
    Tapping Why on an evicted message just shows '(已過期)'.
    """

    def __init__(self, *, max_items: int = 200) -> None:
        self._items: dict[str, WhyContext] = {}
        self._max_items = max_items

    def submit(self, tool: str, args: dict[str, Any], *, tier: int = 2) -> WhyContext:
        wid = uuid.uuid4().hex[:8]
        ctx = WhyContext(
            wid=wid,
            tool=tool,
            args=dict(args),
            tier=tier,
            captured_at=datetime.now(UTC),
        )
        self._items[wid] = ctx
        # FIFO eviction once we're past the cap
        while len(self._items) > self._max_items:
            oldest = next(iter(self._items))
            del self._items[oldest]
        return ctx

    def get(self, wid: str) -> WhyContext | None:
        return self._items.get(wid)

    def has(self, wid: str) -> bool:
        return wid in self._items

    def pending_count(self) -> int:
        return len(self._items)
