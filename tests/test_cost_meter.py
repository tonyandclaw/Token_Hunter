from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from src.cost_meter import (
    PRICES_USD_PER_MTOK,
    BudgetState,
    Severity,
    check_thresholds,
    current_week_window,
    estimate_cost,
    price_for_model,
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


def test_budget_state_first_poll_returns_crossed_alerts(tmp_path: Path):
    _write_event(tmp_path / "2026-05-13.jsonl", cost_usd=85.0)
    state = BudgetState(budget_usd=100.0, logs_dir=tmp_path)
    alerts = state.poll()
    assert [a.pct for a in alerts] == [50, 80]


def test_budget_state_second_poll_returns_only_new_alerts(tmp_path: Path):
    _write_event(tmp_path / "2026-05-13.jsonl", cost_usd=85.0)
    state = BudgetState(budget_usd=100.0, logs_dir=tmp_path)
    state.poll()  # 50 + 80 fire
    # Same usage, no new crossings
    assert state.poll() == []
    # Add more cost so we cross 100
    _write_event(tmp_path / "2026-05-13.jsonl", cost_usd=20.0)
    new = state.poll()
    assert [a.pct for a in new] == [100]


def test_budget_state_halt_property_set_after_120_pct(tmp_path: Path):
    _write_event(tmp_path / "2026-05-13.jsonl", cost_usd=130.0)
    state = BudgetState(budget_usd=100.0, logs_dir=tmp_path)
    assert state.halted is False
    state.poll()
    assert state.halted is True
    assert state.tier2_suspended is True


def test_budget_state_tier2_suspended_at_100_not_120(tmp_path: Path):
    _write_event(tmp_path / "2026-05-13.jsonl", cost_usd=105.0)
    state = BudgetState(budget_usd=100.0, logs_dir=tmp_path)
    state.poll()
    assert state.tier2_suspended is True
    assert state.halted is False


def test_budget_state_no_alerts_below_50_pct(tmp_path: Path):
    _write_event(tmp_path / "2026-05-13.jsonl", cost_usd=10.0)
    state = BudgetState(budget_usd=100.0, logs_dir=tmp_path)
    assert state.poll() == []
    assert state.tier2_suspended is False
    assert state.halted is False


# --- pricing helpers ---


def test_prices_shape_includes_all_models():
    for model in ("opus", "kimi", "gpt"):
        rates = PRICES_USD_PER_MTOK[model]
        assert "input" in rates
        assert "output" in rates
        assert rates["input"] > 0
        assert rates["output"] > 0


def test_price_for_model_returns_dict():
    rates = price_for_model("opus")
    assert "input" in rates and "output" in rates


def test_estimate_cost_zero_tokens_is_zero():
    assert estimate_cost(model="opus", input_tokens=0, output_tokens=0) == 0.0


def test_estimate_cost_one_million_input_tokens():
    """1M input tokens at $X/Mtok should cost $X regardless of unrelated state."""
    rates = PRICES_USD_PER_MTOK["opus"]
    cost = estimate_cost(model="opus", input_tokens=1_000_000, output_tokens=0)
    assert abs(cost - rates["input"]) < 1e-9


def test_estimate_cost_splits_input_and_output():
    """Output tokens charge at a different rate from input tokens."""
    rates = PRICES_USD_PER_MTOK["opus"]
    cost = estimate_cost(model="opus", input_tokens=500_000, output_tokens=500_000)
    expected = rates["input"] * 0.5 + rates["output"] * 0.5
    assert abs(cost - expected) < 1e-9


def test_estimate_cost_kimi_is_cheaper_than_opus():
    """Pinning the routing intent: bulk on Kimi must be cheaper than Opus per Mtok."""
    opus = estimate_cost(model="opus", input_tokens=1_000_000, output_tokens=1_000_000)
    kimi = estimate_cost(model="kimi", input_tokens=1_000_000, output_tokens=1_000_000)
    assert kimi < opus


def test_estimate_cost_unknown_model_returns_zero():
    assert estimate_cost(model="phi", input_tokens=10, output_tokens=10) == 0.0


def test_estimate_cost_negative_tokens_clamped_to_zero():
    """Defensive: never charge negative amounts if the SDK returns garbage."""
    assert estimate_cost(model="opus", input_tokens=-100, output_tokens=-200) == 0.0


def test_reload_prices_picks_up_env_override(monkeypatch):
    """Operator can override defaults without editing the file."""
    from src.cost_meter import PRICES_USD_PER_MTOK, reload_prices

    monkeypatch.setenv("OPUS_INPUT_USD_PER_MTOK", "99.99")
    monkeypatch.setenv("OPUS_OUTPUT_USD_PER_MTOK", "42.5")
    reload_prices()
    try:
        assert PRICES_USD_PER_MTOK["opus"]["input"] == 99.99
        assert PRICES_USD_PER_MTOK["opus"]["output"] == 42.5
    finally:
        # Restore for downstream tests in the same process
        monkeypatch.delenv("OPUS_INPUT_USD_PER_MTOK")
        monkeypatch.delenv("OPUS_OUTPUT_USD_PER_MTOK")
        reload_prices()


def test_reload_prices_ignores_unparseable_env(monkeypatch):
    """Bad env value → keep default rather than crash or silently zero out."""
    from src.cost_meter import _DEFAULT_PRICES, PRICES_USD_PER_MTOK, reload_prices

    monkeypatch.setenv("KIMI_INPUT_USD_PER_MTOK", "not a number")
    reload_prices()
    try:
        assert PRICES_USD_PER_MTOK["kimi"]["input"] == _DEFAULT_PRICES["kimi"]["input"]
    finally:
        monkeypatch.delenv("KIMI_INPUT_USD_PER_MTOK")
        reload_prices()


def test_reload_prices_empty_string_treated_as_unset(monkeypatch):
    """Empty env var should not zero out the price."""
    from src.cost_meter import _DEFAULT_PRICES, PRICES_USD_PER_MTOK, reload_prices

    monkeypatch.setenv("GPT_INPUT_USD_PER_MTOK", "   ")
    reload_prices()
    try:
        assert PRICES_USD_PER_MTOK["gpt"]["input"] == _DEFAULT_PRICES["gpt"]["input"]
    finally:
        monkeypatch.delenv("GPT_INPUT_USD_PER_MTOK")
        reload_prices()


# --- log_turn_summary roundtrips into usage_summary ---


def test_turn_summary_feeds_usage_summary(tmp_path: Path):
    """The audit logger's new turn_summary row must surface in cost_meter totals."""
    from src.audit import AuditLogger, TokenUsage

    logger = AuditLogger(logs_dir=tmp_path)
    logger.log_turn_summary(
        session_id="abc",
        turn=0,
        tokens=TokenUsage(opus=1234),
        cost_usd=0.5,
    )
    usage = usage_summary(tmp_path)
    assert usage.events == 1
    assert usage.tokens_opus == 1234
    assert abs(usage.cost_usd - 0.5) < 1e-9
