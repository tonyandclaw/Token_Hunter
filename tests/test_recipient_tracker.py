from __future__ import annotations

import json
from pathlib import Path

from src.recipient_tracker import KnownRecipients, is_gmail_send_tool


def _write_audit_event(path: Path, **fields) -> None:
    """Append one fake audit-log event to `path`."""
    event = {
        "ts": "2026-05-14T00:00:00Z",
        "session_id": "s",
        "turn": 1,
        "event_type": "tool_call",
        "tool": "mcp__gmail__send",
        "tier": 2,
        "user_confirmed": True,
        "confirmation_message_id": None,
        "input": {"to": "alice@acme.com"},
        "result": "ok",
        "tokens": {"opus": 0, "kimi": 0, "gpt": 0},
        "cost_usd": 0.0,
        "memory_writes": [],
    }
    event.update(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def test_load_from_audit_populates_set(tmp_path: Path):
    log_dir = tmp_path / "logs"
    _write_audit_event(log_dir / "2026-05-14.jsonl", input={"to": "alice@acme.com"})
    _write_audit_event(log_dir / "2026-05-14.jsonl", input={"to": "bob@x.io"})
    kr = KnownRecipients()
    kr.load_from_audit(log_dir)
    assert kr.count() == 2
    assert kr.is_known("alice@acme.com")
    assert kr.is_known("bob@x.io")


def test_load_skips_unconfirmed_sends(tmp_path: Path):
    """A send the user rejected shouldn't make the recipient 'known'."""
    log_dir = tmp_path / "logs"
    _write_audit_event(
        log_dir / "2026-05-14.jsonl",
        input={"to": "rejected@spam.com"},
        user_confirmed=False,
        result="refused",
    )
    kr = KnownRecipients()
    kr.load_from_audit(log_dir)
    assert not kr.is_known("rejected@spam.com")


def test_load_skips_non_gmail_tools(tmp_path: Path):
    log_dir = tmp_path / "logs"
    _write_audit_event(
        log_dir / "2026-05-14.jsonl",
        tool="mcp__bluesky__post",
        input={"text": "hi"},
    )
    _write_audit_event(
        log_dir / "2026-05-14.jsonl",
        tool="mcp__memory__write_user_profile",
        input={"note": "x"},
    )
    kr = KnownRecipients()
    kr.load_from_audit(log_dir)
    # Neither tool produces a recipient address; set stays empty
    assert kr.count() == 0


def test_load_handles_gmail_reply_same_as_send(tmp_path: Path):
    log_dir = tmp_path / "logs"
    _write_audit_event(
        log_dir / "2026-05-14.jsonl",
        tool="mcp__gmail__reply",
        input={"to": "carol@y.io"},
    )
    kr = KnownRecipients()
    kr.load_from_audit(log_dir)
    assert kr.is_known("carol@y.io")


def test_load_is_case_insensitive(tmp_path: Path):
    log_dir = tmp_path / "logs"
    _write_audit_event(log_dir / "2026-05-14.jsonl", input={"to": "Alice@ACME.com"})
    kr = KnownRecipients()
    kr.load_from_audit(log_dir)
    assert kr.is_known("alice@acme.com")
    assert kr.is_known("ALICE@acme.COM")
    assert kr.is_known("  alice@acme.com  ")  # whitespace also normalised


def test_load_skips_malformed_lines(tmp_path: Path):
    """Garbled JSONL row shouldn't crash startup."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "2026-05-14.jsonl"
    log_path.write_text(
        '{"tool": "mcp__gmail__send", "user_confirmed": true, "input": {"to": "a@b"}}\n'
        "this is not json\n"
        "\n"
        '{"tool": "mcp__gmail__send", "user_confirmed": true, "input": {"to": "c@d"}}\n',
        encoding="utf-8",
    )
    kr = KnownRecipients()
    kr.load_from_audit(log_dir)
    assert kr.count() == 2  # the two valid rows survived


def test_load_handles_missing_logs_dir(tmp_path: Path):
    """No logs/ yet → empty set, no exception."""
    kr = KnownRecipients()
    kr.load_from_audit(tmp_path / "no-such-dir")
    assert kr.count() == 0


def test_mark_seen_adds_to_set():
    kr = KnownRecipients()
    assert not kr.is_known("new@stranger.io")
    kr.mark_seen("new@stranger.io")
    assert kr.is_known("new@stranger.io")


def test_mark_seen_normalises_case_and_whitespace():
    kr = KnownRecipients()
    kr.mark_seen("  Alice@ACME.com  ")
    assert kr.is_known("alice@acme.com")
    assert kr.is_known("ALICE@acme.COM")


def test_mark_seen_ignores_empty_input():
    kr = KnownRecipients()
    kr.mark_seen("")
    kr.mark_seen("   ")
    assert kr.count() == 0


def test_is_gmail_send_tool():
    assert is_gmail_send_tool("mcp__gmail__send")
    assert is_gmail_send_tool("mcp__gmail__reply")
    assert not is_gmail_send_tool("mcp__gmail__list_unread")
    assert not is_gmail_send_tool("mcp__gmail__send_extra")  # only exact matches
