"""Tests for inbound Bot Framework JWT verification.

We generate an in-test RSA keypair, stand up a fake `PyJWKClient` that
returns its public key, encode signed tokens against the private key, and
assert each failure mode raises the right error. No network calls.

Covers:
  - happy path (valid signature, correct iss/aud/exp)
  - expired token
  - wrong audience (different app_id)
  - wrong issuer
  - bad signature (token signed with different key)
  - missing kid in header
  - serviceurl mismatch
  - claims include the exp/iss/aud requirement (PyJWT `require`)
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from src.chat.teams_auth import (
    EXPECTED_ISSUER,
    JWTVerificationError,
    OpenIdMetadataCache,
    verify_token,
)

APP_ID = "test-app-id-12345"
KID = "test-kid-1"


# --- Test fixtures: generate an RSA keypair + a fake JWKS client ---


def _make_keypair() -> tuple[Any, str]:
    """Returns (private_key_obj, public_key_pem_str)."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_pem = (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    return priv, pub_pem


class _FakeJWKSClient:
    """Stand-in for jwt.PyJWKClient — returns the test public key for any kid we know."""

    def __init__(self, public_pem_by_kid: dict[str, str]) -> None:
        self._keys = public_pem_by_kid

    def get_signing_key(self, kid: str):
        if kid not in self._keys:
            raise KeyError(f"kid not in fake JWKS: {kid}")

        class _SigningKey:
            def __init__(self, pem: str) -> None:
                # PyJWT's verify path accepts PEM bytes/str directly as the `key`
                self.key = pem

        return _SigningKey(self._keys[kid])


def _metadata_with(public_pem_by_kid: dict[str, str]) -> OpenIdMetadataCache:
    """Build a metadata cache whose JWKS factory returns the given fake."""
    cache = OpenIdMetadataCache(jwks_client_factory=lambda _uri: _FakeJWKSClient(public_pem_by_kid))
    # Pre-prime the cache so _refresh isn't called — no network in tests.
    cache._jwks_client = _FakeJWKSClient(public_pem_by_kid)  # noqa: SLF001
    cache._fetched_at = time.time()  # noqa: SLF001
    return cache


def _sign(
    private_key: Any,
    *,
    audience: str = APP_ID,
    issuer: str = EXPECTED_ISSUER,
    exp_offset: int = 3600,
    service_url: str | None = None,
    kid: str | None = KID,
    extra_claims: dict | None = None,
) -> str:
    payload: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
    }
    if service_url is not None:
        payload["serviceurl"] = service_url
    if extra_claims:
        payload.update(extra_claims)
    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(payload, private_key, algorithm="RS256", headers=headers)


@pytest.fixture
def keypair():
    return _make_keypair()


# --- Happy path ---


async def test_verify_happy_path(keypair):
    priv, pub = keypair
    metadata = _metadata_with({KID: pub})
    token = _sign(priv)
    claims = await verify_token(token, app_id=APP_ID, metadata=metadata, http=None)
    assert claims["aud"] == APP_ID
    assert claims["iss"] == EXPECTED_ISSUER


async def test_verify_passes_serviceurl_check(keypair):
    priv, pub = keypair
    metadata = _metadata_with({KID: pub})
    token = _sign(priv, service_url="https://smba.example/")
    claims = await verify_token(
        token,
        app_id=APP_ID,
        metadata=metadata,
        http=None,
        activity_service_url="https://smba.example/",
    )
    assert claims["serviceurl"] == "https://smba.example/"


async def test_verify_serviceurl_check_tolerates_trailing_slash(keypair):
    priv, pub = keypair
    metadata = _metadata_with({KID: pub})
    # token says foo/ (with slash); activity says foo (without). Should pass.
    token = _sign(priv, service_url="https://smba.example/")
    await verify_token(
        token,
        app_id=APP_ID,
        metadata=metadata,
        http=None,
        activity_service_url="https://smba.example",
    )


# --- Failure modes ---


async def test_verify_rejects_expired_token(keypair):
    priv, pub = keypair
    metadata = _metadata_with({KID: pub})
    token = _sign(priv, exp_offset=-3600)  # already expired an hour ago
    with pytest.raises(JWTVerificationError) as ei:
        await verify_token(token, app_id=APP_ID, metadata=metadata, http=None)
    assert "verification failed" in str(ei.value)


async def test_verify_rejects_wrong_audience(keypair):
    priv, pub = keypair
    metadata = _metadata_with({KID: pub})
    token = _sign(priv, audience="other-app-id")
    with pytest.raises(JWTVerificationError):
        await verify_token(token, app_id=APP_ID, metadata=metadata, http=None)


async def test_verify_rejects_wrong_issuer(keypair):
    priv, pub = keypair
    metadata = _metadata_with({KID: pub})
    token = _sign(priv, issuer="https://attacker.example/")
    with pytest.raises(JWTVerificationError):
        await verify_token(token, app_id=APP_ID, metadata=metadata, http=None)


async def test_verify_rejects_bad_signature(keypair):
    """Token signed by an attacker key the JWKS doesn't know."""
    _legit_priv, legit_pub = keypair
    attacker_priv, _attacker_pub = _make_keypair()
    metadata = _metadata_with({KID: legit_pub})
    # Attacker signs a token with `kid: KID` so the verifier looks up the LEGITIMATE
    # public key — but the signature was made with the attacker's private key.
    token = _sign(attacker_priv)
    with pytest.raises(JWTVerificationError):
        await verify_token(token, app_id=APP_ID, metadata=metadata, http=None)


async def test_verify_rejects_missing_kid(keypair):
    priv, pub = keypair
    metadata = _metadata_with({KID: pub})
    token = _sign(priv, kid=None)
    with pytest.raises(JWTVerificationError) as ei:
        await verify_token(token, app_id=APP_ID, metadata=metadata, http=None)
    assert "kid" in str(ei.value)


async def test_verify_rejects_unknown_kid(keypair):
    """If the JWKS doesn't contain the token's kid, refresh-and-retry, then fail."""
    priv, pub = keypair
    metadata = _metadata_with({KID: pub})
    token = _sign(priv, kid="rotated-kid-not-in-jwks")
    with pytest.raises(JWTVerificationError) as ei:
        await verify_token(token, app_id=APP_ID, metadata=metadata, http=None)
    assert "kid" in str(ei.value)


async def test_verify_rejects_serviceurl_mismatch(keypair):
    priv, pub = keypair
    metadata = _metadata_with({KID: pub})
    token = _sign(priv, service_url="https://smba.example/")
    with pytest.raises(JWTVerificationError) as ei:
        await verify_token(
            token,
            app_id=APP_ID,
            metadata=metadata,
            http=None,
            activity_service_url="https://attacker.example/",
        )
    assert "serviceurl mismatch" in str(ei.value)


async def test_verify_rejects_missing_app_id(keypair):
    priv, pub = keypair
    metadata = _metadata_with({KID: pub})
    token = _sign(priv)
    with pytest.raises(JWTVerificationError) as ei:
        await verify_token(token, app_id="", metadata=metadata, http=None)
    assert "TEAMS_APP_ID" in str(ei.value)


async def test_verify_rejects_garbage_token(keypair):
    _priv, pub = keypair
    metadata = _metadata_with({KID: pub})
    with pytest.raises(JWTVerificationError):
        await verify_token("not.a.jwt.at.all", app_id=APP_ID, metadata=metadata, http=None)
