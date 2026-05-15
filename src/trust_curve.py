"""Trust Escalation Curve — quantified, file-backed trust state per (tool, key).

Per docs/02 Scene 1–2 and README §Trust Escalation Curve:

After ESCALATION_THRESHOLD consecutive identical-pattern confirms, the agent
becomes "eligible to propose escalation". The user then picks one of:

  🤖 Auto (15s undo)  → AUTO_AUDITED   (curve.escalate)
  🛎️ 繼續每次都問     → stays MANUAL   (curve.defer)
  ❌ 永遠別自動       → ALWAYS_ASK     (curve.lock_always_ask)

A pattern key is extracted from tool args by `extract_key`. If extract_key
returns None (no stable narrower key — e.g. a free-form Bluesky post), the
event is still recorded under sentinel WILDCARD_KEY for dashboard counting,
but eligibility never fires for it (too coarse a bucket to auto-escalate).

This module is pure logic + JSON persistence. The Tier-2 confirm pipeline
(`src/tier2_confirm.py`) calls `record()` when a user resolves a confirm;
the propose-escalation UX (still to be wired) consumes `is_eligible()`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CURVES_PATH = REPO_ROOT / "trust" / "curves.json"

ESCALATION_THRESHOLD = 5  # per docs/02: "Trust evidence: 5 / 5 ✓"
WILDCARD_KEY = "*"


class Level(IntEnum):
    """Trust levels per docs/02 visualisation. Higher = more agent autonomy."""

    ALWAYS_ASK = 0  # user picked ❌ — locked off, never escalates again
    MANUAL = 1  # default — Tier 2 confirm every time
    AUTO_AUDITED = 2  # auto with 15s undo window + Telegram notification
    AUTO_SILENT = 3  # auto, audit log only, no Telegram notify
    FULL = 4  # delegated, still logged for audit but no user surfacing


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class PatternState:
    tool: str
    key: str
    level: Level = Level.MANUAL
    consecutive_confirms: int = 0
    total_confirms: int = 0
    total_rejects: int = 0
    last_updated: str = field(default_factory=_now_iso)

    @property
    def is_locked(self) -> bool:
        """ALWAYS_ASK is sticky — user explicitly opted out of escalation."""
        return self.level is Level.ALWAYS_ASK

    @property
    def is_eligible_for_escalation(self) -> bool:
        """True iff at MANUAL with ≥ ESCALATION_THRESHOLD consecutive confirms."""
        if self.key == WILDCARD_KEY:
            return False  # too coarse to auto-escalate
        if self.level is not Level.MANUAL:
            return False
        return self.consecutive_confirms >= ESCALATION_THRESHOLD

    def to_dict(self) -> dict:
        d = asdict(self)
        d["level"] = int(self.level)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> PatternState:
        return cls(
            tool=d["tool"],
            key=d["key"],
            level=Level(int(d.get("level", Level.MANUAL))),
            consecutive_confirms=int(d.get("consecutive_confirms", 0)),
            total_confirms=int(d.get("total_confirms", 0)),
            total_rejects=int(d.get("total_rejects", 0)),
            last_updated=d.get("last_updated") or _now_iso(),
        )


def extract_key(tool: str, args: dict | None) -> str | None:
    """Stable pattern key for trust grouping. None → use WILDCARD_KEY, never escalate.

    Choices reflect docs/02 semantics: ACME 詢問交期 escalates per-recipient,
    not per-tool. Free-form output channels (Bluesky posts, free-text profile
    writes) intentionally return None so escalation eligibility doesn't fire
    on a too-coarse bucket.
    """
    args = args or {}
    if tool.startswith("mcp__gmail__send") or tool.startswith("mcp__gmail__reply"):
        to = str(args.get("to", "")).strip().lower()
        return f"to={to}" if to else None
    if tool.startswith("mcp__memory__write_learning"):
        category = str(args.get("category", "")).strip()
        return f"category={category}" if category else None
    # Bluesky posts, memory user-profile writes, and unknown tools fall through:
    # too varied to escalate as a single bucket.
    return None


class TrustCurve:
    """Per-process state for trust curves. Backed by trust/curves.json."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULT_CURVES_PATH
        self._states: dict[tuple[str, str], PatternState] = {}

    @staticmethod
    def _pattern_id(state: PatternState) -> str:
        return f"{state.tool}|{state.key}"

    @staticmethod
    def _parse_pattern_id(pid: str) -> tuple[str, str]:
        tool, _, key = pid.partition("|")
        return tool, key

    def load(self) -> None:
        if not self._path.exists():
            return
        raw = json.loads(self._path.read_text(encoding="utf-8") or "{}")
        for pid, payload in raw.items():
            tool, key = self._parse_pattern_id(pid)
            payload.setdefault("tool", tool)
            payload.setdefault("key", key)
            state = PatternState.from_dict(payload)
            self._states[(state.tool, state.key)] = state

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {self._pattern_id(s): s.to_dict() for s in self._states.values()}
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _state_for(self, tool: str, key: str | None) -> PatternState:
        k = key or WILDCARD_KEY
        existing = self._states.get((tool, k))
        if existing is not None:
            return existing
        fresh = PatternState(tool=tool, key=k)
        self._states[(tool, k)] = fresh
        return fresh

    def status(self, tool: str, args: dict | None = None) -> PatternState:
        """Read-only status for a tool call. Doesn't mutate state."""
        return self._state_for(tool, extract_key(tool, args))

    def record(
        self,
        tool: str,
        args: dict | None,
        *,
        approved: bool,
        persist: bool = True,
    ) -> PatternState:
        """Record one confirm decision. Approved → +1 streak; rejected → reset streak."""
        state = self._state_for(tool, extract_key(tool, args))
        if state.is_locked:
            # ALWAYS_ASK still tallies counts for the dashboard but never escalates
            if approved:
                state.total_confirms += 1
            else:
                state.total_rejects += 1
        else:
            if approved:
                state.total_confirms += 1
                state.consecutive_confirms += 1
            else:
                state.total_rejects += 1
                state.consecutive_confirms = 0
        state.last_updated = _now_iso()
        if persist:
            self.save()
        return state

    def lock_always_ask(self, tool: str, args: dict | None = None) -> PatternState:
        """User picked ❌ 永遠別自動. Permanently disable escalation for this pattern."""
        state = self._state_for(tool, extract_key(tool, args))
        state.level = Level.ALWAYS_ASK
        state.consecutive_confirms = 0
        state.last_updated = _now_iso()
        self.save()
        return state

    def defer(self, tool: str, args: dict | None = None) -> PatternState:
        """User picked 🛎️ 繼續每次都問. Stay MANUAL; reset streak so we don't re-propose now."""
        state = self._state_for(tool, extract_key(tool, args))
        if not state.is_locked:
            state.consecutive_confirms = 0
        state.last_updated = _now_iso()
        self.save()
        return state

    def escalate(
        self,
        tool: str,
        args: dict | None = None,
        *,
        new_level: Level = Level.AUTO_AUDITED,
    ) -> PatternState:
        """User picked 🤖 Auto. Promote MANUAL → new_level. Refuses to bypass ALWAYS_ASK."""
        state = self._state_for(tool, extract_key(tool, args))
        if state.is_locked:
            raise ValueError(
                f"pattern {state.tool}|{state.key} is ALWAYS_ASK — must be unlocked first"
            )
        if new_level <= state.level:
            raise ValueError(
                f"new_level {new_level.name} is not higher than current {state.level.name}"
            )
        state.level = new_level
        state.consecutive_confirms = 0  # restart counting at the new level
        state.last_updated = _now_iso()
        self.save()
        return state

    def list_patterns(self) -> list[PatternState]:
        """All known patterns, sorted by most-recently-updated first."""
        return sorted(
            self._states.values(),
            key=lambda s: s.last_updated,
            reverse=True,
        )

    def summary(self) -> str:
        """Human-readable dashboard — Telegram-renderable.

        At MANUAL level each pattern shows a small unicode bar of streak
        progress toward the escalation threshold. Above MANUAL, the bar
        is replaced by the trust level (since the streak no longer means
        "progress toward escalation").
        """
        patterns = self.list_patterns()
        if not patterns:
            return "(尚無 Trust 紀錄)"
        lines = ["📊 Trust Dashboard"]
        for s in patterns:
            ratio = f"{s.total_confirms}✅ / {s.total_rejects}❌"
            if s.level is Level.MANUAL and not s.is_locked:
                bar = _progress_bar(s.consecutive_confirms, ESCALATION_THRESHOLD)
                detail = f"{bar} streak {s.consecutive_confirms}/{ESCALATION_THRESHOLD}"
            else:
                detail = s.level.name
            lines.append(f"  {s.tool} [{s.key}]")
            lines.append(f"    {ratio} · {detail}")
        return "\n".join(lines)


def _progress_bar(filled: int, total: int, *, width: int = 5) -> str:
    """Unicode mini progress bar. Cap fill at total so over-runs don't break the bar."""
    if total <= 0:
        return "─" * width
    filled = max(0, min(filled, total))
    full = int(round(filled / total * width))
    return "●" * full + "○" * (width - full)
