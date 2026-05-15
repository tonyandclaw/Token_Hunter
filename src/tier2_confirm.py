"""Tier-2 inline-confirm coordination between the Agent SDK and Telegram.

Per docs/00 §Tier 2 and docs/01 §PermissionGate:

  Agent makes a Tier-2 tool call
     │
     ▼
  PreToolUse hook returns permissionDecision="ask"
     │
     ▼
  SDK calls our can_use_tool(tool_name, tool_input, ctx)
     │
     ▼  agent task awaits a Future
  ConfirmRegistry.submit() creates the Future, returns a confirm_id
     │
     ▼  Telegram message sent with inline buttons keyed by confirm_id
  User taps ✅ or ❌
     │
     ▼  CallbackQuery handler in main.py calls registry.resolve(id, bool)
  Future resolves → can_use_tool returns Allow / Deny
     │
     ▼
  5-minute timeout (DEFAULT_CONFIRM_TIMEOUT) auto-rejects with Deny

This module is the **pure registry + render helpers**, plus the rendered
prompt. It doesn't depend on python-telegram-bot — Telegram wiring lives in
src/main.py so tests stay offline.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.recipient_tracker import KnownRecipients, is_gmail_send_tool
from src.trust_curve import PatternState, TrustCurve
from src.voice_scorer import MAX_VOICE_PCT
from src.voice_scorer import score as voice_score

DEFAULT_CONFIRM_TIMEOUT = 300  # 5 minutes, per docs/01 §PermissionGate

OnSubmit = Callable[[str, str], Awaitable[None]]
# Fired when an approved confirm pushes a pattern to is_eligible_for_escalation.
# Args: (tool_name, tool_input, post_record_state).
OnEligibleForEscalation = Callable[[str, dict[str, Any], PatternState], Awaitable[None]]

CONFIRM_PROMPT = "我準備執行:{tool_name}\n\n影響:{impact}\n\n草稿:\n\n{draft}\n\n確認? [Yes / No]"


@dataclass
class PendingConfirm:
    confirm_id: str
    tool_name: str
    tool_input: dict[str, Any]
    created_at: datetime
    future: asyncio.Future[bool] = field(repr=False)


def _extract_draft(tool_input: dict[str, Any]) -> str | None:
    for key in ("body", "text", "content", "value"):
        v = tool_input.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def render_prompt(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    voice_corpus: str = "",
    known_recipients: KnownRecipients | None = None,
) -> str:
    """Render the user-facing Tier-2 confirm message.

    The format is fixed (docs/00 §Tier 2): 動作 → 影響 → 草稿 → 確認?
    Best-effort field extraction; unknown tools still get a sensible prompt.

    When `voice_corpus` is non-empty AND the tool args contain a draft
    string, a `📈 Voice match: NN%` line is appended below the prompt
    (docs/02 Scene 1). Empty corpus skips the line silently — better than
    showing 0% which would scare the user every time.
    """
    impact_parts: list[str] = []
    if "to" in tool_input:
        impact_parts.append(f"收件人 {tool_input['to']}")
    if "channel" in tool_input:
        impact_parts.append(f"頻道 {tool_input['channel']}")
    if "count" in tool_input:
        impact_parts.append(f"{tool_input['count']} 個項目")
    if not impact_parts:
        impact_parts.append("(僅 agent 內部,本次行動有外部寫入)")

    raw_draft = _extract_draft(tool_input)
    draft = raw_draft if raw_draft is not None else "(無草稿內容)"
    if len(draft) > 600:
        draft = draft[:600] + "… [truncated]"

    prompt = CONFIRM_PROMPT.format(
        tool_name=tool_name,
        impact=", ".join(impact_parts),
        draft=draft,
    )

    if voice_corpus and raw_draft:
        vs = voice_score(raw_draft, voice_corpus)
        prompt += (
            f"\n\n📈 Voice match: {vs.overall_pct}% "
            f"(句長 {vs.length_pct}% · 詞彙 {vs.vocab_pct}% · "
            f"結構 {vs.structure_pct}% · 上限 {MAX_VOICE_PCT}%)"
        )

    # First-contact friction per docs/03 §不做: "Tier 2 永遠擋給不認識的人寫信".
    # When the recipient has never been approved before, prepend a red-flag
    # banner so the user has an extra prompt to think before saying ✅.
    if known_recipients is not None and is_gmail_send_tool(tool_name):
        to_addr = str(tool_input.get("to", "")).strip()
        if to_addr and not known_recipients.is_known(to_addr):
            prompt = f"⚠️ 第一次寄信給 {to_addr}(first-contact)\n\n" + prompt

    return prompt


class ConfirmRegistry:
    """In-process registry of pending Tier-2 confirms keyed by confirm_id."""

    def __init__(self) -> None:
        self._pending: dict[str, PendingConfirm] = {}

    def submit(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> tuple[str, asyncio.Future[bool]]:
        """Register a new pending confirm. Returns (confirm_id, future)."""
        confirm_id = uuid.uuid4().hex[:8]
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[confirm_id] = PendingConfirm(
            confirm_id=confirm_id,
            tool_name=tool_name,
            tool_input=tool_input,
            created_at=datetime.now(UTC),
            future=future,
        )
        return confirm_id, future

    def resolve(self, confirm_id: str, *, approved: bool) -> bool:
        """Set the future's result. Returns True if a pending confirm matched."""
        pending = self._pending.pop(confirm_id, None)
        if pending is None:
            return False
        if not pending.future.done():
            pending.future.set_result(approved)
        return True

    def discard(self, confirm_id: str) -> None:
        self._pending.pop(confirm_id, None)

    def is_pending(self, confirm_id: str) -> bool:
        return confirm_id in self._pending

    def pending_count(self) -> int:
        return len(self._pending)

    def get(self, confirm_id: str) -> PendingConfirm | None:
        return self._pending.get(confirm_id)


async def await_decision(
    registry: ConfirmRegistry,
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    timeout_seconds: float = DEFAULT_CONFIRM_TIMEOUT,
    on_submit: OnSubmit | None = None,
    trust_curve: TrustCurve | None = None,
    on_eligible: OnEligibleForEscalation | None = None,
    voice_corpus: str = "",
    known_recipients: KnownRecipients | None = None,
) -> tuple[str, bool]:
    """Submit a pending confirm and await the user's decision.

    `on_submit(confirm_id, prompt_text)` is awaited synchronously inside this
    function so the caller can dispatch the Telegram message AFTER the
    registry entry exists. Returns (confirm_id, approved). On timeout returns
    (confirm_id, False) and removes the pending entry.

    `trust_curve` (optional): when present, every resolved decision is recorded
    so the Trust Dashboard reflects the user's confirm/reject history. Timeouts
    are recorded as rejections (per docs/02 — silence = no consent).

    `on_eligible` (optional): invoked after recording when an approved confirm
    pushes the pattern to `is_eligible_for_escalation`. Used by main.py to
    send the propose-escalation Telegram message.
    """
    confirm_id, future = registry.submit(tool_name, tool_input)
    if on_submit is not None:
        await on_submit(
            confirm_id,
            render_prompt(
                tool_name,
                tool_input,
                voice_corpus=voice_corpus,
                known_recipients=known_recipients,
            ),
        )
    try:
        approved = await asyncio.wait_for(future, timeout=timeout_seconds)
    except TimeoutError:
        registry.discard(confirm_id)
        approved = False
    if trust_curve is not None:
        state = trust_curve.record(tool_name, tool_input, approved=approved)
        if approved and state.is_eligible_for_escalation and on_eligible is not None:
            await on_eligible(tool_name, dict(tool_input), state)
    # Mark recipient as known so subsequent sends to the same address don't
    # re-trigger the first-contact banner. Only on approval — a rejected
    # send doesn't make the recipient trusted.
    if approved and known_recipients is not None and is_gmail_send_tool(tool_name):
        to_addr = str(tool_input.get("to", "")).strip()
        if to_addr:
            known_recipients.mark_seen(to_addr)
    return confirm_id, approved
