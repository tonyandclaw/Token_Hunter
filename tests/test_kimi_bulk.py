from __future__ import annotations

import pytest

from src.tools.kimi_bulk import call_kimi, should_offload


def test_classify_stays_on_opus():
    d = should_offload("classify")
    assert not d.offload


def test_safety_stays_on_opus_even_if_long():
    d = should_offload("safety", expected_output_chars=10_000)
    assert not d.offload


def test_translate_always_offloads():
    assert should_offload("translate").offload


def test_rewrite_always_offloads():
    assert should_offload("rewrite").offload


def test_draft_offloads_when_long():
    short = should_offload("draft", expected_output_chars=200)
    long = should_offload("draft", expected_output_chars=600)
    assert not short.offload
    assert long.offload


def test_summarize_offloads_when_batch_large():
    small = should_offload("summarize", batch_size=2)
    big = should_offload("summarize", batch_size=4)
    assert not small.offload
    assert big.offload


async def test_call_kimi_errors_without_env(monkeypatch):
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="KIMI_API_KEY"):
        await call_kimi("hi")
