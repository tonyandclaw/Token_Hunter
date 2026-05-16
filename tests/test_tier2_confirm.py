from __future__ import annotations

import asyncio

import pytest

from src.tier2_confirm import ConfirmRegistry, await_decision, render_prompt


def test_render_prompt_email_with_to_and_body():
    msg = render_prompt(
        "mcp__gmail__send",
        {"to": "alice@acme.com", "subject": "re: order", "body": "週五交付,沒問題。"},
    )
    assert msg.startswith("我準備執行:mcp__gmail__send")
    assert "收件人 alice@acme.com" in msg
    assert "週五交付,沒問題。" in msg
    assert msg.endswith("確認? [Yes / No]")


def test_render_prompt_truncates_long_drafts():
    long = "x" * 1000
    msg = render_prompt("mcp__bluesky__post", {"text": long})
    assert "… [truncated]" in msg
    # body is truncated to 600 + ellipsis marker
    assert msg.count("x") == 600


def test_render_prompt_unknown_fields_falls_back():
    msg = render_prompt("custom__tool", {})
    assert "(僅 agent 內部" in msg
    assert "(無草稿內容)" in msg


def test_render_prompt_includes_voice_match_when_corpus_provided():
    msg = render_prompt(
        "mcp__gmail__send",
        {"to": "alice@a.com", "body": "週五交付沒問題。明天確認規格。"},
        user_corpus="週五交付沒問題。明天對規格。後天上線。",
    )
    assert "voice match:" in msg
    assert "cap 80%" in msg


def test_render_prompt_skips_voice_match_when_no_corpus():
    msg = render_prompt(
        "mcp__gmail__send",
        {"to": "alice@a.com", "body": "anything"},
    )
    assert "voice match" not in msg


def test_render_prompt_skips_voice_match_when_no_draft_text():
    msg = render_prompt(
        "mcp__gmail__bulk_delete",
        {"count": 5},
        user_corpus="x x x",
    )
    assert "voice match" not in msg


async def test_submit_then_resolve_resolves_future():
    reg = ConfirmRegistry()
    cid, future = reg.submit("mcp__gmail__send", {"to": "a@b"})
    assert reg.is_pending(cid)
    assert reg.resolve(cid, approved=True) is True
    assert future.done()
    assert future.result() is True
    assert not reg.is_pending(cid)


async def test_resolve_unknown_id_returns_false():
    reg = ConfirmRegistry()
    assert reg.resolve("does-not-exist", approved=True) is False


async def test_await_decision_approves_when_resolved():
    reg = ConfirmRegistry()

    async def resolver_after_brief_delay():
        # Yield once so submit registers first, then resolve any pending id.
        await asyncio.sleep(0)
        for cid in list(reg._pending.keys()):  # noqa: SLF001 — test-only access
            reg.resolve(cid, approved=True)

    asyncio.create_task(resolver_after_brief_delay())
    cid, approved = await await_decision(reg, "mcp__gmail__send", {"to": "a@b"})
    assert approved is True
    assert not reg.is_pending(cid)


async def test_await_decision_denies_when_resolved_no():
    reg = ConfirmRegistry()

    async def resolver():
        await asyncio.sleep(0)
        for cid in list(reg._pending.keys()):  # noqa: SLF001
            reg.resolve(cid, approved=False)

    asyncio.create_task(resolver())
    cid, approved = await await_decision(reg, "mcp__gmail__send", {"to": "a@b"})
    assert approved is False
    assert not reg.is_pending(cid)


async def test_await_decision_times_out_to_deny():
    reg = ConfirmRegistry()
    cid, approved = await await_decision(
        reg,
        "mcp__gmail__send",
        {"to": "a@b"},
        timeout_seconds=0.05,
    )
    assert approved is False
    assert not reg.is_pending(cid)  # registry entry cleaned up


async def test_await_decision_calls_on_submit_with_id_and_rendered_prompt():
    reg = ConfirmRegistry()
    captured: dict[str, str] = {}

    async def on_submit(cid: str, prompt: str) -> None:
        captured["cid"] = cid
        captured["prompt"] = prompt
        # Auto-approve to terminate the await
        reg.resolve(cid, approved=True)

    confirm_id, approved = await await_decision(
        reg,
        "mcp__bluesky__post",
        {"text": "hello world"},
        on_submit=on_submit,
    )
    assert approved is True
    assert captured["cid"] == confirm_id
    assert "mcp__bluesky__post" in captured["prompt"]
    assert "hello world" in captured["prompt"]


async def test_resolve_after_timeout_is_safe():
    """Late button-tap (after timeout) doesn't crash and is reported as no-op."""
    reg = ConfirmRegistry()
    cid, approved = await await_decision(reg, "x", {}, timeout_seconds=0.01)
    assert approved is False
    # Now simulate the user tapping the button after timeout
    assert reg.resolve(cid, approved=True) is False


@pytest.mark.parametrize("count", [1, 5])
async def test_multiple_pending_confirms_independent(count: int):
    reg = ConfirmRegistry()
    submitted: list[tuple[str, asyncio.Future[bool]]] = [
        reg.submit(f"tool_{i}", {"i": i}) for i in range(count)
    ]
    assert reg.pending_count() == count

    # Resolve a single one and ensure others stay pending
    reg.resolve(submitted[0][0], approved=True)
    assert submitted[0][1].result() is True
    assert reg.pending_count() == count - 1
    for cid, fut in submitted[1:]:
        assert reg.is_pending(cid)
        assert not fut.done()
