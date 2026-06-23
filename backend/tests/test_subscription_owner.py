"""GET/POST /subscription são restritos ao DONO (admin principal) da igreja (#4).

require_owner: admin NÃO basta — só quem é o dono_id da própria igreja passa.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_SELF = "00000000-0000-0000-0000-0000000000a1"  # = make_app_user().id
_OTHER = "00000000-0000-0000-0000-0000000000c9"


def _client(app, *, dono_id: str | None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: FakeSession(
        app_user=make_app_user(dono_id=dono_id), roles=["admin"]
    )
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def test_subscription_get_forbidden_for_non_owner_admin(app) -> None:
    # admin que NÃO é o dono -> 403 (require_owner), antes mesmo de buscar a sub.
    resp = _client(app, dono_id=_OTHER).get("/subscription", headers=_AUTH)
    assert resp.status_code == 403


def test_subscription_get_forbidden_when_church_has_no_owner(app) -> None:
    # igreja sem dono (dono_id NULL) -> ninguém passa até o master reatribuir.
    resp = _client(app, dono_id=None).get("/subscription", headers=_AUTH)
    assert resp.status_code == 403


def test_subscription_get_allowed_for_owner(app) -> None:
    # dono passa o gate; 404 só porque o fake não tem assinatura (não é 403).
    resp = _client(app, dono_id=_SELF).get("/subscription", headers=_AUTH)
    assert resp.status_code == 404


def test_subscription_checkout_forbidden_for_non_owner_admin(app) -> None:
    # body válido: o 403 vem do require_owner, não de validação.
    resp = _client(app, dono_id=_OTHER).post(
        "/subscription", json={"plano": "ate_100"}, headers=_AUTH
    )
    assert resp.status_code == 403
