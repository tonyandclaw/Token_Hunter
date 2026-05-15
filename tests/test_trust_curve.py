from __future__ import annotations

import json

import pytest

from src.trust_curve import (
    ESCALATION_THRESHOLD,
    WILDCARD_KEY,
    Level,
    PatternState,
    TrustCurve,
    extract_key,
)


def _curve(tmp_path) -> TrustCurve:
    return TrustCurve(path=tmp_path / "curves.json")


def test_extract_key_gmail_uses_recipient():
    assert extract_key("mcp__gmail__send", {"to": "Alice@ACME.com"}) == "to=alice@acme.com"
    assert extract_key("mcp__gmail__reply", {"to": "bob@x.io"}) == "to=bob@x.io"


def test_extract_key_gmail_no_to_returns_none():
    assert extract_key("mcp__gmail__send", {}) is None
    assert extract_key("mcp__gmail__send", {"to": "   "}) is None


def test_extract_key_learning_uses_category():
    assert (
        extract_key("mcp__memory__write_learning", {"category": "ACME 交期"})
        == "category=ACME 交期"
    )
    assert extract_key("mcp__memory__write_learning", {"category": ""}) is None


def test_extract_key_unstable_tools_return_none():
    """Bluesky posts and user-profile writes are too varied to escalate as a group."""
    assert extract_key("mcp__bluesky__post", {"text": "hi"}) is None
    assert extract_key("mcp__memory__write_user_profile", {"note": "I like tea"}) is None
    assert extract_key("some__brand_new_tool", {}) is None


def test_record_approved_increments_streak(tmp_path):
    c = _curve(tmp_path)
    args = {"to": "alice@acme.com"}
    s = c.record("mcp__gmail__send", args, approved=True)
    assert s.consecutive_confirms == 1
    assert s.total_confirms == 1
    assert s.level is Level.MANUAL
    c.record("mcp__gmail__send", args, approved=True)
    s = c.record("mcp__gmail__send", args, approved=True)
    assert s.consecutive_confirms == 3
    assert s.total_confirms == 3
    assert s.total_rejects == 0


def test_record_rejected_resets_streak(tmp_path):
    c = _curve(tmp_path)
    args = {"to": "alice@acme.com"}
    for _ in range(3):
        c.record("mcp__gmail__send", args, approved=True)
    s = c.record("mcp__gmail__send", args, approved=False)
    assert s.consecutive_confirms == 0
    assert s.total_rejects == 1
    assert s.total_confirms == 3


def test_eligibility_fires_at_threshold(tmp_path):
    c = _curve(tmp_path)
    args = {"to": "alice@acme.com"}
    for i in range(ESCALATION_THRESHOLD - 1):
        s = c.record("mcp__gmail__send", args, approved=True)
        assert not s.is_eligible_for_escalation, f"should not be eligible at {i + 1}"
    s = c.record("mcp__gmail__send", args, approved=True)
    assert s.is_eligible_for_escalation
    assert s.consecutive_confirms == ESCALATION_THRESHOLD


def test_eligibility_does_not_fire_for_wildcard_key(tmp_path):
    c = _curve(tmp_path)
    # bluesky_post has no extractable key → all events fall into WILDCARD_KEY
    for _ in range(ESCALATION_THRESHOLD + 5):
        s = c.record("mcp__bluesky__post", {"text": "hi"}, approved=True)
    assert s.key == WILDCARD_KEY
    assert not s.is_eligible_for_escalation


def test_eligibility_does_not_fire_at_higher_levels(tmp_path):
    c = _curve(tmp_path)
    args = {"to": "alice@acme.com"}
    for _ in range(ESCALATION_THRESHOLD):
        c.record("mcp__gmail__send", args, approved=True)
    c.escalate("mcp__gmail__send", args, new_level=Level.AUTO_AUDITED)
    # Now keep confirming — eligibility shouldn't re-fire because we're past MANUAL
    for _ in range(ESCALATION_THRESHOLD):
        s = c.record("mcp__gmail__send", args, approved=True)
    assert s.level is Level.AUTO_AUDITED
    assert not s.is_eligible_for_escalation


def test_escalate_promotes_one_step(tmp_path):
    c = _curve(tmp_path)
    args = {"to": "alice@acme.com"}
    for _ in range(ESCALATION_THRESHOLD):
        c.record("mcp__gmail__send", args, approved=True)
    s = c.escalate("mcp__gmail__send", args)
    assert s.level is Level.AUTO_AUDITED
    assert s.consecutive_confirms == 0  # restart at new level


def test_escalate_refuses_to_demote(tmp_path):
    c = _curve(tmp_path)
    args = {"to": "alice@acme.com"}
    c.escalate("mcp__gmail__send", args, new_level=Level.AUTO_AUDITED)
    with pytest.raises(ValueError):
        c.escalate("mcp__gmail__send", args, new_level=Level.MANUAL)


def test_lock_always_ask_is_sticky(tmp_path):
    c = _curve(tmp_path)
    args = {"to": "alice@acme.com"}
    c.lock_always_ask("mcp__gmail__send", args)
    s = c.status("mcp__gmail__send", args)
    assert s.is_locked
    assert s.level is Level.ALWAYS_ASK
    # Subsequent confirms tally but never count toward the streak
    for _ in range(ESCALATION_THRESHOLD + 3):
        s = c.record("mcp__gmail__send", args, approved=True)
    assert s.is_locked
    assert s.consecutive_confirms == 0
    assert s.total_confirms == ESCALATION_THRESHOLD + 3
    assert not s.is_eligible_for_escalation


def test_escalate_refuses_when_locked(tmp_path):
    c = _curve(tmp_path)
    args = {"to": "alice@acme.com"}
    c.lock_always_ask("mcp__gmail__send", args)
    with pytest.raises(ValueError):
        c.escalate("mcp__gmail__send", args, new_level=Level.AUTO_AUDITED)


def test_defer_resets_streak_only(tmp_path):
    c = _curve(tmp_path)
    args = {"to": "alice@acme.com"}
    for _ in range(ESCALATION_THRESHOLD):
        c.record("mcp__gmail__send", args, approved=True)
    s = c.defer("mcp__gmail__send", args)
    assert s.level is Level.MANUAL
    assert s.consecutive_confirms == 0
    assert s.total_confirms == ESCALATION_THRESHOLD  # historical count preserved


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "curves.json"
    c1 = TrustCurve(path=path)
    args = {"to": "alice@acme.com"}
    for _ in range(3):
        c1.record("mcp__gmail__send", args, approved=True)
    c1.lock_always_ask("mcp__bluesky__post", {"text": "anything"})
    # Don't rely on autosave; explicit save for clarity
    c1.save()
    assert path.exists()

    c2 = TrustCurve(path=path)
    c2.load()
    gm = c2.status("mcp__gmail__send", args)
    assert gm.total_confirms == 3
    assert gm.consecutive_confirms == 3
    assert gm.level is Level.MANUAL
    bs = c2.status("mcp__bluesky__post", {"text": "x"})
    assert bs.is_locked


def test_save_load_is_human_readable_json(tmp_path):
    path = tmp_path / "curves.json"
    c = TrustCurve(path=path)
    c.record("mcp__gmail__send", {"to": "alice@acme.com"}, approved=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    # One pattern id, with all expected fields
    assert "mcp__gmail__send|to=alice@acme.com" in payload
    row = payload["mcp__gmail__send|to=alice@acme.com"]
    assert row["level"] == int(Level.MANUAL)
    assert row["total_confirms"] == 1


def test_status_does_not_mutate(tmp_path):
    c = _curve(tmp_path)
    s = c.status("mcp__gmail__send", {"to": "alice@acme.com"})
    assert s.total_confirms == 0
    # Status was called twice; counts shouldn't move
    s = c.status("mcp__gmail__send", {"to": "alice@acme.com"})
    assert s.total_confirms == 0


def test_pattern_state_from_dict_legacy_payload():
    """Older curves.json shapes without all fields should still load with defaults."""
    s = PatternState.from_dict({"tool": "mcp__gmail__send", "key": "to=alice@acme.com", "level": 1})
    assert s.consecutive_confirms == 0
    assert s.total_confirms == 0
    assert s.level is Level.MANUAL


def test_summary_renders_known_state(tmp_path):
    c = _curve(tmp_path)
    args = {"to": "alice@acme.com"}
    for _ in range(2):
        c.record("mcp__gmail__send", args, approved=True)
    out = c.summary()
    assert "Trust Dashboard" in out
    assert "to=alice@acme.com" in out
    assert "2✅" in out
    assert "streak 2/5" in out
    # The 2/5 progress bar: 2 filled, 3 empty (rounded)
    assert "●●○○○" in out


def test_summary_shows_level_name_above_manual(tmp_path):
    c = _curve(tmp_path)
    args = {"to": "alice@acme.com"}
    c.escalate("mcp__gmail__send", args, new_level=Level.AUTO_AUDITED)
    out = c.summary()
    # No progress bar past MANUAL — replaced by the level name
    assert "AUTO_AUDITED" in out
    assert "streak" not in out


def test_summary_empty(tmp_path):
    c = _curve(tmp_path)
    assert "尚無 Trust 紀錄" in c.summary()
