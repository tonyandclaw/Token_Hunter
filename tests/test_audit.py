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
