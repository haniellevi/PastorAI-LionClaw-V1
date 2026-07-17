"""SEC-ALTO-004B — session/reset/invite reuse ClerkClient.verify_purpose_token.

SEC-ALTO-004 extracted the shared HS256 decode+verify policy (fixed algorithm,
pinned issuer, required claims, normalized error) into
``ClerkClient.verify_purpose_token`` and made the Google Calendar OAuth
``state`` reuse it instead of decoding independently. This file covers the
follow-up: ``verify_session_token``/``verify_reset_token``/
``verify_invite_token`` now delegate to the same policy too, so all four
purpose-scoped JWTs (session, reset, invite, OAuth state) share one
implementation.

Exercises, against the REAL ``ClerkClient``/``GoogleOAuthClient`` (no fakes):
valid roundtrip, expired, wrong issuer, missing required claim — for each of
session/reset/invite (OAuth-state equivalents already live in
``test_calendar_oauth.py``) — plus cross-token isolation across all four:
a token minted for one purpose must never verify under another's issuer, even
though all four are signed with the same secret.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import Settings
from app.services.clerk import ClerkAuthError, ClerkClient
from app.services.google_oauth import GoogleOAuthClient, GoogleOAuthError

_SECRET = "s" * 40
_SETTINGS = Settings(session_jwt_secret=_SECRET)

_RESET_JTI = "11111111-1111-1111-1111-111111111111"
_IGREJA = "00000000-0000-0000-0000-000000000001"


def _clerk() -> ClerkClient:
    return ClerkClient(settings=_SETTINGS)


def _oauth() -> GoogleOAuthClient:
    return GoogleOAuthClient(settings=_SETTINGS)


def _craft(
    *,
    issuer: str,
    secret: str = _SECRET,
    exp_delta: timedelta = timedelta(minutes=10),
    extra: dict | None = None,
    omit: tuple[str, ...] = (),
) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": "clerk_user_1", "iss": issuer, "iat": now, "exp": now + exp_delta}
    if extra:
        payload.update(extra)
    for key in omit:
        payload.pop(key, None)
    return jwt.encode(payload, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# valid roundtrip — session / reset / invite (OAuth state already covered by
# test_calendar_oauth.py::test_state_roundtrip)
# ---------------------------------------------------------------------------
def test_session_token_roundtrip() -> None:
    clerk = _clerk()
    token = clerk._mint_session_token("clerk_user_1")  # noqa: SLF001 - no public mint w/o live Clerk call
    identity = clerk.verify_session_token(token)
    assert identity.clerk_user_id == "clerk_user_1"


def test_reset_token_roundtrip() -> None:
    clerk = _clerk()
    token, jti, _exp = clerk.mint_reset_token("clerk_user_1")
    clerk_user_id, verified_jti = clerk.verify_reset_token(token)
    assert clerk_user_id == "clerk_user_1"
    assert verified_jti == jti


def test_invite_token_roundtrip() -> None:
    clerk = _clerk()
    token = clerk.mint_invite_token("app_user_1")
    assert clerk.verify_invite_token(token) == "app_user_1"


# ---------------------------------------------------------------------------
# expired / wrong issuer / missing required claim — session, reset, invite
# ---------------------------------------------------------------------------
_TOKEN_TYPES = [
    ("pastorai", "verify_session_token", {}, "Invalid session token"),
    (
        "pastorai-reset",
        "verify_reset_token",
        {"jti": _RESET_JTI},
        "Invalid or expired reset token",
    ),
    ("pastorai-invite", "verify_invite_token", {}, "Invalid or expired invite token"),
]


@pytest.mark.parametrize("issuer,verify_name,extra,error_message", _TOKEN_TYPES)
def test_expired_token_is_rejected(issuer, verify_name, extra, error_message) -> None:
    clerk = _clerk()
    token = _craft(issuer=issuer, exp_delta=timedelta(minutes=-1), extra=extra)
    with pytest.raises(ClerkAuthError, match=f"^{error_message}$"):
        getattr(clerk, verify_name)(token)


@pytest.mark.parametrize("issuer,verify_name,extra,error_message", _TOKEN_TYPES)
def test_wrong_issuer_is_rejected(issuer, verify_name, extra, error_message) -> None:
    clerk = _clerk()
    token = _craft(issuer=f"not-{issuer}", extra=extra)
    with pytest.raises(ClerkAuthError, match=f"^{error_message}$"):
        getattr(clerk, verify_name)(token)


def test_session_token_missing_sub_is_rejected() -> None:
    clerk = _clerk()
    token = _craft(issuer="pastorai", omit=("sub",))
    with pytest.raises(ClerkAuthError):
        clerk.verify_session_token(token)


def test_reset_token_missing_jti_is_rejected() -> None:
    clerk = _clerk()
    token = _craft(issuer="pastorai-reset", extra={"jti": _RESET_JTI}, omit=("jti",))
    with pytest.raises(ClerkAuthError):
        clerk.verify_reset_token(token)


def test_invite_token_missing_sub_is_rejected() -> None:
    clerk = _clerk()
    token = _craft(issuer="pastorai-invite", omit=("sub",))
    with pytest.raises(ClerkAuthError):
        clerk.verify_invite_token(token)


# ---------------------------------------------------------------------------
# cross-token isolation — a token minted for one purpose must never verify
# under another purpose's verifier, even though all four share the secret.
# ---------------------------------------------------------------------------
def test_session_token_cannot_be_used_as_reset_invite_or_state() -> None:
    clerk = _clerk()
    token = clerk._mint_session_token("clerk_user_1")  # noqa: SLF001
    with pytest.raises(ClerkAuthError):
        clerk.verify_reset_token(token)
    with pytest.raises(ClerkAuthError):
        clerk.verify_invite_token(token)
    with pytest.raises(GoogleOAuthError):
        _oauth().verify_state(token)


def test_reset_token_cannot_be_used_as_session_or_invite() -> None:
    clerk = _clerk()
    token, _jti, _exp = clerk.mint_reset_token("clerk_user_1")
    with pytest.raises(ClerkAuthError):
        clerk.verify_session_token(token)
    with pytest.raises(ClerkAuthError):
        clerk.verify_invite_token(token)


def test_invite_token_cannot_be_used_as_session_or_reset() -> None:
    clerk = _clerk()
    token = clerk.mint_invite_token("app_user_1")
    with pytest.raises(ClerkAuthError):
        clerk.verify_session_token(token)
    with pytest.raises(ClerkAuthError):
        clerk.verify_reset_token(token)


def test_oauth_state_cannot_be_used_as_reset_or_invite() -> None:
    # state → session cross-check already covered by
    # test_calendar_oauth.py::test_oauth_state_cannot_be_used_as_session_token
    state = _oauth().sign_state(_IGREJA)
    clerk = _clerk()
    with pytest.raises(ClerkAuthError):
        clerk.verify_reset_token(state)
    with pytest.raises(ClerkAuthError):
        clerk.verify_invite_token(state)
