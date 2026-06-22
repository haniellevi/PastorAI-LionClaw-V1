"""Regression tests for CORS origin normalization.

A trailing slash in ``FRONTEND_URL``/``APP_BASE_URL`` once broke every
cross-origin auth call in production: browsers send ``Origin`` as
scheme+host+port (no path), so a stored ``https://host/`` never matched the
browser-sent ``https://host`` and the preflight was rejected with
"Disallowed CORS origin". ``cors_origins`` must strip the trailing slash.
"""

from __future__ import annotations

from app.config import Settings


def test_cors_origins_strip_trailing_slash() -> None:
    settings = Settings(
        frontend_url="https://pastorai-frontend.vercel.app/",
        app_base_url="https://api.filadelfiacorrente.com/",
    )
    origins = settings.cors_origins
    assert "https://pastorai-frontend.vercel.app" in origins
    assert "https://api.filadelfiacorrente.com" in origins
    # The browser-sent origin (no slash) must be present, not the slashed form.
    assert all(not o.endswith("/") for o in origins)


def test_cors_origins_without_slash_unchanged() -> None:
    settings = Settings(
        frontend_url="https://pastorai-frontend.vercel.app",
        app_base_url="https://api.filadelfiacorrente.com",
    )
    assert set(settings.cors_origins) == {
        "https://pastorai-frontend.vercel.app",
        "https://api.filadelfiacorrente.com",
    }


def test_cors_origins_adds_admin_subdomain() -> None:
    # O console master roda em admin.<dominio> (mesma app na Vercel). Deve ser
    # liberado automaticamente junto do app.<dominio>, senão o login do console
    # a partir de admin.igreja12.com.br cai em CORS.
    settings = Settings(
        frontend_url="https://app.igreja12.com.br",
        app_base_url="https://api.igreja12.com.br",
    )
    origins = settings.cors_origins
    assert "https://app.igreja12.com.br" in origins
    assert "https://admin.igreja12.com.br" in origins
