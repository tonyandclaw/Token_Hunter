from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.http_retry import DEFAULT_MAX_ATTEMPTS, request_with_retry


def _resp(status: int) -> httpx.Response:
    return httpx.Response(status_code=status, request=httpx.Request("GET", "http://x"))


async def test_returns_first_2xx_without_retry():
    """Happy path — call once, no retry."""
    calls = []

    async def do_request() -> httpx.Response:
        calls.append(1)
        return _resp(200)

    out = await request_with_retry(do_request, max_attempts=3, base_delay=0)
    assert out.status_code == 200
    assert len(calls) == 1


async def test_returns_4xx_without_retry():
    """4xx is the caller's fault — don't retry."""
    calls = []

    async def do_request() -> httpx.Response:
        calls.append(1)
        return _resp(403)

    out = await request_with_retry(do_request, max_attempts=3, base_delay=0)
    assert out.status_code == 403
    assert len(calls) == 1  # ONLY one call — 4xx not retried


async def test_retries_5xx_up_to_max():
    """5xx is transient — retry, but stop at max_attempts."""
    calls = []

    async def do_request() -> httpx.Response:
        calls.append(1)
        return _resp(503)

    out = await request_with_retry(do_request, max_attempts=3, base_delay=0)
    assert out.status_code == 503  # last 5xx returned to caller
    assert len(calls) == 3


async def test_retries_5xx_then_succeeds():
    """First 5xx, then 200 → should return the 200 and not call again."""
    statuses = [503, 502, 200]

    async def do_request() -> httpx.Response:
        return _resp(statuses.pop(0))

    out = await request_with_retry(do_request, max_attempts=3, base_delay=0)
    assert out.status_code == 200
    assert statuses == []  # all three consumed


async def test_retries_connect_error_up_to_max():
    """Connect errors raise; should retry then re-raise the last one."""
    calls = []

    async def do_request() -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("nope")

    with pytest.raises(httpx.ConnectError):
        await request_with_retry(do_request, max_attempts=3, base_delay=0)
    assert len(calls) == 3


async def test_does_not_retry_non_retryable_exception():
    """ValueError isn't in _RETRYABLE_EXC — propagate immediately."""
    calls = []

    async def do_request() -> httpx.Response:
        calls.append(1)
        raise ValueError("programming bug")

    with pytest.raises(ValueError):
        await request_with_retry(do_request, max_attempts=3, base_delay=0)
    assert len(calls) == 1  # ONLY one call — programming bug not retried


async def test_max_attempts_one_disables_retry():
    """max_attempts=1 → no retry at all."""
    calls = []

    async def do_request() -> httpx.Response:
        calls.append(1)
        return _resp(503)

    out = await request_with_retry(do_request, max_attempts=1, base_delay=0)
    assert out.status_code == 503
    assert len(calls) == 1


async def test_retries_mix_of_exception_and_5xx():
    """Sequence: ConnectError → 503 → 200 should succeed."""
    seq: list[Any] = [
        httpx.ConnectError("first attempt"),
        _resp(503),
        _resp(200),
    ]

    async def do_request() -> httpx.Response:
        item = seq.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    out = await request_with_retry(do_request, max_attempts=3, base_delay=0)
    assert out.status_code == 200
    assert seq == []


def test_default_max_attempts_pinned():
    """Pin the public constant so demo timing / log volume doesn't drift."""
    assert DEFAULT_MAX_ATTEMPTS == 3
