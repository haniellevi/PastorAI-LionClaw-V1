from types import SimpleNamespace

from app.routers import platform_admin, team
from app.services.frontend_auth_links import build_frontend_auth_link


def test_builds_tracker_safe_activation_path_without_fragment() -> None:
    link = build_frontend_auth_link(
        "https://app.igreja12.com.br/",
        "ativar",
        "header.payload.signature",
    )

    assert link == "https://app.igreja12.com.br/ativar/header.payload.signature"
    assert "#" not in link


def test_escapes_token_as_single_path_segment() -> None:
    link = build_frontend_auth_link(
        "https://app.igreja12.com.br",
        "redefinir-senha",
        "token/with unsafe?characters",
    )

    assert link == (
        "https://app.igreja12.com.br/redefinir-senha/"
        "token%2Fwith%20unsafe%3Fcharacters"
    )


class _InviteTokenClerk:
    def mint_invite_token(self, app_user_id: str) -> str:
        return f"header.{app_user_id}.signature"


def test_both_invite_sources_generate_real_frontend_paths(monkeypatch) -> None:
    settings = SimpleNamespace(frontend_url="https://app.igreja12.com.br")
    monkeypatch.setattr(team, "get_settings", lambda: settings)
    monkeypatch.setattr(platform_admin, "get_settings", lambda: settings)
    app_user_id = "11111111-1111-1111-1111-111111111111"

    for build_link in (team._activation_link, platform_admin._activation_link):
        link = build_link(app_user_id, _InviteTokenClerk())
        assert link.startswith("https://app.igreja12.com.br/ativar/")
        assert "#" not in link
