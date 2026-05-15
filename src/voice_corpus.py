"""Build the user's writing corpus for voice_scorer comparisons.

Per docs/02 Scene 1 and README mechanic #3 ("Voice Match 量化"), the agent
shows `📈 Voice match: NN%` on every draft. To compute that, voice_scorer
needs a corpus of the user's prior writing. We don't have direct access to
the user's sent-mail history, so we approximate from what we DO have:

  L2 (`memories/user-profile.md`) — explicit user statements (full text)
  L4 (`memories/sessions/{date}.md`) — only the lines starting with
    `user[<id>]: ` (those are messages typed by the user this session)

We read up to `DEFAULT_RECENT_DAYS` of recent L4 files. Total corpus size
is capped at `MAX_CORPUS_CHARS` so a long-running deployment doesn't
balloon memory; oldest content is trimmed first.

This is intentionally simple — it's a fingerprint, not training data.
"""

from __future__ import annotations

import contextlib
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
USER_PROFILE_PATH = REPO_ROOT / "memories" / "user-profile.md"
SESSIONS_DIR = REPO_ROOT / "memories" / "sessions"

DEFAULT_RECENT_DAYS = 7
MAX_CORPUS_CHARS = 20_000

# Matches "- `HH:MM:SSZ` user[12345]: <text>" lines in L4 logs.
_USER_LINE_RE = re.compile(r"^-\s+`[^`]+`\s+user\[\d+\]:\s*(?P<text>.*)$", re.MULTILINE)


def _extract_user_lines(text: str) -> list[str]:
    return [m.group("text") for m in _USER_LINE_RE.finditer(text)]


def _read_session_user_text(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return "\n".join(_extract_user_lines(raw))


def _iter_recent_session_files(
    sessions_dir: Path,
    *,
    today: date,
    days: int,
) -> list[Path]:
    """Return session files within the last `days` days, oldest first."""
    if not sessions_dir.exists():
        return []
    cutoff = today - timedelta(days=days)
    eligible: list[Path] = []
    for path in sorted(sessions_dir.glob("*.md")):
        try:
            d = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if d >= cutoff:
            eligible.append(path)
    return eligible


def load_user_corpus(
    *,
    profile_path: Path | None = None,
    sessions_dir: Path | None = None,
    days: int = DEFAULT_RECENT_DAYS,
    max_chars: int = MAX_CORPUS_CHARS,
    now: datetime | None = None,
) -> str:
    """Concatenate L2 + recent L4 user lines into a single corpus string.

    Returns "" if no source files exist (then voice_scorer reports 0% with
    the "no user corpus" note, which is the correct behaviour).
    """
    parts: list[str] = []
    profile = profile_path or USER_PROFILE_PATH
    if profile.exists():
        with contextlib.suppress(OSError):
            parts.append(profile.read_text(encoding="utf-8"))

    base = sessions_dir or SESSIONS_DIR
    today = (now or datetime.now(UTC)).date()
    for path in _iter_recent_session_files(base, today=today, days=days):
        snippet = _read_session_user_text(path)
        if snippet:
            parts.append(snippet)

    corpus = "\n\n".join(parts)
    if len(corpus) > max_chars:
        # Drop oldest content first (the head); the tail is most recent.
        corpus = corpus[-max_chars:]
    return corpus
