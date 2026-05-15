"""Append-only log of forensic findings, one event per line.

Whenever `gmail_mcp.read` auto-runs forensic.analyze on an incoming email
(or any other call site triggers a scan), we drop a row into
`logs/forensic.jsonl`. The /status command and the CLI ops tool read this
log to surface recent findings; the audit JSONL (logs/{date}.jsonl) is
left alone so its schema doesn't grow.

Called by:
  - src/tools/gmail_mcp.py:build_tools().read  (auto-trigger on every read)
  - tests via src.forensic_log.record  (offline)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.forensic import ForensicReport

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = REPO_ROOT / "logs" / "forensic.jsonl"


@dataclass(frozen=True)
class ForensicLogEntry:
    """One audit-style row. Body/subject NEVER appear here — only hashes."""

    ts: str
    source: str  # e.g. "gmail__read"
    sender_domain: str
    severity: str  # "info" | "warning" | "block"
    injection_hits: tuple[str, ...]
    domain_typosquat: bool
    body_hash: str  # sha256_short of the raw body — looked up if needed
    extra: dict = field(default_factory=dict)

    def to_jsonl(self) -> str:
        payload = asdict(self)
        payload["injection_hits"] = list(self.injection_hits)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(
    report: ForensicReport,
    *,
    source: str,
    body_hash: str,
    path: Path | None = None,
    extra: dict | None = None,
) -> Path:
    """Append a row for the given report. Creates the parent dir if needed."""
    target = path or DEFAULT_LOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    entry = ForensicLogEntry(
        ts=_utc_now_iso(),
        source=source,
        sender_domain=report.domain.sender_domain if report.domain else "",
        severity=report.severity,
        injection_hits=report.injection_hits,
        domain_typosquat=bool(report.domain and report.domain.looks_typosquat),
        body_hash=body_hash,
        extra=extra or {},
    )
    # Single write of `line + "\n"` for kernel-level atomic append (POSIX
    # O_APPEND guarantees atomicity for writes <= PIPE_BUF).
    line = entry.to_jsonl() + "\n"
    with target.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return target


def read_recent(
    *,
    path: Path | None = None,
    limit: int = 5,
    min_severity: str = "info",
) -> list[dict]:
    """Return the most recent N entries, filtered to severity >= min_severity.

    Order: most-recent first. Returns [] if the log doesn't exist yet.
    """
    target = path or DEFAULT_LOG_PATH
    if not target.exists():
        return []
    sev_rank = {"info": 0, "warning": 1, "block": 2}
    threshold = sev_rank.get(min_severity, 0)
    out: list[dict] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if sev_rank.get(row.get("severity", "info"), 0) < threshold:
            continue
        out.append(row)
    return list(reversed(out))[:limit]
