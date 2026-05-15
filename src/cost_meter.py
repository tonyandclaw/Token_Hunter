"""CostMeter — tally token spend from logs/*.jsonl, fire threshold alerts.

Per docs/00 §異質模型成本紀律 and docs/05:
- 6M Opus token budget over the competition = $100 USD total
- Alerts at 50% / 80% / 100% / 120% of budget
- 100% → Telegram urgent + Tier 2 actions suspended (enforced in main.py)
- 120% → only read-only operations allowed

This module is the pure tally + threshold engine. It reads audit-log files
written by `src/audit.py` and surfaces alerts; main.py decides what to do
about them (notify user, suspend Tier 2, etc.).

Pricing helpers `price_for_model` and `estimate_cost` convert raw token
counts to USD using the published list prices. Called by `agent.reply` when
it emits a turn_summary audit event after each query completes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"

# 50 / 80 / 100 / 120% thresholds per docs/04
THRESHOLDS_PCT: tuple[int, ...] = (50, 80, 100, 120)

# USD per 1M tokens.
#
# ⚠️  REVIEW BEFORE PRODUCTION USE  ⚠️
# These defaults are best-guess placeholders. Verify against the live pricing
# page before relying on budget alerts in production:
#   https://www.anthropic.com/pricing (Opus)
#   https://platform.moonshot.cn/  (Kimi K2.5 — pricing in CNY, convert)
#   https://openai.com/pricing (GPT)
#
# If your numbers differ, override at runtime via env vars rather than editing
# this file (so a price change doesn't need a code commit):
#   OPUS_INPUT_USD_PER_MTOK / OPUS_OUTPUT_USD_PER_MTOK
#   KIMI_INPUT_USD_PER_MTOK / KIMI_OUTPUT_USD_PER_MTOK
#   GPT_INPUT_USD_PER_MTOK  / GPT_OUTPUT_USD_PER_MTOK
#
# The dict shape is part of the schema contract — tests pin shape, not numbers,
# so price moves don't churn the suite. Module-level constants are evaluated
# at import; if you change env after import, call `reload_prices()`.
_DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "opus": {"input": 15.00, "output": 75.00},
    "kimi": {"input": 0.60, "output": 2.50},
    "gpt": {"input": 5.00, "output": 15.00},
}


def _env_float(name: str, default: float) -> float:
    """Read a float from env; fall back to default on missing / unparseable."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _load_prices() -> dict[str, dict[str, float]]:
    """Build the price table, honouring env-var overrides per model.field."""
    return {
        model: {
            "input": _env_float(f"{model.upper()}_INPUT_USD_PER_MTOK", defaults["input"]),
            "output": _env_float(f"{model.upper()}_OUTPUT_USD_PER_MTOK", defaults["output"]),
        }
        for model, defaults in _DEFAULT_PRICES.items()
    }


PRICES_USD_PER_MTOK: dict[str, dict[str, float]] = _load_prices()


def reload_prices() -> None:
    """Re-read env vars and update PRICES_USD_PER_MTOK in place.

    Useful if ops sets env vars after import (e.g. via a hot-config reload).
    The module-level dict is mutated, not replaced, so existing references
    stay valid.
    """
    fresh = _load_prices()
    PRICES_USD_PER_MTOK.clear()
    PRICES_USD_PER_MTOK.update(fresh)


def price_for_model(model: str) -> dict[str, float]:
    """Return {'input': X, 'output': Y} USD-per-Mtok for `model` (opus / kimi / gpt)."""
    return PRICES_USD_PER_MTOK[model]


def estimate_cost(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Pure-Python USD estimate. Used by audit-event emitters at the call site."""
    rates = PRICES_USD_PER_MTOK.get(model)
    if rates is None:
        return 0.0
    in_cost = (max(0, input_tokens) / 1_000_000) * rates["input"]
    out_cost = (max(0, output_tokens) / 1_000_000) * rates["output"]
    return in_cost + out_cost


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


class BudgetState:
    """Track which threshold alerts have already fired (per process).

    main.py calls poll() once per turn; we filter alerts to ones not yet
    seen in this process so the user gets one notification per crossing
    rather than one per turn after crossing.
    """

    def __init__(self, budget_usd: float, *, logs_dir: Path | None = None):
        self.budget_usd = budget_usd
        self.logs_dir = logs_dir
        self._fired: set[int] = set()

    def poll(self) -> list[Alert]:
        """Return any alerts whose threshold was crossed since the last poll."""
        usage = usage_summary(self.logs_dir)
        new: list[Alert] = []
        for alert in check_thresholds(usage, self.budget_usd):
            if alert.pct not in self._fired:
                self._fired.add(alert.pct)
                new.append(alert)
        return new

    @property
    def halted(self) -> bool:
        """120% reached — main.py should refuse new agent calls."""
        return 120 in self._fired

    @property
    def tier2_suspended(self) -> bool:
        """100% reached — main.py / can_use_tool should auto-deny Tier 2."""
        return 100 in self._fired or self.halted
