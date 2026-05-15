from __future__ import annotations

from src.absence_feedback import (
    CALLBACK_PREFIX,
    FeedbackAction,
    FeedbackRegistry,
    apply_feedback,
    decode_callback,
    encode_callback,
)
from src.trust_curve import Level, TrustCurve


def test_encode_decode_roundtrip():
    for action in FeedbackAction:
        data = encode_callback("abc12345", action)
        assert data.startswith(f"{CALLBACK_PREFIX}:abc12345:")
        decoded = decode_callback(data)
        assert decoded is not None
        fid, decoded_action = decoded
        assert fid == "abc12345"
        assert decoded_action is action


def test_decode_rejects_bad_format():
    assert decode_callback("nope") is None
    assert decode_callback("afb:abc") is None
    assert decode_callback("foo:abc:ok") is None
    assert decode_callback("afb:abc:bogus") is None


def test_registry_submit_and_pop():
    reg = FeedbackRegistry()
    pf = reg.submit("mcp__gmail__send", {"to": "alice@acme.com"}, label="寫信給 alice@acme.com")
    assert reg.is_pending(pf.fid)
    assert reg.pending_count() == 1

    popped = reg.pop(pf.fid)
    assert popped is not None
    assert popped.tool == "mcp__gmail__send"
    assert popped.label == "寫信給 alice@acme.com"
    assert not reg.is_pending(pf.fid)


def test_registry_pop_unknown_returns_none():
    reg = FeedbackRegistry()
    assert reg.pop("does-not-exist") is None


def test_apply_feedback_ok_is_noop(tmp_path):
    curve = TrustCurve(path=tmp_path / "c.json")
    # Pre-load some state — apply OK should not touch it
    curve.escalate("mcp__gmail__send", {"to": "a@b"}, new_level=Level.AUTO_AUDITED)
    reg = FeedbackRegistry()
    pf = reg.submit("mcp__gmail__send", {"to": "a@b"}, label="x")
    out = apply_feedback(curve, pf, FeedbackAction.OK)
    assert "trust curve 不變動" in out
    assert curve.status("mcp__gmail__send", {"to": "a@b"}).level is Level.AUTO_AUDITED


def test_apply_feedback_lock_drops_pattern_to_always_ask(tmp_path):
    curve = TrustCurve(path=tmp_path / "c.json")
    curve.escalate("mcp__gmail__send", {"to": "a@b"}, new_level=Level.AUTO_AUDITED)
    reg = FeedbackRegistry()
    pf = reg.submit("mcp__gmail__send", {"to": "a@b"}, label="x")
    out = apply_feedback(curve, pf, FeedbackAction.LOCK)
    assert "ALWAYS_ASK" in out
    assert curve.status("mcp__gmail__send", {"to": "a@b"}).is_locked


def test_args_are_copied_in_submit():
    reg = FeedbackRegistry()
    args = {"to": "alice@acme.com"}
    pf = reg.submit("mcp__gmail__send", args, label="x")
    args["to"] = "evil@attacker.example"
    assert pf.args["to"] == "alice@acme.com"
