"""SEC-1 config hardening.

BAIXO-001: production must use a dedicated ``SESSION_JWT_SECRET`` and never
reuse the Clerk secret to sign session JWTs.
MEDIO-001: CORS must use explicit origins and never fall back to a wildcard
together with credentials.

Settings are built with explicit init kwargs (highest precedence in
pydantic-settings) and ``_env_file=None`` so the suite is deterministic
regardless of a local ``.env``.
"""

from __future__ import annotations

import pytest
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.main import create_app

# A complete, VALID production config. Each test overrides one field to exercise
# a fail-fast path. Values are placeholders — no real secrets.
_PROD = dict(
    app_env="production",
    clerk_secret_key="sk_live_placeholder_clerk_0000000000",
    clerk_jwt_issuer="https://clerk.example.com",
    supabase_url="https://db.example.supabase.co",
    supabase_service_role_key="svc_placeholder",
    database_url="postgresql://u:p@h:5432/db",
    secrets_encryption_key="enc_placeholder",
    evolution_api_url="https://evo.example.com",
    evolution_api_key="evk_placeholder",
    evolution_webhook_secret="whs_placeholder",
    redis_url="redis://localhost:6379/0",
    frontend_url="https://app.igreja12.com.br",
    app_base_url="https://api.igreja12.com.br",
    session_jwt_secret="s" * 40,
)


def _prod(**over) -> Settings:
    return Settings(_env_file=None, **{**_PROD, **over})


# ---- BAIXO-001: dedicated session secret ---------------------------------


def test_prod_ready_with_dedicated_session_secret() -> None:
    _prod().assert_production_ready()  # must not raise


def test_prod_fails_without_session_secret() -> None:
    with pytest.raises(RuntimeError, match="SESSION_JWT_SECRET"):
        _prod(session_jwt_secret="").assert_production_ready()


def test_prod_fails_with_weak_session_secret() -> None:
    with pytest.raises(RuntimeError, match="SESSION_JWT_SECRET"):
        _prod(session_jwt_secret="short").assert_production_ready()


def test_prod_fails_when_session_secret_reuses_clerk() -> None:
    shared = "z" * 40
    with pytest.raises(RuntimeError, match="CLERK_SECRET_KEY"):
        _prod(
            clerk_secret_key=shared, session_jwt_secret=shared
        ).assert_production_ready()


def test_effective_session_secret_never_clerk_in_prod() -> None:
    s = _prod()
    assert s.effective_session_secret == "s" * 40
    assert s.effective_session_secret != s.clerk_secret_key


def test_dev_session_secret_falls_back_to_clerk() -> None:
    # Dev keeps the documented fallback so it boots without an extra env var,
    # and assert_production_ready is a no-op outside production.
    s = Settings(
        _env_file=None,
        app_env="development",
        clerk_secret_key="sk_dev_placeholder",
        session_jwt_secret="",
    )
    assert s.effective_session_secret == "sk_dev_placeholder"
    s.assert_production_ready()  # no raise


# ---- MEDIO-001: strict CORS ----------------------------------------------


def test_prod_cors_covers_three_surfaces() -> None:
    origins = _prod().cors_origins
    for host in ("app", "admin", "painel"):
        assert f"https://{host}.igreja12.com.br" in origins


def test_prod_fails_without_explicit_origins() -> None:
    # The localhost defaults are not acceptable production origins.
    with pytest.raises(RuntimeError, match="FRONTEND_URL|APP_BASE_URL"):
        _prod(
            frontend_url="http://localhost:3000",
            app_base_url="http://localhost:8000",
        ).assert_production_ready()


def test_cors_origins_never_wildcard() -> None:
    assert "*" not in _prod().cors_origins
    assert "*" not in Settings(_env_file=None, app_env="development").cors_origins


def test_app_cors_middleware_uses_explicit_origins() -> None:
    # main.py must wire allow_origins to settings.cors_origins with no wildcard
    # fallback (MEDIO-001).
    app = create_app()
    mw = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    opts = getattr(mw, "kwargs", None) or getattr(mw, "options", {})
    allow = opts.get("allow_origins", [])
    assert "*" not in allow
    assert allow == get_settings().cors_origins
