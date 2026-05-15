from __future__ import annotations

from src.why_button import (
    CALLBACK_PREFIX,
    WhyRegistry,
    decode_callback,
    encode_callback,
)


def test_encode_decode_roundtrip():
    data = encode_callback("abc12345")
    assert data == f"{CALLBACK_PREFIX}:abc12345"
    assert decode_callback(data) == "abc12345"


def test_decode_rejects_bad_format():
    assert decode_callback("nope") is None
    assert decode_callback("why:abc:extra") is None
    assert decode_callback("foo:abc") is None


def test_submit_creates_context():
    reg = WhyRegistry()
    ctx = reg.submit("mcp__gmail__send", {"to": "alice@acme.com"}, tier=2)
    assert reg.has(ctx.wid)
    assert reg.pending_count() == 1
    assert ctx.tool == "mcp__gmail__send"
    assert ctx.args == {"to": "alice@acme.com"}
    assert ctx.tier == 2


def test_get_does_not_pop():
    """Re-reading Why must work — registry.get() returns without mutation."""
    reg = WhyRegistry()
    ctx = reg.submit("mcp__gmail__send", {"to": "a@b"})
    assert reg.get(ctx.wid) is ctx
    assert reg.get(ctx.wid) is ctx  # second call also returns it
    assert reg.has(ctx.wid)
    assert reg.pending_count() == 1


def test_get_unknown_returns_none():
    reg = WhyRegistry()
    assert reg.get("does-not-exist") is None


def test_fifo_eviction_at_cap():
    reg = WhyRegistry(max_items=3)
    a = reg.submit("t1", {})
    b = reg.submit("t2", {})
    c = reg.submit("t3", {})
    assert reg.pending_count() == 3
    # Adding a 4th evicts the oldest (a)
    d = reg.submit("t4", {})
    assert reg.pending_count() == 3
    assert not reg.has(a.wid)
    assert reg.has(b.wid)
    assert reg.has(c.wid)
    assert reg.has(d.wid)


def test_args_are_copied_not_referenced():
    """Mutating the original args dict must not change the stored snapshot."""
    reg = WhyRegistry()
    args = {"to": "alice@acme.com"}
    ctx = reg.submit("mcp__gmail__send", args)
    args["to"] = "evil@attacker.example"
    assert ctx.args["to"] == "alice@acme.com"
