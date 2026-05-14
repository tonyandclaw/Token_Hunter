"""tool__kimi_bulk — offload bulk drafting / batch summarization to Kimi K2.5.

Cost discipline per docs/00 §異質模型成本紀律 and CLAUDE.md §5:

Offload to Kimi when ANY of:
- expected output > 500 chars
- batch size > 3 items
- task is translation
- task is paragraph rewrite

NEVER offload:
- Tier 2/3 permission classification (must stay on Opus)
- User-facing persona / safety decisions

The actual Kimi HTTP call is `call_kimi()`; for now it stubs out with a clear
error when `KIMI_API_KEY` is missing so unit tests stay offline-safe.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

import httpx

OFFLOAD_OUTPUT_CHAR_THRESHOLD = 500
OFFLOAD_BATCH_THRESHOLD = 3

TaskKind = Literal["draft", "summarize", "translate", "rewrite", "classify", "safety"]
OFFLOADABLE_KINDS: frozenset[TaskKind] = frozenset({"draft", "summarize", "translate", "rewrite"})
OPUS_ONLY_KINDS: frozenset[TaskKind] = frozenset({"classify", "safety"})


@dataclass(frozen=True)
class RouteDecision:
    offload: bool
    reason: str


def should_offload(
    kind: TaskKind,
    *,
    expected_output_chars: int = 0,
    batch_size: int = 1,
) -> RouteDecision:
    """Decide whether to route this task to Kimi (True) or keep it on Opus (False)."""
    if kind in OPUS_ONLY_KINDS:
        return RouteDecision(False, f"task kind {kind!r} must stay on Opus")
    if kind in {"translate", "rewrite"}:
        return RouteDecision(True, f"task kind {kind!r} is always Kimi-offloaded")
    if expected_output_chars > OFFLOAD_OUTPUT_CHAR_THRESHOLD:
        return RouteDecision(
            True,
            f"expected output {expected_output_chars} chars > {OFFLOAD_OUTPUT_CHAR_THRESHOLD}",
        )
    if batch_size > OFFLOAD_BATCH_THRESHOLD:
        return RouteDecision(True, f"batch size {batch_size} > {OFFLOAD_BATCH_THRESHOLD}")
    return RouteDecision(False, "below all offload thresholds")


async def call_kimi(prompt: str, *, max_tokens: int = 2048) -> str:
    """Call Kimi K2.5 via OpenAI-compatible chat-completions API.

    Reads KIMI_API_KEY and KIMI_BASE_URL from env. Returns the assistant text.
    Raises RuntimeError if env is missing — callers should check before calling.
    """
    api_key = os.environ.get("KIMI_API_KEY")
    base_url = os.environ.get("KIMI_BASE_URL")
    if not api_key or not base_url:
        raise RuntimeError("KIMI_API_KEY / KIMI_BASE_URL not configured")

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "kimi-k2.5",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
