from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.absence_mode import (
    AbsenceMode,
    DecisionKind,
    parse_enter_command,
    parse_exit_command,
    summarize_tool_call,
)

# --- parse_enter_command ---


def test_parse_enter_command_chinese_hours():
    out = parse_enter_command("我接下來 4 小時開會,你自己處理")
    assert out is not None
    duration, note = out
    assert duration == timedelta(hours=4)
    assert "開會" in note


def test_parse_enter_command_chinese_minutes():
    out = parse_enter_command("我外出 30 分鐘")
    assert out is not None
    assert out[0] == timedelta(minutes=30)


def test_parse_enter_command_english_hours():
    out = parse_enter_command("afk 2 hours")
    assert out is not None
    assert out[0] == timedelta(hours=2)


def test_parse_enter_command_english_short_form():
    out = parse_enter_command("absence 90m")
    assert out is not None
    assert out[0] == timedelta(minutes=90)


def test_parse_enter_command_keyword_without_duration_returns_none():
    """Keyword alone is too ambiguous — refuse to enter."""
    assert parse_enter_command("我去開會") is None
    assert parse_enter_command("afk") is None


def test_parse_enter_command_duration_without_keyword_returns_none():
    """Bare durations in casual chat shouldn't trigger absence."""
    assert parse_enter_command("會議 3 小時前結束了") is None
    assert parse_enter_command("等 5 分鐘") is None


def test_parse_enter_command_does_not_match_substrings():
    """'background', 'awake' should not match the absence keywords."""
    assert parse_enter_command("background 3 hours") is None
    assert parse_enter_command("awake 1 hour") is None


# --- parse_exit_command ---


def test_parse_exit_command_chinese():
    assert parse_exit_command("我回來了") is True
    assert parse_exit_command("  回來了  ") is True


def test_parse_exit_command_english_case_insensitive():
    assert parse_exit_command("I'm back") is True
    assert parse_exit_command("im back") is True
    assert parse_exit_command("BACK") is True


def test_parse_exit_command_rejects_unrelated_text():
    assert parse_exit_command("我回來了,順便買了咖啡") is False
    assert parse_exit_command("absence is great") is False


# --- AbsenceMode lifecycle ---


def test_enter_sets_active_state():
    mode = AbsenceMode()
    now = datetime(2026, 5, 14, 10, 0, tzinfo=UTC)
    state = mode.enter(timedelta(hours=2), note="meeting", now=now)
    assert mode.is_active(now=now)
    assert not mode.is_expired(now=now)
    assert state.ends_at == now + timedelta(hours=2)
    assert state.note == "meeting"


def test_enter_rejects_zero_or_negative_duration():
    mode = AbsenceMode()
    with pytest.raises(ValueError):
        mode.enter(timedelta(0))
    with pytest.raises(ValueError):
        mode.enter(timedelta(seconds=-1))


def test_is_expired_after_window_passes():
    mode = AbsenceMode()
    start = datetime(2026, 5, 14, 10, 0, tzinfo=UTC)
    mode.enter(timedelta(hours=1), now=start)
    after = start + timedelta(hours=2)
    assert not mode.is_active(now=after)
    assert mode.is_expired(now=after)


def test_exit_returns_prior_state_and_clears():
    mode = AbsenceMode()
    mode.enter(timedelta(hours=1))
    prior = mode.exit()
    assert prior is not None
    assert mode.state() is None
    assert not mode.is_active()


def test_exit_when_not_in_absence_returns_none():
    mode = AbsenceMode()
    assert mode.exit() is None


def test_record_outside_window_raises():
    mode = AbsenceMode()
    with pytest.raises(RuntimeError):
        mode.record(DecisionKind.AUTO_EXECUTED, "mcp__gmail__send")


def test_record_appends_to_decisions():
    mode = AbsenceMode()
    mode.enter(timedelta(hours=1))
    mode.record(
        DecisionKind.AUTO_EXECUTED,
        "mcp__gmail__send",
        {"to": "alice@acme.com", "subject": "re: order"},
    )
    mode.record(DecisionKind.BLOCKED_MANUAL, "mcp__bluesky__post", {"text": "hi"})
    state = mode.state()
    assert state is not None
    assert len(state.decisions) == 2
    assert state.decisions[0].kind is DecisionKind.AUTO_EXECUTED
    assert "alice@acme.com" in state.decisions[0].summary
    # Raw args preserved for the per-decision feedback flow
    assert state.decisions[0].args == {"to": "alice@acme.com", "subject": "re: order"}
    assert state.decisions[1].args == {"text": "hi"}


def test_record_copies_args_dict():
    """Mutating the original args dict must not change the stored snapshot."""
    mode = AbsenceMode()
    mode.enter(timedelta(hours=1))
    args = {"to": "alice@acme.com"}
    mode.record(DecisionKind.AUTO_EXECUTED, "mcp__gmail__send", args)
    args["to"] = "evil@attacker.example"
    state = mode.state()
    assert state is not None
    assert state.decisions[0].args["to"] == "alice@acme.com"


def test_remaining_decays_with_time():
    mode = AbsenceMode()
    start = datetime(2026, 5, 14, 10, 0, tzinfo=UTC)
    state = mode.enter(timedelta(hours=1), now=start)
    assert state.remaining(now=start + timedelta(minutes=20)) == timedelta(minutes=40)
    assert state.remaining(now=start + timedelta(hours=2)) == timedelta(0)


# --- summarize_tool_call ---


def test_summarize_gmail():
    assert (
        summarize_tool_call("mcp__gmail__send", {"to": "alice@acme.com", "subject": "re: order"})
        == "→ alice@acme.com / re: order"
    )
    assert summarize_tool_call("mcp__gmail__send", {"to": "bob@x.io"}) == "→ bob@x.io"


def test_summarize_bluesky_truncates():
    s = summarize_tool_call("mcp__bluesky__post", {"text": "x" * 100})
    assert s.endswith("…")
    assert len(s) <= 61  # 60 chars + ellipsis


def test_summarize_learning_uses_category():
    assert (
        summarize_tool_call("mcp__memory__write_learning", {"category": "ACME 交期"})
        == "category=ACME 交期"
    )


def test_summarize_unknown_tool_empty():
    assert summarize_tool_call("custom__weird_tool", {}) == ""


# --- render_replay ---


def test_render_replay_empty_window():
    mode = AbsenceMode()
    start = datetime(2026, 5, 14, 10, 0, tzinfo=UTC)
    mode.enter(timedelta(hours=1), note="meeting", now=start)
    out = mode.render_replay()
    assert "Absence Replay" in out
    assert "meeting" in out
    assert "期間沒有 agent 決定" in out


def test_render_replay_with_decisions():
    mode = AbsenceMode()
    start = datetime(2026, 5, 14, 10, 0, tzinfo=UTC)
    mode.enter(timedelta(hours=1), note="standup", now=start)
    mode.record(
        DecisionKind.AUTO_EXECUTED,
        "mcp__gmail__send",
        {"to": "alice@acme.com"},
        now=start + timedelta(minutes=5),
    )
    mode.record(
        DecisionKind.BLOCKED_MANUAL,
        "mcp__bluesky__post",
        {"text": "first contact post"},
        now=start + timedelta(minutes=10),
    )
    out = mode.render_replay()
    assert "🤖" in out
    assert "⏸️" in out
    assert "alice@acme.com" in out
    assert "first contact post" in out
    assert "🤖 1 自動執行" in out
    assert "⏸️ 1 待你回來決定" in out


def test_render_replay_after_exit_uses_passed_state():
    mode = AbsenceMode()
    mode.enter(timedelta(hours=1), note="x")
    mode.record(DecisionKind.AUTO_EXECUTED, "mcp__gmail__send", {"to": "a@b"})
    prior = mode.exit()
    # Now state is cleared, but we can still render the captured one
    out = mode.render_replay(state=prior)
    assert "Absence Replay" in out
    assert "a@b" in out


def test_render_replay_with_no_state_returns_placeholder():
    mode = AbsenceMode()
    assert "無 absence" in mode.render_replay()
