"""15-second undo window for AUTO_AUDITED Tier-2 calls.

Per docs/02 Scene 2 / Scene 3 and README §Trust Escalation Curve:

When a pattern has been escalated to `Level.AUTO_AUDITED`, the agent runs
the tool WITHOUT asking — but the user gets a Telegram notification with a
single `[↶ Undo (Ns)]` button. The tool execution itself is delayed `N`
seconds; tapping the button before the timer fires cancels the call and
returns Deny to the SDK.

Design choices:
- Delay-then-execute is implemented inside `can_use_tool`. We return
  Allow only AFTER the timer expires; tapping the button cancels the
  pending future → return Deny. This works for any tool (gmail, bluesky,
  memory) because we never have to "unsend" anything — the tool simply
  hasn't run yet at the moment the user clicks Undo.
- Default window: 15s (the demo shows 14s remaining; we burn 1s on
  Telegram round-trip). Configurable via `DEFAULT_UNDO_SECONDS`.
- Same registry pattern as ConfirmRegistry / EscalationRegistry — short
  id keyed callbacks, pop-on-resolve.

This module is pure logic + render helpers. Telegram wiring is in main.py.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DEFAULT_UNDO_SECONDS = 15
CALLBACK_PREFIX = "undo"

UNDO_PROMPT = (
    "🤖 預備自動執行(已升級為 AUTO_AUDITED):\n"
    "  {label}\n\n"
    "[↶ Undo ({seconds}s)] 在倒數結束前按下可取消。"
)


# Callable signature: (undo_id, tool, args, prompt_text, seconds) → None.
# main.py uses this to dispatch the Telegram message right after we register
# the pending undo. tool/args are passed through so main.py can also register
# a WhyRegistry snapshot and attach the [🔍 Why this?] button.
UndoNotifier = Callable[[str, str, dict[str, Any], str, int], Awaitable[None]]


@dataclass
class PendingUndo:
    uid: str
    tool: str
    args: dict[str, Any]
    created_at: datetime
    future: asyncio.Future[bool]  # True = user pressed Undo; False/Timeout = proceed


def encode_callback(uid: str) -> str:
    """Callback data shape: 'undo:<id>'. Single-button, no action enum needed."""
    return f"{CALLBACK_PREFIX}:{uid}"


def decode_callback(data: str) -> str | None:
    parts = data.split(":")
    if len(parts) != 2 or parts[0] != CALLBACK_PREFIX:
        return None
    return parts[1]


def _label_for(tool: str, args: dict[str, Any]) -> str:
    """Reused-shape short label so the Undo prompt shows what's about to fire."""
    args = args or {}
    if tool.startswith("mcp__gmail__send") or tool.startswith("mcp__gmail__reply"):
        to = str(args.get("to", "")).strip() or "?"
        subj = str(args.get("subject", "")).strip()
        return f"寄信給 {to}" + (f" / {subj[:40]}" if subj else "")
    if tool.startswith("mcp__bluesky__"):
        body = str(args.get("text", "")).strip()
        return f"Bluesky: {body[:60]}{'…' if len(body) > 60 else ''}"
    if tool.startswith("mcp__memory__"):
        return tool.split("__")[-1]
    return tool


def render_prompt(tool: str, args: dict[str, Any], *, seconds: int) -> str:
    return UNDO_PROMPT.format(label=_label_for(tool, args), seconds=seconds)


class UndoRegistry:
    """In-process registry of pending undo windows keyed by short id."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingUndo] = {}

    def submit(self, tool: str, args: dict[str, Any]) -> tuple[str, asyncio.Future[bool]]:
        uid = uuid.uuid4().hex[:8]
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[uid] = PendingUndo(
            uid=uid,
            tool=tool,
            args=dict(args),
            created_at=datetime.now(UTC),
            future=future,
        )
        return uid, future

    def cancel(self, uid: str) -> bool:
        """User pressed Undo. Returns True if a matching pending entry was found."""
        pending = self._pending.pop(uid, None)
        if pending is None:
            return False
        if not pending.future.done():
            pending.future.set_result(True)
        return True

    def discard(self, uid: str) -> None:
        self._pending.pop(uid, None)

    def is_pending(self, uid: str) -> bool:
        return uid in self._pending

    def pending_count(self) -> int:
        return len(self._pending)


async def await_undo(
    registry: UndoRegistry,
    tool: str,
    args: dict[str, Any],
    *,
    seconds: int = DEFAULT_UNDO_SECONDS,
    notify: UndoNotifier | None = None,
) -> tuple[str, bool]:
    """Open a single undo window. Returns (uid, cancelled).

    - cancelled == True   → user pressed Undo within the window → caller returns Deny
    - cancelled == False  → timer expired with no cancel        → caller returns Allow
    """
    uid, future = registry.submit(tool, args)
    if notify is not None:
        await notify(uid, tool, args, render_prompt(tool, args, seconds=seconds), seconds)
    try:
        cancelled = await asyncio.wait_for(future, timeout=seconds)
        return uid, cancelled
    except TimeoutError:
        registry.discard(uid)
        return uid, False
