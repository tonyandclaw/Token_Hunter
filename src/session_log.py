"""L4 session log — `memories/sessions/{ISO-date}.md`.

Per docs/00 §每次 session 開始必做 and CLAUDE.md §2:
- Every session, agent reads (or creates) today's file.
- Append-only timeline; one entry per turn / tool-call summary.
- 30-day rolling retention: anything older than 30 days is deleted by
  `prune_old(now=...)`.

Writes to this directory are explicitly Tier 1 (auto) per docs/00.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

SESSIONS_DIR = Path(__file__).resolve().parent.parent / "memories" / "sessions"
RETENTION_DAYS = 30


def _iso_today(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%d")


def today_path(sessions_dir: Path | None = None, now: datetime | None = None) -> Path:
    base = sessions_dir or SESSIONS_DIR
    return base / f"{_iso_today(now)}.md"


def ensure_today(sessions_dir: Path | None = None, now: datetime | None = None) -> Path:
    """Create today's session file with an H1 header if it doesn't exist."""
    path = today_path(sessions_dir, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        header = f"# Session log — {_iso_today(now)}\n\n"
        path.write_text(header, encoding="utf-8")
    return path


def append_entry(
    text: str,
    *,
    sessions_dir: Path | None = None,
    now: datetime | None = None,
) -> Path:
    """Append a timestamped entry to today's log. Returns the file path."""
    path = ensure_today(sessions_dir, now)
    ts = (now or datetime.now(UTC)).strftime("%H:%M:%SZ")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"- `{ts}` {text}\n")
    return path


_USER_ENTRY_RE = re.compile(r"^- `\d{2}:\d{2}:\d{2}Z`\s+user\[\d+\]:\s+(.*)$")


def read_user_corpus(
    sessions_dir: Path | None = None,
    *,
    days: int = 7,
    now: datetime | None = None,
) -> str:
    """Concatenate the user's own messages from the last `days` of session logs.

    Used as the voice-match corpus in Tier-2 confirm cards. Lines from the
    agent and tool calls are filtered out — we only fingerprint how the user
    writes, not how the agent has been writing on their behalf.
    """
    base = sessions_dir or SESSIONS_DIR
    if not base.exists():
        return ""
    today = (now or datetime.now(UTC)).date()
    cutoff = today - timedelta(days=days)
    pieces: list[str] = []
    for path in sorted(base.glob("*.md")):
        try:
            file_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if file_date < cutoff:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _USER_ENTRY_RE.match(line)
            if m:
                pieces.append(m.group(1))
    return "\n\n".join(pieces)


def prune_old(
    sessions_dir: Path | None = None,
    *,
    now: datetime | None = None,
    retention_days: int = RETENTION_DAYS,
) -> list[Path]:
    """Delete session files older than `retention_days`. Returns list of removed files."""
    base = sessions_dir or SESSIONS_DIR
    if not base.exists():
        return []
    today = (now or datetime.now(UTC)).date()
    cutoff = today - timedelta(days=retention_days)
    removed: list[Path] = []
    for path in base.glob("*.md"):
        try:
            file_date = date.fromisoformat(path.stem)
        except ValueError:
            continue  # filename isn't an ISO date — leave it alone
        if file_date < cutoff:
            path.unlink()
            removed.append(path)
    return removed
