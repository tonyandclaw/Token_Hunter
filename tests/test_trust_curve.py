from __future__ import annotations

import json
from pathlib import Path

from src.trust_curve import (
    DEFAULT_PROPOSE_THRESHOLD,
    PatternState,
    TrustCurve,
    pattern_key,
    render_proposal,
)


def test_pattern_key_gmail_send_keys_on_recipient():
    k1 = pattern_key("mcp__gmail__send", {"to": "alice@a.com", "body": "1"})
    k2 = pattern_key("mcp__gmail__send", {"to": "alice@a.com", "body": "2"})
    assert k1 == k2
    assert k1 == ("mcp__gmail__send", "alice@a.com")


def test_pattern_key_gmail_send_different_recipients_distinct():
    k1 = pattern_key("mcp__gmail__send", {"to": "alice@a.com"})
    k2 = pattern_key("mcp__gmail__send", {"to": "bob@b.com"})
    assert k1 != k2


def test_pattern_key_unknown_tool_uses_star_fingerprint():
    k = pattern_key("custom__tool", {"foo": "bar"})
    assert k == ("custom__tool", "*")


def test_pattern_key_missing_field_normalizes_to_question_mark():
    k = pattern_key("mcp__gmail__send", {})
    assert k == ("mcp__gmail__send", "?")


def test_pattern_key_lowercases_and_strips():
    k1 = pattern_key("mcp__gmail__send", {"to": " ALICE@A.com "})
    k2 = pattern_key("mcp__gmail__send", {"to": "alice@a.com"})
    assert k1 == k2


def test_record_increments_streak_and_total():
    tc = TrustCurve(path=None)
    s = tc.record("mcp__gmail__send", {"to": "alice@a.com"}, approved=True)
    assert s.streak == 1
    assert s.total_confirms == 1
    s = tc.record("mcp__gmail__send", {"to": "alice@a.com"}, approved=True)
    assert s.streak == 2
    assert s.total_confirms == 2


def test_record_deny_resets_streak_but_increments_denials():
    tc = TrustCurve(path=None)
    tc.record("mcp__gmail__send", {"to": "alice@a.com"}, approved=True)
    tc.record("mcp__gmail__send", {"to": "alice@a.com"}, approved=True)
    s = tc.record("mcp__gmail__send", {"to": "alice@a.com"}, approved=False)
    assert s.streak == 0
    assert s.total_confirms == 2
    assert s.total_denials == 1


def test_should_propose_only_after_threshold_streak():
    tc = TrustCurve(path=None, propose_threshold=3)
    for _ in range(2):
        s = tc.record("mcp__gmail__send", {"to": "alice@a.com"}, approved=True)
        assert tc.should_propose(s) is False
    s = tc.record("mcp__gmail__send", {"to": "alice@a.com"}, approved=True)
    assert tc.should_propose(s) is True


def test_mark_proposed_silences_repeat_proposals():
    tc = TrustCurve(path=None, propose_threshold=2)
    tc.record("mcp__gmail__send", {"to": "a@a"}, approved=True)
    s = tc.record("mcp__gmail__send", {"to": "a@a"}, approved=True)
    assert tc.should_propose(s) is True
    tc.mark_proposed("mcp__gmail__send", {"to": "a@a"})
    s = tc.record("mcp__gmail__send", {"to": "a@a"}, approved=True)
    assert tc.should_propose(s) is False


def test_denial_clears_proposed_so_fresh_streak_can_re_propose():
    tc = TrustCurve(path=None, propose_threshold=2)
    tc.record("mcp__gmail__send", {"to": "a@a"}, approved=True)
    tc.record("mcp__gmail__send", {"to": "a@a"}, approved=True)
    tc.mark_proposed("mcp__gmail__send", {"to": "a@a"})
    # Deny resets streak and clears proposed
    tc.record("mcp__gmail__send", {"to": "a@a"}, approved=False)
    tc.record("mcp__gmail__send", {"to": "a@a"}, approved=True)
    s = tc.record("mcp__gmail__send", {"to": "a@a"}, approved=True)
    assert tc.should_propose(s) is True


def test_load_or_empty_roundtrips_json(tmp_path: Path):
    path = tmp_path / "curves.json"
    tc = TrustCurve.load_or_empty(path, propose_threshold=2)
    tc.record("mcp__gmail__send", {"to": "alice@a.com"}, approved=True)
    tc.record("mcp__gmail__send", {"to": "alice@a.com"}, approved=True)
    tc.mark_proposed("mcp__gmail__send", {"to": "alice@a.com"})

    reloaded = TrustCurve.load_or_empty(path, propose_threshold=2)
    state = reloaded.state_for("mcp__gmail__send", {"to": "alice@a.com"})
    assert state.streak == 2
    assert state.total_confirms == 2
    assert state.proposed is True


def test_load_or_empty_corrupt_file_falls_back_clean(tmp_path: Path):
    path = tmp_path / "curves.json"
    path.write_text("{not json", encoding="utf-8")
    tc = TrustCurve.load_or_empty(path)
    assert tc.state_for("anything", {}).streak == 0


def test_load_or_empty_missing_file_returns_empty(tmp_path: Path):
    tc = TrustCurve.load_or_empty(tmp_path / "no.json")
    assert tc.state_for("anything", {}).streak == 0


def test_save_pretty_prints_for_human_inspection(tmp_path: Path):
    path = tmp_path / "curves.json"
    tc = TrustCurve.load_or_empty(path)
    tc.record("mcp__gmail__send", {"to": "alice@a.com"}, approved=True)
    raw = path.read_text(encoding="utf-8")
    # Indented JSON with the tool name visible
    assert "mcp__gmail__send" in raw
    # Make sure the saved content survives roundtrip parse
    parsed = json.loads(raw)
    assert parsed["patterns"][0]["streak"] == 1


def test_render_proposal_contains_streak_and_target():
    state = PatternState(
        tool_name="mcp__gmail__send",
        fingerprint="alice@a.com",
        streak=5,
    )
    proposal = render_proposal(state)
    assert "5" in proposal.message
    assert "mcp__gmail__send" in proposal.message
    assert "alice@a.com" in proposal.message
    assert "60 秒" in proposal.message


def test_render_proposal_falls_back_for_unspecified_fingerprint():
    state = PatternState(
        tool_name="mcp__bluesky__post",
        fingerprint="*",
        streak=5,
    )
    proposal = render_proposal(state)
    assert "這個動作" in proposal.message
    # Tool name still appears
    assert "mcp__bluesky__post" in proposal.message


def test_default_propose_threshold_matches_docs():
    # docs/00 + CLAUDE.md say "連續 5 次". Pin the constant so changes are noisy.
    assert DEFAULT_PROPOSE_THRESHOLD == 5
