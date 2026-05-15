"""Persisted user_id → SDK session_id map for cross-restart context resume.

When the SDK returns a `SystemMessage(subtype="init")` event, we capture
its `session_id` and pass it as `resume=` on the next call so the agent
remembers prior conversation context. Without persistence, every process
restart resets that mapping and the agent's memory across user messages
goes back to 0.

This is the same file-backed pattern as `trust/curves.json` and
`trust/teams_conversations.json`. Single JSON object, atomic-replace on
write. Single-writer (one bot process) — no locking needed.

Called by: `src/main.py:on_text` after each `reply()` returns a fresh
sdk_session_id; loaded once at `main()` startup.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO_ROOT / "trust" / "sdk_sessions.json"


class SessionStore:
    """File-backed dict[user_id → sdk_session_id] with atomic write."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULT_PATH
        self._cache: dict[str, str] = {}

    def load(self) -> None:
        """Populate `_cache` from disk. Empty dict if file is missing."""
        if not self._path.exists():
            self._cache = {}
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            # Corrupt file — start clean rather than crash the bot. The
            # worst case is we lose continuity for one turn.
            self._cache = {}
            return
        # Defensive: coerce both keys and values to str even if some other
        # caller wrote ints.
        self._cache = {str(k): str(v) for k, v in raw.items() if v}

    def save(self) -> None:
        """Write `_cache` to disk atomically (write-temp + rename)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write so a crash mid-write doesn't leave a half-flushed file
        # that breaks the next load().
        fd, tmp_path = tempfile.mkstemp(
            prefix=".sdk_sessions.", suffix=".json.tmp", dir=str(self._path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._cache, fh, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp_path, self._path)
        except Exception:
            # Best-effort cleanup of the temp file on any failure
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def get(self, user_id: str) -> str | None:
        return self._cache.get(user_id)

    def set(self, user_id: str, sdk_session_id: str) -> None:
        """Update + persist immediately. Cheap — single small JSON file."""
        if not sdk_session_id:
            return
        if self._cache.get(user_id) == sdk_session_id:
            return  # no-op, don't churn the file
        self._cache[user_id] = sdk_session_id
        self.save()

    def forget(self, user_id: str) -> None:
        """Drop a user's session — e.g. after a kill switch fires."""
        if user_id in self._cache:
            del self._cache[user_id]
            self.save()

    def all(self) -> dict[str, str]:
        """Read-only snapshot for /status or CLI inspection."""
        return dict(self._cache)

    def count(self) -> int:
        """Number of users with persisted SDK sessions. Cheaper than `len(all())`."""
        return len(self._cache)
