from __future__ import annotations

import asyncio

import pytest

from src.tier2_confirm import ConfirmRegistry, await_decision, render_prompt
from src.trust_curve import Level, TrustCurve


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


def test_render_prompt_appends_voice_match_when_corpus_supplied():
    """docs/02 Scene 1: '📈 Voice match: NN%' line below the draft."""
    msg = render_prompt(
        "mcp__gmail__send",
        {"to": "a@b", "body": "週五交付,沒問題。再聯絡。"},
        voice_corpus="週五交付。明白。",
    )
    assert "📈 Voice match:" in msg
    assert "句長" in msg
    assert "詞彙" in msg
    assert "結構" in msg
    assert "上限 80%" in msg


def test_render_prompt_skips_voice_when_corpus_empty():
    """Empty corpus → no voice line at all (don't show a 0% that would scare the user)."""
    msg = render_prompt(
        "mcp__gmail__send",
        {"to": "a@b", "body": "test"},
        voice_corpus="",
    )
    assert "Voice match" not in msg


def test_render_prompt_skips_voice_when_no_draft():
    """No draft text in args → no voice line, even with a corpus."""
    msg = render_prompt(
        "mcp__gmail__bulk_delete",
        {"count": 5},
        voice_corpus="some user writing",
    )
    assert "Voice match" not in msg


# --- First-contact recipient warning ---


def test_render_prompt_prepends_first_contact_banner_for_new_recipient():
    """docs/03 §不做: stranger recipients get an extra ⚠️ warning."""
    from src.recipient_tracker import KnownRecipients

    kr = KnownRecipients()  # empty — every recipient is new
    msg = render_prompt(
        "mcp__gmail__send",
        {"to": "stranger@unknown.io", "subject": "x", "body": "hi"},
        known_recipients=kr,
    )
    assert msg.startswith("⚠️ 第一次寄信給 stranger@unknown.io")
    # Standard confirm prompt body should still follow
    assert "mcp__gmail__send" in msg
    assert "stranger@unknown.io" in msg


def test_render_prompt_no_banner_for_known_recipient():
    """A recipient already in the set → no first-contact banner."""
    from src.recipient_tracker import KnownRecipients

    kr = KnownRecipients()
    kr.mark_seen("alice@acme.com")
    msg = render_prompt(
        "mcp__gmail__send",
        {"to": "alice@acme.com", "subject": "x", "body": "hi"},
        known_recipients=kr,
    )
    assert not msg.startswith("⚠️ 第一次寄信給")


def test_render_prompt_no_banner_when_tracker_omitted():
    """No tracker passed → no banner, no error."""
    msg = render_prompt(
        "mcp__gmail__send",
        {"to": "stranger@unknown.io", "subject": "x", "body": "hi"},
    )
    assert "第一次寄信給" not in msg


def test_render_prompt_no_banner_for_non_gmail_tools():
    """Bluesky posts / memory writes don't have recipient addresses to check."""
    from src.recipient_tracker import KnownRecipients

    kr = KnownRecipients()
    msg = render_prompt(
        "mcp__bluesky__post",
        {"text": "hello world"},
        known_recipients=kr,
    )
    assert "第一次寄信給" not in msg


async def test_await_decision_marks_recipient_seen_on_approval(tmp_path):
    """Approval of a gmail send should add the recipient to the known set."""
    from src.recipient_tracker import KnownRecipients

    reg = ConfirmRegistry()
    kr = KnownRecipients()

    async def resolver():
        await asyncio.sleep(0)
        for cid in list(reg._pending.keys()):  # noqa: SLF001
            reg.resolve(cid, approved=True)

    asyncio.create_task(resolver())
    await await_decision(
        reg,
        "mcp__gmail__send",
        {"to": "newperson@x.io"},
        known_recipients=kr,
    )
    assert kr.is_known("newperson@x.io")


async def test_await_decision_does_not_mark_seen_on_rejection(tmp_path):
    """A rejected send must NOT make the recipient 'known'."""
    from src.recipient_tracker import KnownRecipients

    reg = ConfirmRegistry()
    kr = KnownRecipients()

    async def resolver():
        await asyncio.sleep(0)
        for cid in list(reg._pending.keys()):  # noqa: SLF001
            reg.resolve(cid, approved=False)

    asyncio.create_task(resolver())
    await await_decision(
        reg,
        "mcp__gmail__send",
        {"to": "newperson@x.io"},
        known_recipients=kr,
    )
    assert not kr.is_known("newperson@x.io")


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


async def test_await_decision_records_approval_in_trust_curve(tmp_path):
    reg = ConfirmRegistry()
    curve = TrustCurve(path=tmp_path / "curves.json")

    async def resolver():
        await asyncio.sleep(0)
        for cid in list(reg._pending.keys()):  # noqa: SLF001
            reg.resolve(cid, approved=True)

    asyncio.create_task(resolver())
    await await_decision(
        reg,
        "mcp__gmail__send",
        {"to": "alice@acme.com", "subject": "x", "body": "y"},
        trust_curve=curve,
    )
    state = curve.status("mcp__gmail__send", {"to": "alice@acme.com"})
    assert state.total_confirms == 1
    assert state.consecutive_confirms == 1
    assert state.level is Level.MANUAL


async def test_await_decision_fires_on_eligible_at_threshold(tmp_path):
    """After ESCALATION_THRESHOLD consecutive approvals, on_eligible should fire once."""
    from src.trust_curve import ESCALATION_THRESHOLD

    reg = ConfirmRegistry()
    curve = TrustCurve(path=tmp_path / "curves.json")
    captured: list[tuple[str, dict, int]] = []

    async def on_eligible(tool, args, state):
        captured.append((tool, dict(args), state.consecutive_confirms))

    args = {"to": "alice@acme.com", "subject": "x", "body": "y"}
    for _ in range(ESCALATION_THRESHOLD):
        # Auto-resolve every confirm as approved
        async def resolver():
            await asyncio.sleep(0)
            for cid in list(reg._pending.keys()):  # noqa: SLF001
                reg.resolve(cid, approved=True)

        asyncio.create_task(resolver())
        await await_decision(
            reg,
            "mcp__gmail__send",
            args,
            trust_curve=curve,
            on_eligible=on_eligible,
        )

    # on_eligible fires exactly once — on the Nth confirm that pushed us to threshold.
    assert len(captured) == 1
    captured_tool, captured_args, captured_streak = captured[0]
    assert captured_tool == "mcp__gmail__send"
    assert captured_args["to"] == "alice@acme.com"
    assert captured_streak == ESCALATION_THRESHOLD


async def test_await_decision_does_not_fire_on_eligible_on_rejection(tmp_path):
    reg = ConfirmRegistry()
    curve = TrustCurve(path=tmp_path / "curves.json")
    fired = []

    async def on_eligible(tool, args, state):
        fired.append(state)

    args = {"to": "alice@acme.com"}
    # 4 approved + 1 rejected = streak resets to 0 before threshold
    for approved in [True, True, True, True, False]:

        async def resolver(approved=approved):
            await asyncio.sleep(0)
            for cid in list(reg._pending.keys()):  # noqa: SLF001
                reg.resolve(cid, approved=approved)

        asyncio.create_task(resolver())
        await await_decision(
            reg, "mcp__gmail__send", args, trust_curve=curve, on_eligible=on_eligible
        )

    assert fired == []


async def test_await_decision_records_timeout_as_rejection(tmp_path):
    reg = ConfirmRegistry()
    curve = TrustCurve(path=tmp_path / "curves.json")
    await await_decision(
        reg,
        "mcp__gmail__send",
        {"to": "alice@acme.com"},
        timeout_seconds=0.01,
        trust_curve=curve,
    )
    state = curve.status("mcp__gmail__send", {"to": "alice@acme.com"})
    assert state.total_rejects == 1
    assert state.consecutive_confirms == 0


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
