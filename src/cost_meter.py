"""CostMeter — tally token spend from logs/*.jsonl, fire threshold alerts.

Per docs/00 §異質模型成本紀律 and docs/05:
- 6M Opus token budget over the competition = $100 USD total
- Alerts at 50% / 80% / 100% / 120% of budget
- 100% → Telegram urgent + Tier 2 actions suspended (enforced in main.py)
- 120% → only read-only operations allowed

This module is the pure tally + threshold engine. It reads audit-log files
written by `src/audit.py` and surfaces alerts; main.py decides what to do
about them (notify user, suspend Tier 2, etc.).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"

# 50 / 80 / 100 / 120% thresholds per docs/04
THRESHOLDS_PCT: tuple[int, ...] = (50, 80, 100, 120)


class Severity(Enum):
    INFO = "info"  # 50%
    WARNING = "warning"  # 80%
    URGENT = "urgent"  # 100%
    HALT = "halt"  # 120%


_SEVERITY_BY_PCT: dict[int, Severity] = {
    50: Severity.INFO,
    80: Severity.WARNING,
    100: Severity.URGENT,
    120: Severity.HALT,
}


@dataclass(frozen=True)
class Usage:
    cost_usd: float
    tokens_opus: int
    tokens_kimi: int
    tokens_gpt: int
    events: int

    @property
    def tokens_total(self) -> int:
        return self.tokens_opus + self.tokens_kimi + self.tokens_gpt


@dataclass(frozen=True)
class Alert:
    pct: int
    severity: Severity
    message: str


def _iter_log_files(
    logs_dir: Path,
    *,
    since: date | None = None,
    until: date | None = None,
) -> list[Path]:
    if not logs_dir.exists():
        return []
    out: list[Path] = []
    for path in sorted(logs_dir.glob("*.jsonl")):
        try:
            d = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if since and d < since:
            continue
        if until and d > until:
            continue
        out.append(path)
    return out


def usage_summary(
    logs_dir: Path | None = None,
    *,
    since: date | None = None,
    until: date | None = None,
) -> Usage:
    """Sum every event in `since..until` (inclusive). Both bounds are optional."""
    cost = 0.0
    opus = kimi = gpt = events = 0
    for path in _iter_log_files(logs_dir or LOGS_DIR, since=since, until=until):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cost += float(event.get("cost_usd") or 0)
                tokens = event.get("tokens") or {}
                opus += int(tokens.get("opus") or 0)
                kimi += int(tokens.get("kimi") or 0)
                gpt += int(tokens.get("gpt") or 0)
                events += 1
    return Usage(cost, opus, kimi, gpt, events)


def check_thresholds(usage: Usage, budget_usd: float) -> list[Alert]:
    """Return one Alert per threshold that's been crossed, ordered low → high."""
    if budget_usd <= 0:
        return []
    pct_used = (usage.cost_usd / budget_usd) * 100
    return [
        Alert(
            pct=t,
            severity=_SEVERITY_BY_PCT[t],
            message=(
                f"cost {usage.cost_usd:.2f} USD = {pct_used:.0f}% of {budget_usd:.0f} USD "
                f"budget (≥ {t}% threshold)"
            ),
        )
        for t in THRESHOLDS_PCT
        if pct_used >= t
    ]


def current_week_window(now: datetime | None = None) -> tuple[date, date]:
    """Monday→Sunday inclusive, anchored on `now` (default: UTC today)."""
    today = (now or datetime.now(UTC)).date()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start, end
