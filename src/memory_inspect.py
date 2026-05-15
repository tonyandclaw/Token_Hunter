"""Read-only renderers for L2 / L3 memory, used by /profile and /learnings.

Per docs/00 §四層記憶, the user should be able to inspect what the agent
remembers about them at any time. The actual memory files
(`memories/user-profile.md`, `memories/learnings.md`) are markdown — easy
to read directly, but not from a phone. These helpers truncate sensibly
for Telegram display.

Called by:
  - src/main.py:on_profile_command  → render_user_profile(path)
  - src/main.py:on_learnings_command → render_learnings(path, limit=)

Pure I/O — never mutates anything. Returns "" or a placeholder string
when the file doesn't exist (a fresh deployment).
"""

from __future__ import annotations

from pathlib import Path

from src.replay import parse_learnings

REPO_ROOT = Path(__file__).resolve().parent.parent
USER_PROFILE_PATH = REPO_ROOT / "memories" / "user-profile.md"
LEARNINGS_PATH = REPO_ROOT / "memories" / "learnings.md"

MAX_PROFILE_CHARS = 2000  # Telegram message limit is 4096; leave headroom
MAX_LEARNINGS_ENTRIES = 5  # most-recent N blocks


def render_user_profile(path: Path | None = None) -> str:
    target = path or USER_PROFILE_PATH
    if not target.exists():
        return "📇 L2 user-profile.md\n\n(尚未建立 — 等你明說的事實累積後會有內容)"
    raw = target.read_text(encoding="utf-8").strip()
    if not raw:
        return "📇 L2 user-profile.md\n\n(檔案存在但是空的)"
    if len(raw) > MAX_PROFILE_CHARS:
        # Show the tail — recent additions are more relevant than first entries
        raw = "… [truncated, see file for full]\n\n" + raw[-MAX_PROFILE_CHARS:]
    return f"📇 L2 user-profile.md\n\n{raw}"


def render_learnings(
    path: Path | None = None,
    *,
    limit: int = MAX_LEARNINGS_ENTRIES,
) -> str:
    """Render the most-recent L3 blocks. Older blocks counted but not shown."""
    target = path or LEARNINGS_PATH
    if not target.exists():
        return "🧠 L3 learnings.md\n\n(尚未建立 — 我會在累積 ≥ 3 次觀察後寫第一條規則)"
    entries = parse_learnings(target)
    if not entries:
        return "🧠 L3 learnings.md\n\n(檔案存在但沒有結構化的規則 block)"

    most_recent = entries[-limit:]
    omitted = len(entries) - len(most_recent)

    lines = [f"🧠 L3 learnings.md ({len(entries)} 條規則,顯示最新 {len(most_recent)}):"]
    if omitted > 0:
        lines.append(f"  …前面省略 {omitted} 條,完整內容看檔案")
    for e in most_recent:
        lines.append("")
        lines.append(f"  [{e.category}] {e.date}  信心={e.confidence}")
        if e.observation:
            lines.append(f"    觀察: {e.observation[:120]}")
        if e.rule:
            lines.append(f"    規則: {e.rule[:120]}")
    return "\n".join(lines)
