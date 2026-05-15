from __future__ import annotations

import pytest

from src.escalation import (
    CALLBACK_PREFIX,
    Action,
    EscalationRegistry,
    apply_action,
    decode_callback,
    encode_callback,
    pattern_label,
    render_proposal,
)
from src.trust_curve import ESCALATION_THRESHOLD, Level, TrustCurve


def test_pattern_label_gmail_with_recipient():
    assert pattern_label("mcp__gmail__send", {"to": "alice@acme.com"}) == "寫信給 alice@acme.com"
    assert pattern_label("mcp__gmail__reply", {"to": "bob@x.io"}) == "寫信給 bob@x.io"


def test_pattern_label_gmail_without_recipient():
    assert pattern_label("mcp__gmail__send", {}) == "寄信"


def test_pattern_label_learning_with_category():
    assert (
        pattern_label("mcp__memory__write_learning", {"category": "ACME 交期"})
        == "記下「ACME 交期」類規則"
    )


def test_pattern_label_unknown_tool_falls_back_to_tool_name():
    assert pattern_label("some__weird_tool", {}) == "some__weird_tool"


def test_render_proposal_includes_streak_and_label(tmp_path):
    curve = TrustCurve(path=tmp_path / "c.json")
    args = {"to": "alice@acme.com"}
    for _ in range(ESCALATION_THRESHOLD):
        curve.record("mcp__gmail__send", args, approved=True)
    state = curve.status("mcp__gmail__send", args)
    text = render_proposal(state, "mcp__gmail__send", args)
    assert "5 次" in text
    assert "寫信給 alice@acme.com" in text


def test_encode_decode_callback_roundtrip():
    for action in Action:
        data = encode_callback("abc12345", action)
        assert data.startswith(f"{CALLBACK_PREFIX}:abc12345:")
        decoded = decode_callback(data)
        assert decoded is not None
        eid, decoded_action = decoded
        assert eid == "abc12345"
        assert decoded_action is action


def test_decode_callback_rejects_bad_format():
    assert decode_callback("nope") is None
    assert decode_callback("esc:abc") is None  # missing action
    assert decode_callback("foo:abc:yes") is None  # wrong prefix
    assert decode_callback("esc:abc:bogus") is None  # bad action value


def test_registry_submit_and_pop():
    reg = EscalationRegistry()
    pending = reg.submit("mcp__gmail__send", {"to": "alice@acme.com"}, streak=5)
    assert reg.is_pending(pending.eid)
    assert reg.pending_count() == 1

    popped = reg.pop(pending.eid)
    assert popped is not None
    assert popped.tool == "mcp__gmail__send"
    assert popped.args == {"to": "alice@acme.com"}
    assert popped.streak == 5
    assert not reg.is_pending(pending.eid)


def test_registry_pop_unknown_returns_none():
    reg = EscalationRegistry()
    assert reg.pop("does-not-exist") is None


def test_apply_action_escalate(tmp_path):
    curve = TrustCurve(path=tmp_path / "c.json")
    args = {"to": "alice@acme.com"}
    for _ in range(ESCALATION_THRESHOLD):
        curve.record("mcp__gmail__send", args, approved=True)

    reg = EscalationRegistry()
    pending = reg.submit("mcp__gmail__send", args, streak=ESCALATION_THRESHOLD)
    out = apply_action(curve, pending, Action.ESCALATE)
    assert "Trust upgraded" in out
    assert curve.status("mcp__gmail__send", args).level is Level.AUTO_AUDITED


def test_apply_action_defer_resets_streak(tmp_path):
    curve = TrustCurve(path=tmp_path / "c.json")
    args = {"to": "alice@acme.com"}
    for _ in range(ESCALATION_THRESHOLD):
        curve.record("mcp__gmail__send", args, approved=True)

    reg = EscalationRegistry()
    pending = reg.submit("mcp__gmail__send", args, streak=ESCALATION_THRESHOLD)
    out = apply_action(curve, pending, Action.DEFER)
    assert "繼續每次都問" in out
    state = curve.status("mcp__gmail__send", args)
    assert state.level is Level.MANUAL
    assert state.consecutive_confirms == 0
    assert state.total_confirms == ESCALATION_THRESHOLD  # history preserved


def test_apply_action_lock(tmp_path):
    curve = TrustCurve(path=tmp_path / "c.json")
    args = {"to": "alice@acme.com"}
    for _ in range(ESCALATION_THRESHOLD):
        curve.record("mcp__gmail__send", args, approved=True)

    reg = EscalationRegistry()
    pending = reg.submit("mcp__gmail__send", args, streak=ESCALATION_THRESHOLD)
    out = apply_action(curve, pending, Action.LOCK)
    assert "always-ask" in out
    assert curve.status("mcp__gmail__send", args).is_locked


def test_apply_action_escalate_refuses_locked(tmp_path):
    curve = TrustCurve(path=tmp_path / "c.json")
    args = {"to": "alice@acme.com"}
    curve.lock_always_ask("mcp__gmail__send", args)

    reg = EscalationRegistry()
    pending = reg.submit("mcp__gmail__send", args, streak=0)
    with pytest.raises(ValueError):
        apply_action(curve, pending, Action.ESCALATE)
