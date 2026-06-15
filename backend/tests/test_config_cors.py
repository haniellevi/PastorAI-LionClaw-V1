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
