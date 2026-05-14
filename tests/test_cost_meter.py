from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from src.cost_meter import (
    Severity,
    check_thresholds,
    current_week_window,
    usage_summary,
)


def _write_event(
    path: Path,
    *,
    cost_usd: float = 0.01,
    opus: int = 0,
    kimi: int = 0,
    gpt: int = 0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": "2026-05-13T00:00:00Z",
        "session_id": "s",
        "turn": 1,
        "event_type": "tool_call",
        "tool": "x",
        "tier": 1,
        "user_confirmed": None,
        "confirmation_message_id": None,
        "input": {},
        "result": "ok",
        "tokens": {"opus": opus, "kimi": kimi, "gpt": gpt},
        "cost_usd": cost_usd,
        "memory_writes": [],
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event))
        fh.write("\n")


def test_usage_summary_sums_across_files(tmp_path: Path):
    _write_event(tmp_path / "2026-05-12.jsonl", cost_usd=0.50, opus=1000)
    _write_event(tmp_path / "2026-05-13.jsonl", cost_usd=0.30, opus=500, kimi=200)
    _write_event(tmp_path / "2026-05-13.jsonl", cost_usd=0.10, gpt=50)
    u = usage_summary(tmp_path)
    assert u.events == 3
    assert u.cost_usd == 0.90
    assert u.tokens_opus == 1500
    assert u.tokens_kimi == 200
    assert u.tokens_gpt == 50
    assert u.tokens_total == 1750


def test_usage_summary_respects_date_window(tmp_path: Path):
    _write_event(tmp_path / "2026-05-12.jsonl", cost_usd=1.00)
    _write_event(tmp_path / "2026-05-13.jsonl", cost_usd=2.00)
    _write_event(tmp_path / "2026-05-14.jsonl", cost_usd=3.00)
    u = usage_summary(tmp_path, since=date(2026, 5, 13), until=date(2026, 5, 13))
    assert u.cost_usd == 2.00
    assert u.events == 1


def test_usage_summary_ignores_non_date_files_and_empty_lines(tmp_path: Path):
    (tmp_path / "notes.jsonl").write_text("garbage\n", encoding="utf-8")
    (tmp_path / "2026-05-13.jsonl").write_text("\n\n", encoding="utf-8")
    u = usage_summary(tmp_path)
    assert u.events == 0
    assert u.cost_usd == 0.0


def test_usage_summary_skips_unparseable_lines(tmp_path: Path):
    path = tmp_path / "2026-05-13.jsonl"
    path.write_text('{"cost_usd": 1.0, "tokens": {"opus": 100}}\n', encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("this is not json\n")
        fh.write('{"cost_usd": 2.0}\n')
    u = usage_summary(tmp_path)
    assert u.events == 2
    assert u.cost_usd == 3.0
    assert u.tokens_opus == 100


def test_check_thresholds_no_alerts_below_50_pct(tmp_path: Path):
    _write_event(tmp_path / "2026-05-13.jsonl", cost_usd=40.0)
    alerts = check_thresholds(usage_summary(tmp_path), budget_usd=100.0)
    assert alerts == []


def test_check_thresholds_fires_each_crossed_level(tmp_path: Path):
    _write_event(tmp_path / "2026-05-13.jsonl", cost_usd=85.0)
    alerts = check_thresholds(usage_summary(tmp_path), budget_usd=100.0)
    assert [a.pct for a in alerts] == [50, 80]
    assert alerts[0].severity is Severity.INFO
    assert alerts[1].severity is Severity.WARNING


def test_check_thresholds_halt_at_120(tmp_path: Path):
    _write_event(tmp_path / "2026-05-13.jsonl", cost_usd=125.0)
    alerts = check_thresholds(usage_summary(tmp_path), budget_usd=100.0)
    assert [a.pct for a in alerts] == [50, 80, 100, 120]
    assert alerts[-1].severity is Severity.HALT


def test_check_thresholds_zero_budget_returns_nothing(tmp_path: Path):
    _write_event(tmp_path / "2026-05-13.jsonl", cost_usd=10.0)
    assert check_thresholds(usage_summary(tmp_path), budget_usd=0.0) == []


def test_current_week_window_monday_to_sunday():
    wednesday = datetime(2026, 5, 13, tzinfo=UTC)
    start, end = current_week_window(wednesday)
    assert start == date(2026, 5, 11)  # Monday
    assert end == date(2026, 5, 17)  # Sunday
