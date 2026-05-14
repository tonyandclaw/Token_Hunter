"""AuditLogger — append one event per line to logs/{YYYY-MM-DD}.jsonl.

Schema from docs/04-security-design.md §E. The raw email body / post text MUST
NEVER hit this file: `make_event()` requires pre-hashed identifiers. The raw
copy goes to `logs/private/` encrypted (out of scope for this module).

Don't change the schema without coordinating with docs/06 Slide 11.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"


def sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class TokenUsage:
    opus: int = 0
    kimi: int = 0
    gpt: int = 0


@dataclass
class AuditEvent:
    session_id: str
    turn: int
    event_type: str  # "tool_call" | "memory_write" | "tier3_refusal" | ...
    tool: str
    tier: int
    user_confirmed: bool | None
    confirmation_message_id: str | None
    input: dict[str, Any]
    result: str  # "ok" | "error" | "refused" | "timeout"
    tokens: TokenUsage
    cost_usd: float
    memory_writes: list[str] = field(default_factory=list)
    ts: str = field(default_factory=utc_now_iso)

    def to_jsonl(self) -> str:
        payload = {
            "ts": self.ts,
            "session_id": self.session_id,
            "turn": self.turn,
            "event_type": self.event_type,
            "tool": self.tool,
            "tier": self.tier,
            "user_confirmed": self.user_confirmed,
            "confirmation_message_id": self.confirmation_message_id,
            "input": self.input,
            "result": self.result,
            "tokens": {
                "opus": self.tokens.opus,
                "kimi": self.tokens.kimi,
                "gpt": self.tokens.gpt,
            },
            "cost_usd": round(self.cost_usd, 6),
            "memory_writes": self.memory_writes,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class AuditLogger:
    def __init__(self, logs_dir: Path | None = None):
        self.logs_dir = logs_dir or LOGS_DIR
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _today_path(self, now: datetime | None = None) -> Path:
        d = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
        return self.logs_dir / f"{d}.jsonl"

    def log(self, event: AuditEvent) -> Path:
        path = self._today_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(event.to_jsonl())
            fh.write("\n")
        return path
