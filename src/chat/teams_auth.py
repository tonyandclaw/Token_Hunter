"""Bot Framework inbound-JWT verification for the Teams adapter.

Every POST to `/api/messages` from Microsoft carries an `Authorization: Bearer
<JWT>` header signed by Microsoft's Bot Framework certs. Without verifying it,
the bot accepts arbitrary HTTP from anywhere — anyone who guesses the URL can
fabricate activities, including impersonating other users' AAD IDs to bypass
the ALLOWED_USERS gate. This module verifies:

  1. Signature against Microsoft's published JWKS (rotated keys, cached with TTL)
  2. Issuer claim equals `https://api.botframework.com`
  3. Audience claim equals our `MicrosoftAppId` (TEAMS_APP_ID)
  4. Token not expired (`exp` claim)
  5. `serviceurl` claim matches the activity's serviceUrl, when both are present

We use the PyJWT library's standard validators — never roll our own crypto
per the awesome-secure-defaults guidance.

References (operator-only — keep these in CLAUDE.md not in code):
  - https://learn.microsoft.com/en-us/azure/bot-service/rest-api/bot-framework-rest-connector-authentication

Called by: `TeamsAdapter.handle_request` (in src/chat/teams.py), which is
in turn called by the aiohttp webhook handler in `TeamsAdapter.run`.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

log = logging.getLogger("fushou.chat.teams_auth")

# Public-channels metadata endpoint. Skills / emulator use different URLs;
# pin to the public channel and document it.
DEFAULT_METADATA_URL = "https://login.botframework.com/v1/.well-known/openidconfiguration"
EXPECTED_ISSUER = "https://api.botframework.com"

# JWKS TTL — Microsoft rotates keys; refresh daily.
DEFAULT_JWKS_TTL_SECONDS = 24 * 60 * 60


class OpenIdMetadataCache:
    """Fetches and caches Microsoft's OpenID config + JWKS.

    We re-fetch when the cache is older than `ttl_seconds` OR when we see a
    `kid` we don't recognise (Microsoft rotates keys). Thread-safety isn't
    required — only the asyncio event loop in `TeamsAdapter.run` touches it.
    """

    def __init__(
        self,
        metadata_url: str = DEFAULT_METADATA_URL,
        *,
        ttl_seconds: int = DEFAULT_JWKS_TTL_SECONDS,
        jwks_client_factory: Any = None,
    ) -> None:
        self._metadata_url = metadata_url
        self._ttl = ttl_seconds
        self._fetched_at: float = 0.0
        self._jwks_uri: str | None = None
        # PyJWKClient handles JWKS fetching + key parsing. Tests can pass a
        # fake factory that returns a stub with `get_signing_key(kid)`.
        self._jwks_client_factory = jwks_client_factory or PyJWKClient
        self._jwks_client: Any = None

    def _is_stale(self) -> bool:
        return self._jwks_client is None or (time.time() - self._fetched_at) > self._ttl

    async def _refresh(self, http: httpx.AsyncClient) -> None:
        resp = await http.get(self._metadata_url, timeout=15.0)
        resp.raise_for_status()
        metadata = resp.json()
        jwks_uri = metadata.get("jwks_uri")
        if not jwks_uri:
            raise RuntimeError(f"OpenID metadata missing jwks_uri (got keys: {list(metadata)})")
        self._jwks_uri = jwks_uri
        self._jwks_client = self._jwks_client_factory(jwks_uri)
        self._fetched_at = time.time()
        log.info("refreshed Bot Framework JWKS: %s", jwks_uri)

    async def get_signing_key(self, kid: str, http: httpx.AsyncClient) -> Any:
        """Return a PyJWT-compatible signing key for the given kid.

        Refreshes the cache if stale OR if we don't recognise the kid (key
        rotation race). Raises whatever PyJWKClient raises on lookup failure.
        """
        if self._is_stale():
            await self._refresh(http)
        try:
            return self._jwks_client.get_signing_key(kid).key
        except Exception:
            # Forced refresh and retry — handles rotation where a new kid
            # appears between the previous refresh and this request.
            log.info("kid %s not in cache, forcing JWKS refresh", kid)
            await self._refresh(http)
            return self._jwks_client.get_signing_key(kid).key


class JWTVerificationError(Exception):
    """Single error type the TeamsAdapter catches; wraps any underlying jwt.* error."""


async def verify_token(
    token: str,
    *,
    app_id: str,
    metadata: OpenIdMetadataCache,
    http: httpx.AsyncClient,
    activity_service_url: str | None = None,
    expected_issuer: str = EXPECTED_ISSUER,
    leeway_seconds: int = 60,
) -> dict[str, Any]:
    """Verify a Bot Framework JWT and return its claims dict on success.

    Raises `JWTVerificationError` on any failure — bad signature, expired,
    wrong audience, wrong issuer, or `serviceurl` mismatch. Never returns
    partially-trusted claims.

    `activity_service_url` is an optional cross-check: when provided, the
    token's `serviceurl` claim must match (Bot Framework binds the service
    URL into the JWT to prevent reusing tokens against a different endpoint).
    """
    if not app_id:
        raise JWTVerificationError("TEAMS_APP_ID not configured")

    try:
        unverified = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as e:
        raise JWTVerificationError(f"unparseable token: {e}") from e
    kid = unverified.get("kid")
    if not kid:
        raise JWTVerificationError("token header missing kid")

    try:
        public_key = await metadata.get_signing_key(kid, http)
    except Exception as e:  # noqa: BLE001 — JWKS lookup failures are auth failures
        raise JWTVerificationError(f"could not resolve kid {kid!r}: {e}") from e

    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=app_id,
            issuer=expected_issuer,
            leeway=leeway_seconds,
            options={"require": ["exp", "iss", "aud"]},
        )
    except jwt.PyJWTError as e:
        raise JWTVerificationError(f"signature/claim verification failed: {e}") from e

    # serviceurl cross-check — Microsoft binds the activity's serviceUrl
    # into the JWT, so a token captured from one endpoint can't be replayed
    # against another. Only enforce when both are present (skip-emulator).
    if activity_service_url:
        token_url = str(claims.get("serviceurl", "")).rstrip("/")
        if token_url and token_url != activity_service_url.rstrip("/"):
            raise JWTVerificationError(
                f"serviceurl mismatch: token={token_url!r} activity={activity_service_url!r}"
            )

    return claims
