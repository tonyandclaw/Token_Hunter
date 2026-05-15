from __future__ import annotations

import json
from pathlib import Path

from src.audit import AuditEvent, AuditLogger, TokenUsage, sha256_short


def _sample_event(tool: str = "mcp__gmail__send") -> AuditEvent:
    return AuditEvent(
        session_id="sess-1",
        turn=3,
        event_type="tool_call",
        tool=tool,
        tier=2,
        user_confirmed=True,
        confirmation_message_id="tg-msg-42",
        input={"subject_hash": sha256_short("hi"), "body_hash": sha256_short("body")},
        result="ok",
        tokens=TokenUsage(opus=1240, kimi=0, gpt=0),
        cost_usd=0.0186,
        memory_writes=["learnings.md+1"],
    )


def test_jsonl_one_line_per_event(tmp_path: Path):
    log = AuditLogger(tmp_path / "logs")
    log.log(_sample_event("mcp__gmail__send"))
    log.log(_sample_event("mcp__bluesky__post"))
    files = list((tmp_path / "logs").glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["tool"] == "mcp__gmail__send"
    assert parsed[1]["tool"] == "mcp__bluesky__post"


def test_schema_has_required_fields(tmp_path: Path):
    log = AuditLogger(tmp_path / "logs")
    log.log(_sample_event())
    line = next((tmp_path / "logs").glob("*.jsonl")).read_text(encoding="utf-8").splitlines()[0]
    payload = json.loads(line)
    # docs/04 §E required fields
    for field in (
        "ts",
        "session_id",
        "turn",
        "event_type",
        "tool",
        "tier",
        "user_confirmed",
        "confirmation_message_id",
        "input",
        "result",
        "tokens",
        "cost_usd",
        "memory_writes",
    ):
        assert field in payload, f"missing required field {field!r}"
    assert set(payload["tokens"]) == {"opus", "kimi", "gpt"}


def test_input_carries_hashes_not_raw(tmp_path: Path):
    """docs/04 §E: raw body MUST NOT appear in the audit log."""
    log = AuditLogger(tmp_path / "logs")
    log.log(_sample_event())
    line = next((tmp_path / "logs").glob("*.jsonl")).read_text(encoding="utf-8").splitlines()[0]
    payload = json.loads(line)
    assert "body_hash" in payload["input"]
    assert "subject_hash" in payload["input"]
    # spot-check that no obvious raw-body field is present
    assert "body" not in payload["input"]
    assert "subject" not in payload["input"]


def test_sha256_short_is_deterministic_and_16_hex():
    a = sha256_short("hello")
    b = sha256_short("hello")
    assert a == b
    assert len(a) == 16
    assert all(c in "0123456789abcdef" for c in a)


def test_sha256_short_distinguishes_different_inputs():
    assert sha256_short("a") != sha256_short("b")


def test_sha256_short_handles_unicode():
    """CJK input must hash to 16 hex chars without raising."""
    out = sha256_short("週五交付,沒問題。")
    assert len(out) == 16


def test_audit_event_to_jsonl_rounds_floats():
    """cost_usd rounding pinned at 6 decimal places (docs/04 §E)."""
    ev = AuditEvent(
        session_id="s",
        turn=1,
        event_type="tool_call",
        tool="x",
        tier=1,
        user_confirmed=None,
        confirmation_message_id=None,
        input={},
        result="ok",
        tokens=TokenUsage(),
        cost_usd=0.123456789,  # 9 digits
    )
    payload = json.loads(ev.to_jsonl())
    # Stringified value should have at most 6 decimal places
    assert payload["cost_usd"] == 0.123457


def test_audit_event_ts_is_iso8601_utc():
    ev = AuditEvent(
        session_id="s",
        turn=1,
        event_type="tool_call",
        tool="x",
        tier=1,
        user_confirmed=None,
        confirmation_message_id=None,
        input={},
        result="ok",
        tokens=TokenUsage(),
        cost_usd=0.0,
    )
    payload = json.loads(ev.to_jsonl())
    # Format: YYYY-MM-DDTHH:MM:SSZ
    assert payload["ts"].endswith("Z")
    assert "T" in payload["ts"]
    assert len(payload["ts"]) == 20


def test_log_turn_summary_writes_correct_event_type(tmp_path: Path):
    """The new summary row is event_type='turn_summary', NOT 'tool_call'."""
    logger = AuditLogger(tmp_path / "logs")
    logger.log_turn_summary(
        session_id="abc",
        turn=0,
        tokens=TokenUsage(opus=100),
        cost_usd=0.05,
    )
    line = next((tmp_path / "logs").glob("*.jsonl")).read_text(encoding="utf-8").strip()
    payload = json.loads(line)
    assert payload["event_type"] == "turn_summary"
    assert payload["session_id"] == "abc"
    assert payload["tokens"]["opus"] == 100
    assert payload["tool"] == ""
    assert payload["tier"] == 0


def test_audit_logger_creates_log_dir(tmp_path: Path):
    """logs_dir is created lazily — first .log() should mkdir -p."""
    log_dir = tmp_path / "nested" / "logs"
    assert not log_dir.exists()
    logger = AuditLogger(log_dir)
    # AuditLogger.__init__ also calls mkdir(parents=True, exist_ok=True)
    assert log_dir.exists()
    logger.log(_sample_event())
    assert any(log_dir.glob("*.jsonl"))


def test_jsonl_payload_preserves_chinese_chars(tmp_path: Path):
    """ensure_ascii=False in to_jsonl — Chinese should be readable in the log."""
    ev = AuditEvent(
        session_id="s",
        turn=1,
        event_type="tool_call",
        tool="mcp__memory__write_learning",
        tier=2,
        user_confirmed=True,
        confirmation_message_id=None,
        input={"category": "ACME 交期"},
        result="ok",
        tokens=TokenUsage(),
        cost_usd=0.0,
    )
    line = ev.to_jsonl()
    assert "ACME 交期" in line
