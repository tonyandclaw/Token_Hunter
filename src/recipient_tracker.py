"""Track which recipients the user has already confirmed sending to.

docs/03 §不做 requires "Tier 2 永遠擋給不認識的人寫信" — meaning every send
to a stranger should get a friction layer beyond the normal Tier-2 confirm.
We implement that by tagging the confirm prompt with a `⚠️ first contact`
banner when the recipient has never been approved before.

How "known" is determined:
  - On startup, scan all `logs/{date}.jsonl` files for past `mcp__gmail__send`
    or `mcp__gmail__reply` events with `user_confirmed = True`. Extract the
    `to` address from `input`. The `to` field is NOT in `HASHABLE_FIELDS`
    (only subject/body/text/content are hashed) — so the audit log carries
    plaintext recipient addresses, which is exactly what we need here.
  - During runtime, when a user approves a new send, `mark_seen(addr)`
    is called so the SAME address doesn't get flagged on subsequent turns
    in this process.

Called by:
  - src/main.py:main()  → load_from_audit at startup
  - src/tier2_confirm.py:render_prompt  → is_known check
  - src/tier2_confirm.py:await_decision → mark_seen after approval
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("fushou.recipient_tracker")

GMAIL_SEND_TOOLS: frozenset[str] = frozenset({"mcp__gmail__send", "mcp__gmail__reply"})


class KnownRecipients:
    """In-memory set of email addresses the user has confirmed sending to."""

    def __init__(self) -> None:
        self._known: set[str] = set()

    def load_from_audit(self, logs_dir: Path) -> None:
        """Populate `_known` from all past audit JSONL files.

        Tolerant of malformed lines, unreadable files, and unexpected event
        shapes — never raises. The cost of a wrong-classification "first
        contact" warning is a tiny UX wart; the cost of crashing main()
        startup is a dead bot.
        """
        if not logs_dir.exists():
            return
        for log_path in sorted(logs_dir.glob("*.jsonl")):
            try:
                content = log_path.read_text(encoding="utf-8")
            except OSError:
                continue
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tool = str(event.get("tool", ""))
                if tool not in GMAIL_SEND_TOOLS:
                    continue
                # Both `user_confirmed=True` and `result="ok"` are signals
                # the send actually went through and the user OK'd it.
                if not (event.get("user_confirmed") is True or event.get("result") == "ok"):
                    continue
                to_addr = str((event.get("input") or {}).get("to", "")).strip().lower()
                if to_addr:
                    self._known.add(to_addr)

    def is_known(self, addr: str) -> bool:
        return addr.strip().lower() in self._known

    def mark_seen(self, addr: str) -> None:
        cleaned = addr.strip().lower()
        if cleaned:
            self._known.add(cleaned)

    def count(self) -> int:
        return len(self._known)


def is_gmail_send_tool(tool_name: str) -> bool:
    """True if `tool_name` is a gmail send/reply that should trigger first-contact check."""
    return tool_name in GMAIL_SEND_TOOLS
