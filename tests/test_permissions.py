from __future__ import annotations

from src.permissions import Tier, classify, refusal_message


def test_tier1_reads():
    assert classify("mcp__gmail__list_unread").tier is Tier.AUTO
    assert classify("mcp__gmail__search", {"q": "from:a@b"}).tier is Tier.AUTO
    assert classify("mcp__bluesky__timeline").tier is Tier.AUTO
    assert classify("WebSearch").tier is Tier.AUTO


def test_tier1_kimi_bulk_generate():
    """Kimi is the agent's drafting helper — Tier 1 like Opus itself."""
    assert classify("mcp__kimi__bulk_generate").tier is Tier.AUTO


def test_tier1_read_and_glob_and_grep():
    """SDK built-in file readers — used by subagents to read memories/*.md."""
    assert classify("Read").tier is Tier.AUTO
    assert classify("Glob").tier is Tier.AUTO
    assert classify("Grep").tier is Tier.AUTO


def test_tier1_agent_delegation():
    """Calling a subagent is an internal context move, not an external write."""
    assert classify("Agent").tier is Tier.AUTO


def test_tier2_writes():
    assert classify("mcp__gmail__send", {"to": "x@y.com"}).tier is Tier.CONFIRM
    assert classify("mcp__bluesky__post").tier is Tier.CONFIRM
    assert classify("mcp__memory__write_user_profile").tier is Tier.CONFIRM
    assert classify("mcp__memory__write_learning").tier is Tier.CONFIRM


def test_unclassified_defaults_to_confirm():
    assert classify("some__brand_new_tool").tier is Tier.CONFIRM


def test_tier3_bulk_delete():
    assert classify("mcp__gmail__bulk_delete", {"count": 11}).tier is Tier.REFUSE
    assert classify("mcp__gmail__bulk_delete", {"count": 10}).tier is Tier.CONFIRM


def test_tier3_api_key_in_memory_write_value():
    leaked = classify(
        "mcp__memory__write_user_profile",
        {"value": "my key is sk-abc123def"},
    )
    assert leaked.tier is Tier.REFUSE
    assert "API key" in leaked.reason or "secret" in leaked.reason


def test_tier3_api_key_in_user_profile_note():
    """Note field of write_user_profile is also scanned.

    The test value contains the `AKIA` substring our classifier matches on,
    but is intentionally too short to trip generic AWS-key secret scanners
    (which expect AKIA followed by 16 uppercase chars).
    """
    # Construct via concat so even the substring `AKIA<16hex>` never appears
    # as a single literal in source.
    fake_shape = "AKIA" + "XXXX_TEST"
    leaked = classify(
        "mcp__memory__write_user_profile",
        {"note": f"remember my {fake_shape} key"},
    )
    assert leaked.tier is Tier.REFUSE


def test_tier3_api_key_in_learning_observation():
    """observation / rule fields of write_learning are also scanned."""
    leaked = classify(
        "mcp__memory__write_learning",
        {"observation": "use ghp_abcdef for deploys", "rule": "always set token"},
    )
    assert leaked.tier is Tier.REFUSE


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


def test_tier3_mcp_install_refused():
    """docs/04 §A: installing non-Composio/Anthropic MCP servers is Tier 3 refusal,
    not Tier 2 confirm. Even if the user asks."""
    assert classify("mcp__install_server").tier is Tier.REFUSE
    assert classify("mcp__install").tier is Tier.REFUSE


def test_tier3_read_blocks_env_file():
    """Read('.env') → Tier 3 refusal. Prevents API-key exfil via SDK built-in Read."""
    assert classify("Read", {"file_path": ".env"}).tier is Tier.REFUSE
    assert classify("Read", {"file_path": "/Users/tony/repo/.env"}).tier is Tier.REFUSE
    assert classify("Read", {"file_path": "./.env.production"}).tier is Tier.REFUSE


def test_tier3_read_blocks_ssh_keys():
    assert classify("Read", {"file_path": "/home/tony/.ssh/id_rsa"}).tier is Tier.REFUSE
    assert classify("Read", {"file_path": "~/.ssh/known_hosts"}).tier is Tier.REFUSE
    assert classify("Read", {"file_path": "/etc/ssh/ssh_host_ed25519_key"}).tier is Tier.REFUSE


def test_tier3_read_blocks_etc_shadow():
    assert classify("Read", {"file_path": "/etc/shadow"}).tier is Tier.REFUSE
    assert classify("Read", {"file_path": "/etc/passwd"}).tier is Tier.REFUSE


def test_tier3_read_blocks_trust_state():
    """Agent shouldn't directly Read the trust/ JSONs — those are internal state."""
    assert classify("Read", {"file_path": "trust/curves.json"}).tier is Tier.REFUSE
    assert classify("Read", {"file_path": "trust/sdk_sessions.json"}).tier is Tier.REFUSE


def test_tier3_glob_blocks_key_patterns():
    assert classify("Glob", {"pattern": "**/.env"}).tier is Tier.REFUSE
    assert classify("Glob", {"pattern": "**/id_rsa"}).tier is Tier.REFUSE
    assert classify("Glob", {"pattern": "**/secrets/**"}).tier is Tier.REFUSE


def test_tier3_glob_root_path_also_checked():
    """The `path` arg (search root) is checked too, not just `pattern`."""
    decision = classify("Glob", {"pattern": "*.md", "path": "/home/tony/.ssh"})
    assert decision.tier is Tier.REFUSE


def test_tier1_read_memories_md_still_allowed():
    """Legit reads of memories/*.md must still be Tier 1 (the agent reads L2/L3)."""
    assert classify("Read", {"file_path": "memories/user-profile.md"}).tier is Tier.AUTO
    assert classify("Read", {"file_path": "memories/learnings.md"}).tier is Tier.AUTO
    assert classify("Read", {"file_path": "memories/sessions/2026-05-14.md"}).tier is Tier.AUTO


def test_tier1_glob_memories_still_allowed():
    """Globbing inside memories/ is fine — that's how the agent inventories its L4 log."""
    assert classify("Glob", {"pattern": "memories/sessions/*.md"}).tier is Tier.AUTO


def test_path_check_case_insensitive():
    """Sensitivity check is case-insensitive — uppercase variants still blocked."""
    assert classify("Read", {"file_path": "/HOME/Tony/.SSH/ID_RSA"}).tier is Tier.REFUSE
    assert classify("Read", {"file_path": "/PATH/TO/.Env"}).tier is Tier.REFUSE


def test_refusal_message_format():
    msg = refusal_message("recipient is flagged")
    assert msg.startswith("⛔ 這是 Tier 3 禁止動作:")
    assert "我不能執行,即使你授權。" in msg
