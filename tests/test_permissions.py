from __future__ import annotations

from src.permissions import Tier, classify, refusal_message


def test_tier1_reads():
    assert classify("mcp__gmail__list_unread").tier is Tier.AUTO
    assert classify("mcp__gmail__search", {"q": "from:a@b"}).tier is Tier.AUTO
    assert classify("mcp__bluesky__timeline").tier is Tier.AUTO
    assert classify("WebSearch").tier is Tier.AUTO


def test_tier2_writes():
    assert classify("mcp__gmail__send", {"to": "x@y.com"}).tier is Tier.CONFIRM
    assert classify("mcp__bluesky__post").tier is Tier.CONFIRM
    assert classify("memory__write_user_profile").tier is Tier.CONFIRM


def test_unclassified_defaults_to_confirm():
    assert classify("some__brand_new_tool").tier is Tier.CONFIRM


def test_tier3_bulk_delete():
    assert classify("mcp__gmail__bulk_delete", {"count": 11}).tier is Tier.REFUSE
    assert classify("mcp__gmail__bulk_delete", {"count": 10}).tier is Tier.CONFIRM


def test_tier3_api_key_in_memory_write():
    leaked = classify(
        "memory__write_user_profile",
        {"value": "my key is sk-abc123def"},
    )
    assert leaked.tier is Tier.REFUSE
    assert "API key" in leaked.reason or "secret" in leaked.reason


def test_tier3_flagged_recipient():
    decision = classify(
        "mcp__gmail__send",
        {"to": "Scam@evil.example"},
        flagged_addresses=frozenset({"scam@evil.example"}),
    )
    assert decision.tier is Tier.REFUSE


def test_tier3_forbidden_substring():
    assert classify("mcp__modify_constitution").tier is Tier.REFUSE
    assert classify("mcp__modify_tier_rules").tier is Tier.REFUSE


def test_refusal_message_format():
    msg = refusal_message("recipient is flagged")
    assert msg.startswith("⛔ 這是 Tier 3 禁止動作:")
    assert "我不能執行,即使你授權。" in msg
