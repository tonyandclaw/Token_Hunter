"""Unit tests for the PreToolUse / PostToolUse hooks in src/agent.py.

We construct hook input dicts that match the SDK's TypedDict shape and call
the async callbacks directly — no SDK runtime needed.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.agent import _hash_input, make_post_tool_use_hook, make_pre_tool_use_hook
from src.audit import AuditLogger


def _pre_input(tool_name: str, tool_input: dict | None = None) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input or {},
        "tool_use_id": "tu-1",
    }


def _post_input(tool_name: str, tool_input: dict | None = None, response: str = "ok") -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input or {},
        "tool_response": response,
        "tool_use_id": "tu-1",
    }


async def test_pre_hook_allows_tier1():
    hook = make_pre_tool_use_hook("sess-1")
    out = await hook(_pre_input("mcp__gmail__list_unread"), None, {})  # type: ignore[arg-type]
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


async def test_pre_hook_denies_tier3_with_refusal_message():
    hook = make_pre_tool_use_hook("sess-1")
    out = await hook(
        _pre_input("mcp__gmail__bulk_delete", {"count": 50}),
        None,
        {},  # type: ignore[arg-type]
    )
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason.startswith("⛔ 這是 Tier 3 禁止動作:")


async def test_pre_hook_asks_for_tier2():
    hook = make_pre_tool_use_hook("sess-1")
    out = await hook(_pre_input("mcp__gmail__send", {"to": "a@b"}), None, {})  # type: ignore[arg-type]
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"


async def test_post_hook_writes_audit_jsonl(tmp_path: Path):
    audit = AuditLogger(tmp_path)
    hook = make_post_tool_use_hook("sess-XYZ", audit)
    await hook(_post_input("mcp__gmail__list_unread"), None, {})  # type: ignore[arg-type]
    await hook(_post_input("mcp__bluesky__timeline"), None, {})  # type: ignore[arg-type]

    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    parsed = [json.loads(ln) for ln in lines]
    assert parsed[0]["session_id"] == "sess-XYZ"
    assert parsed[0]["turn"] == 1
    assert parsed[1]["turn"] == 2
    assert parsed[0]["tier"] == 1


async def test_post_hook_hashes_subject_and_body(tmp_path: Path):
    """Raw subject / body must NOT appear in audit log; only their hashes do."""
    audit = AuditLogger(tmp_path)
    hook = make_post_tool_use_hook("sess-h", audit)
    await hook(
        _post_input(
            "mcp__gmail__send",
            {"to": "a@b.com", "subject": "secret", "body": "very confidential"},
        ),
        None,
        {},  # type: ignore[arg-type]
    )
    payload = json.loads(next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8").splitlines()[0])
    assert "subject" not in payload["input"]
    assert "body" not in payload["input"]
    assert "subject_hash" in payload["input"]
    assert "body_hash" in payload["input"]
    assert payload["input"]["to"] == "a@b.com"  # non-sensitive fields preserved


def test_hash_input_only_hashes_sensitive_fields():
    out = _hash_input({"to": "a@b", "subject": "hi", "body": "yo", "cc": "c@d"})
    assert out["to"] == "a@b"
    assert out["cc"] == "c@d"
    assert "subject" not in out
    assert "body" not in out
    assert "subject_hash" in out
    assert "body_hash" in out
