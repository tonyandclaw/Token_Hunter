from __future__ import annotations

import asyncio

from src.undo_window import (
    DEFAULT_UNDO_SECONDS,
    UndoRegistry,
    await_undo,
    decode_callback,
    encode_callback,
    render_prompt,
)


def test_encode_decode_roundtrip():
    data = encode_callback("abc12345")
    assert data == "undo:abc12345"
    assert decode_callback(data) == "abc12345"


def test_decode_rejects_bad_format():
    assert decode_callback("nope") is None
    assert decode_callback("foo:abc") is None
    assert decode_callback("undo:abc:extra") is None


def test_render_prompt_includes_label_and_seconds():
    out = render_prompt("mcp__gmail__send", {"to": "alice@acme.com", "subject": "x"}, seconds=15)
    assert "AUTO_AUDITED" in out
    assert "alice@acme.com" in out
    assert "15s" in out


def test_render_prompt_bluesky_truncates():
    out = render_prompt("mcp__bluesky__post", {"text": "x" * 200}, seconds=15)
    assert "…" in out


def test_registry_submit_creates_pending(tmp_path):
    async def go():
        reg = UndoRegistry()
        uid, future = reg.submit("mcp__gmail__send", {"to": "a@b"})
        assert reg.is_pending(uid)
        assert reg.pending_count() == 1
        # Resolve so the future doesn't hang
        reg.cancel(uid)
        assert future.result() is True

    asyncio.run(go())


def test_registry_cancel_unknown_returns_false():
    async def go():
        reg = UndoRegistry()
        assert reg.cancel("does-not-exist") is False

    asyncio.run(go())


def test_registry_cancel_removes_pending():
    async def go():
        reg = UndoRegistry()
        uid, _ = reg.submit("mcp__gmail__send", {"to": "a@b"})
        reg.cancel(uid)
        assert not reg.is_pending(uid)

    asyncio.run(go())


async def test_await_undo_times_out_returns_not_cancelled():
    """Timer expiring with no Undo press → cancelled=False → caller will Allow."""
    reg = UndoRegistry()
    uid, cancelled = await await_undo(
        reg,
        "mcp__gmail__send",
        {"to": "a@b"},
        seconds=0.05,
    )
    assert cancelled is False
    assert not reg.is_pending(uid)


async def test_await_undo_cancel_within_window():
    reg = UndoRegistry()

    async def presser():
        # Yield once so submit registers, then tap any pending undo
        await asyncio.sleep(0)
        for uid in list(reg._pending.keys()):  # noqa: SLF001 — test internals
            reg.cancel(uid)

    asyncio.create_task(presser())
    uid, cancelled = await await_undo(
        reg,
        "mcp__gmail__send",
        {"to": "a@b"},
        seconds=2.0,
    )
    assert cancelled is True
    assert not reg.is_pending(uid)


async def test_await_undo_notify_called_with_id_tool_args_prompt():
    reg = UndoRegistry()
    captured: dict[str, object] = {}

    async def notify(uid: str, tool: str, args: dict, prompt: str, seconds: int) -> None:
        captured["uid"] = uid
        captured["tool"] = tool
        captured["args"] = args
        captured["prompt"] = prompt
        captured["seconds"] = seconds
        # Auto-cancel so the await doesn't sleep the whole window
        reg.cancel(uid)

    uid, cancelled = await await_undo(
        reg,
        "mcp__bluesky__post",
        {"text": "hello"},
        seconds=5.0,
        notify=notify,
    )
    assert cancelled is True
    assert captured["uid"] == uid
    assert captured["tool"] == "mcp__bluesky__post"
    assert captured["args"] == {"text": "hello"}
    assert "hello" in str(captured["prompt"])
    assert captured["seconds"] == 5


async def test_late_cancel_after_timeout_safe():
    """Pressing Undo after the window expired must not crash and is a no-op."""
    reg = UndoRegistry()
    uid, cancelled = await await_undo(reg, "x", {}, seconds=0.01)
    assert cancelled is False
    assert reg.cancel(uid) is False


def test_default_undo_seconds_value():
    """Pin the default so demo timing doesn't drift accidentally."""
    assert DEFAULT_UNDO_SECONDS == 15
