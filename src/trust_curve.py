"""Trust Curve — pattern-detected escalation proposal.

Per docs/00 §你的人格 (the 5-stage trust ladder), CLAUDE.md §moat, and
Slide 5: after the user confirms the same pattern N times in a row, the
agent itself proposes "auto-with-undo?" rather than continuing to ask.

This module is the **state machine + proposal phrasing**. Hooking it into
the Tier-2 confirm flow lives in src/agent.py; surfacing the proposal
message lives in src/main.py.

Design:
- A "pattern" is `(tool_name, fingerprint)` where fingerprint is a stable
  string derived from the args that define same-ness. For
  `mcp__gmail__send` that's the `to` recipient; for `mcp__bluesky__post`
  it's just the tool name (every post is a different pattern member of
  the same family). Unknown tools fall back to tool-name only.
- State persists in `trust/curves.json` so the counter survives restarts.
  One file per process; concurrent writes aren't expected (single user).
- Counts are streaks: a deny or timeout resets the counter to 0. Only an
  uninterrupted run of N same-pattern confirms triggers a proposal.
- After a proposal is surfaced once, we mark the pattern as "proposed"
  so we don't nag the user every subsequent confirm. The user can accept
  by reply (out of scope this PR — proposal acceptance lands later).

The 5-stage ladder is a product framing; this module implements the
mechanic that makes one specific step of it possible (the "agent itself
proposes the next level" moment). Auto-execute + 60s undo is out of
scope for this PR.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CURVES_PATH = REPO_ROOT / "trust" / "curves.json"

# Default streak length before the agent proposes escalation. Chosen to match
# the CLAUDE.md / docs/00 phrasing "連續 5 次".
DEFAULT_PROPOSE_THRESHOLD = 5

# Per-tool fingerprint config. Each entry maps tool name → list of arg keys
# whose values (joined) define the pattern. Tools not in this map fall back to
# tool-name only.
_FINGERPRINT_KEYS: dict[str, tuple[str, ...]] = {
    "mcp__gmail__send": ("to",),
    "mcp__bluesky__reply": ("to_uri",),
}


@dataclass
class PatternState:
    """Streak counter for one (tool_name, fingerprint) pattern."""

    tool_name: str
    fingerprint: str
    streak: int = 0  # consecutive confirms; reset on deny/timeout
    total_confirms: int = 0  # all-time confirmed count (informational)
    total_denials: int = 0
    proposed: bool = False  # set True after the agent has proposed escalation


def pattern_key(tool_name: str, tool_input: dict[str, Any] | None) -> tuple[str, str]:
    """Return the (tool_name, fingerprint) pair used as the storage key.

    Fingerprint normalization is intentionally simple: it's the string-cast
    value of the configured discriminator field(s), joined by `|`. For tools
    with no configured discriminator the fingerprint is `*`. Empty / missing
    values become the literal `?` so a `to=""` send doesn't accidentally
    match a `to=` send.
    """
    inp = tool_input or {}
    keys = _FINGERPRINT_KEYS.get(tool_name)
    if not keys:
        return tool_name, "*"
    parts: list[str] = []
    for k in keys:
        v = inp.get(k)
        parts.append(str(v).strip().lower() if isinstance(v, str) and v.strip() else "?")
    return tool_name, "|".join(parts)


class TrustCurve:
    """Streak tracker with JSON persistence.

    Construct with `path=None` for an in-memory instance (tests); construct
    with a path for production persistence. `load_or_empty(path)` is the
    convenience factory.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        propose_threshold: int = DEFAULT_PROPOSE_THRESHOLD,
    ) -> None:
        self._path = path
        self._threshold = max(1, int(propose_threshold))
        self._patterns: dict[tuple[str, str], PatternState] = {}

    @classmethod
    def load_or_empty(
        cls,
        path: Path | None = None,
        *,
        propose_threshold: int = DEFAULT_PROPOSE_THRESHOLD,
    ) -> TrustCurve:
        target = path or DEFAULT_CURVES_PATH
        inst = cls(target, propose_threshold=propose_threshold)
        if target.exists():
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return inst  # corrupt file → start fresh (next write overwrites)
            for entry in raw.get("patterns", []):
                state = PatternState(**entry)
                inst._patterns[(state.tool_name, state.fingerprint)] = state
        return inst

    @property
    def threshold(self) -> int:
        return self._threshold

    def state_for(self, tool_name: str, tool_input: dict[str, Any] | None) -> PatternState:
        key = pattern_key(tool_name, tool_input)
        return self._patterns.get(
            key,
            PatternState(tool_name=key[0], fingerprint=key[1]),
        )

    def record(
        self,
        tool_name: str,
        tool_input: dict[str, Any] | None,
        *,
        approved: bool,
    ) -> PatternState:
        """Update the streak for one Tier-2 outcome. Returns the new state."""
        key = pattern_key(tool_name, tool_input)
        state = self._patterns.setdefault(
            key,
            PatternState(tool_name=key[0], fingerprint=key[1]),
        )
        if approved:
            state.streak += 1
            state.total_confirms += 1
        else:
            state.streak = 0
            state.total_denials += 1
            # A denial after escalation was proposed cancels the proposal so it
            # can re-appear if the user later builds a fresh streak.
            state.proposed = False
        self._save()
        return state

    def should_propose(self, state: PatternState) -> bool:
        """True when the streak just crossed the threshold and we haven't asked yet."""
        return state.streak >= self._threshold and not state.proposed

    def mark_proposed(self, tool_name: str, tool_input: dict[str, Any] | None) -> None:
        key = pattern_key(tool_name, tool_input)
        state = self._patterns.get(key)
        if state is None:
            return
        state.proposed = True
        self._save()

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"patterns": [asdict(s) for s in self._patterns.values()]}
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass(frozen=True)
class EscalationProposal:
    """Rendered message the agent surfaces when a streak crosses threshold."""

    tool_name: str
    fingerprint: str
    streak: int
    message: str = field(default="")


def render_proposal(state: PatternState) -> EscalationProposal:
    """Render the user-facing proposal in the docs/00 voice."""
    target = state.fingerprint if state.fingerprint not in {"*", "?"} else "這個動作"
    msg = (
        f"💡 我注意到你已連續 {state.streak} 次確認「{state.tool_name}」"
        f"對 {target} 的同模式請求。\n\n"
        "要不要升級為「自動執行 + 60 秒可撤」?日後同模式 (同工具 + 同對象) "
        "我會直接做,並給你 60 秒視窗按 ❌ 撤銷。\n\n"
        "回覆 `yes / 好` 接受,或 `no / 不要` 維持目前每次確認。"
    )
    return EscalationProposal(
        tool_name=state.tool_name,
        fingerprint=state.fingerprint,
        streak=state.streak,
        message=msg,
    )
