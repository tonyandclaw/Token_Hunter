"""Minimal async-httpx retry-with-backoff wrapper.

Why hand-rolled instead of `tenacity` or `httpx-retries`:
  - one fewer dep on the production wheel
  - 50 lines of code vs a heavyweight library
  - we only need to retry one shape (httpx.Response from an awaited call)

Called by:
  - src/chat/teams.py:_TokenCache.get        (Microsoft login endpoint)
  - src/chat/teams.py:TeamsAdapter._post_activity / edit_message
                                              (Bot Framework outbound)

Retries on:
  - connect errors (httpx.ConnectError, httpx.ReadTimeout, httpx.PoolTimeout,
    httpx.ConnectTimeout, httpx.WriteError, httpx.RemoteProtocolError)
  - response status >= 500 (transient server-side failure)

Does NOT retry on:
  - 4xx (client error — caller's fault, retrying won't help)
  - non-httpx exceptions (let them propagate; they're programming bugs)
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

log = logging.getLogger("fushou.http_retry")

T = TypeVar("T")

# Retry the request on these — all signal "try again, the server might recover".
_RETRYABLE_EXC: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteError,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 0.5  # seconds; doubled each retry, with jitter
DEFAULT_MAX_DELAY = 8.0


async def request_with_retry(
    do_request: Callable[[], Awaitable[httpx.Response]],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    label: str = "http",
) -> httpx.Response:
    """Run `do_request()` up to `max_attempts` times with exponential backoff + jitter.

    Returns the first response that's either 2xx/3xx/4xx (any non-5xx) OR the
    last response received after exhausting attempts. Raises the last
    `_RETRYABLE_EXC` exception if every attempt raised.

    `do_request` is a zero-arg callable that returns a coroutine — so each
    retry runs a fresh request. The caller owns the httpx.AsyncClient.

    `label` is purely for log output ("token-fetch", "send-activity", etc.)
    so operators can grep the source of a retry storm.
    """
    last_exc: BaseException | None = None
    last_response: httpx.Response | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = await do_request()
        except _RETRYABLE_EXC as exc:
            last_exc = exc
            last_response = None
            log.warning(
                "%s retryable error on attempt %d/%d: %s",
                label,
                attempt,
                max_attempts,
                exc,
            )
            if attempt == max_attempts:
                raise
        else:
            last_exc = None
            last_response = response
            if response.status_code < 500:
                return response  # 2xx/3xx/4xx — let the caller decide
            log.warning(
                "%s 5xx on attempt %d/%d: status=%d",
                label,
                attempt,
                max_attempts,
                response.status_code,
            )
            if attempt == max_attempts:
                return response  # exhausted; return the 5xx for the caller to handle

        # Exponential backoff with jitter: 0.5, 1.0, 2.0, ... capped at max_delay
        # Jitter is +-25% to spread thundering herds.
        delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
        jitter = delay * 0.25 * (random.random() * 2 - 1)
        await asyncio.sleep(delay + jitter)

    # Unreachable in practice — the loop always either returns or raises.
    # Belt-and-braces for static analyzers.
    if last_response is not None:
        return last_response
    assert last_exc is not None
    raise last_exc
