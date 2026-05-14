"""L2 + L3 memory writes — append-only, structured.

Per docs/00 §記憶寫入規範 and CLAUDE.md §2:

L2 (`memories/user-profile.md`) holds only things the **user explicitly said**.
Inferences go to L3.

L3 (`memories/learnings.md`) is the agent's inferred rules, in a fixed
four-field block:

    ## [類別] - [ISO 日期]

    **觀察**:...
    **推論規則**:...
    **信心度**:低/中/高(觀察 N 次)
    **反例**:...

Anti-poisoning + anti-overfit (docs/00):
- Confidence rises to "高" only after ≥ HIGH_CONFIDENCE_MIN_OBS prior entries
  share the same category. `append_learning` enforces this by downgrading a
  request for "高" to "低" with a warning string when the threshold isn't met.
- We NEVER overwrite an existing block. Caller corrections always create a
  NEW low-confidence entry, never mutate prior high-confidence ones.

Writes here are Tier-2 actions: the caller (an MCP tool wrapped in
`src/tools/memory_mcp.py`) goes through the agent's confirm flow before
calling these functions, so the file mutation itself is plain and trusted.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parent.parent
USER_PROFILE_PATH = REPO_ROOT / "memories" / "user-profile.md"
LEARNINGS_PATH = REPO_ROOT / "memories" / "learnings.md"

Confidence = Literal["低", "中", "高"]
ALLOWED_CONFIDENCES: tuple[Confidence, ...] = ("低", "中", "高")

# Per docs/00 §記憶寫入規範: "觀察 ≥ 5 次才能升到「高」"
HIGH_CONFIDENCE_MIN_OBS = 5

_CATEGORY_HEADING_RE = re.compile(r"^##\s+\[(?P<category>[^\]]+)\]\s+-\s+", re.MULTILINE)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _today_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%d")


def append_user_profile(
    note: str,
    *,
    path: Path | None = None,
    now: datetime | None = None,
) -> str:
    """Append a single user-stated fact to L2. Returns the block written."""
    target = path or USER_PROFILE_PATH
    _ensure_parent(target)
    block = f"\n- ({_today_iso(now)}) {note.strip()}\n"
    with target.open("a", encoding="utf-8") as fh:
        fh.write(block)
    return block


def count_observations(category: str, *, path: Path | None = None) -> int:
    """Count prior L3 blocks whose category heading equals `category`."""
    target = path or LEARNINGS_PATH
    if not target.exists():
        return 0
    text = target.read_text(encoding="utf-8")
    return sum(1 for m in _CATEGORY_HEADING_RE.finditer(text) if m["category"] == category)


def append_learning(
    category: str,
    observation: str,
    rule: str,
    confidence: Confidence,
    counter_example: str | None = None,
    *,
    path: Path | None = None,
    now: datetime | None = None,
) -> tuple[str, str | None]:
    """Append a four-field L3 block. Returns (block_written, warning_or_None).

    Enforces the docs/00 anti-overfit rule: if `confidence == "高"` but the
    category has < HIGH_CONFIDENCE_MIN_OBS prior entries, we downgrade to
    "低" and emit a warning. The caller (a Tier-2 MCP tool) surfaces the
    warning back to the user.
    """
    if confidence not in ALLOWED_CONFIDENCES:
        raise ValueError(f"confidence must be one of {ALLOWED_CONFIDENCES!r}, got {confidence!r}")

    target = path or LEARNINGS_PATH
    warning: str | None = None
    prior_obs = count_observations(category, path=target)

    actual_confidence: Confidence = confidence
    # Existing block is prior_obs; this new block makes prior_obs + 1 total
    if confidence == "高" and prior_obs + 1 < HIGH_CONFIDENCE_MIN_OBS:
        actual_confidence = "低"
        warning = (
            f"信心度從「高」降級為「低」:類別 {category!r} 累計觀察數 "
            f"{prior_obs + 1} 次,未達到「高」門檻 {HIGH_CONFIDENCE_MIN_OBS} 次。"
        )

    _ensure_parent(target)
    confidence_line = f"**信心度**:{actual_confidence}(觀察 {prior_obs + 1} 次)"

    block_lines = [
        f"## [{category}] - {_today_iso(now)}",
        "",
        f"**觀察**:{observation.strip()}",
        "",
        f"**推論規則**:{rule.strip()}",
        "",
        confidence_line,
        "",
        f"**反例**:{counter_example.strip() if counter_example else '(無)'}",
        "",
    ]
    block = "\n".join(block_lines)

    # Sandwich blank lines around the block so concatenation stays well-formed
    with target.open("a", encoding="utf-8") as fh:
        if target.stat().st_size > 0:
            fh.write("\n")
        fh.write(block)
    return block, warning


def list_categories(*, path: Path | None = None) -> list[tuple[str, int]]:
    """Return [(category, count), ...] sorted by descending count, for diagnostics."""
    target = path or LEARNINGS_PATH
    if not target.exists():
        return []
    text = target.read_text(encoding="utf-8")
    counts: dict[str, int] = {}
    for m in _CATEGORY_HEADING_RE.finditer(text):
        counts[m["category"]] = counts.get(m["category"], 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def today() -> date:
    """Exported for tests that want a consistent today value."""
    return datetime.now(UTC).date()
