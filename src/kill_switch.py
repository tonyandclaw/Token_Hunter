"""Kill switch — abort any in-flight action.

Per docs/00 §Kill Switch, two independent triggers:

1. User sends `STOP`, `緊急停止`, or `KILL` as a standalone message → reply
   `✋ 已停止。最後一筆 [...]` and drop any pending Tier-2 draft.
2. A `KILL.flag` file appears on disk → same effect, out-of-band.

Check `triggered()` at every turn boundary in `src/main.py`.
"""

from __future__ import annotations

from pathlib import Path

KILL_KEYWORDS: frozenset[str] = frozenset({"STOP", "緊急停止", "KILL"})

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FLAG_PATH = REPO_ROOT / "KILL.flag"

STOP_REPLY_TEMPLATE = "✋ 已停止。最後一筆 [{last_action}]"


def is_keyword(message: str) -> bool:
    """True if the message is exactly a kill keyword (with surrounding whitespace ok)."""
    return message.strip() in KILL_KEYWORDS


def flag_present(path: Path | None = None) -> bool:
    return (path or DEFAULT_FLAG_PATH).exists()


def triggered(message: str, flag_path: Path | None = None) -> bool:
    return is_keyword(message) or flag_present(flag_path)


def stop_reply(last_action: str = "無") -> str:
    return STOP_REPLY_TEMPLATE.format(last_action=last_action)
