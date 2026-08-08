"""HTTP contract for per-tenant LLM model selection (US-27)."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import LlmCredential
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from app.services.llm import ModelAccessError
from tests.conftest import FakeClerk, FakeSession, make_app_user

_AUTH = {"Authorization": "Bearer good"}


class _Result:
    def __init__(self, scalar=None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class CredentialSession(FakeSession):
    def __init__(self, credential=None) -> None:
        super().__init__(app_user=make_app_user(), roles=["admin"])
        self.credential = credential
        self.credential_queries: list[str] = []

    def execute(self, statement, params=None):
        descriptions = getattr(statement, "column_descriptions", None) or []
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is LlmCredential:
            self.credential_queries.append(
                str(statement.compile(compile_kwargs={"literal_binds": True}))
            )
            return _Result(self.credential)
        return super().execute(statement, params)

    def add(self, obj) -> None:
        super().add(obj)
        if isinstance(obj, LlmCredential):
            self.credential = obj


def _client(app, session: CredentialSession) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def _credential(modelo: str = "gpt-5.6-luna"):
    return SimpleNamespace(
        provedor="openai",
        modelo=modelo,
        api_key_encrypted="ciphertext",
        validado=True,
        ativo=True,
    )


def test_model_catalog_is_admin_only_and_exposes_no_secret(app) -> None:
    client = _client(app, CredentialSession())
    assert client.get("/agent/models").status_code == 401

    response = client.get("/agent/models", headers=_AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["padrao"] == "gpt-5.6-luna"
    assert [item["modelo"] for item in body["modelos"]] == [
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
    ]
    assert "apiKey" not in response.text and "secret" not in response.text.lower()


def test_save_credential_persists_selected_model_for_callers_tenant(
    app, monkeypatch
) -> None:
    import app.routers.agent as agent_router

    session = CredentialSession()
    seen: list[tuple[str, str, str]] = []
    monkeypatch.setattr(agent_router, "encrypt_secret", lambda key: f"enc:{key}")
    monkeypatch.setattr(
        agent_router,
        "validate_credential",
        lambda provider, key, model: seen.append((provider, key, model)) or True,
    )

    response = _client(app, session).post(
        "/agent/credential",
        headers=_AUTH,
        json={
            "provedor": "openai",
            "apiKey": "sk-tenant",
            "modelo": "gpt-5.6-terra",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "active",
        "provedor": "openai",
        "modelo": "gpt-5.6-terra",
        "validado": True,
    }
    assert seen == [("openai", "sk-tenant", "gpt-5.6-terra")]
    assert session.credential.modelo == "gpt-5.6-terra"
    assert session.credential.api_key_encrypted == "enc:sk-tenant"
    assert session.commits == 1
    assert "sk-tenant" not in response.text
    assert any(
        "where llm_credentials.igreja_id =" in sql.lower()
        for sql in session.credential_queries
    )


def test_update_model_keeps_encrypted_key_and_validates_access(
    app, monkeypatch
) -> None:
    import app.routers.agent as agent_router

    credential = _credential()
    session = CredentialSession(credential)
    seen: list[tuple[str, str, str]] = []
    monkeypatch.setattr(agent_router, "decrypt_secret", lambda _value: "sk-existing")
    monkeypatch.setattr(
        agent_router,
        "validate_credential",
        lambda provider, key, model: seen.append((provider, key, model)) or True,
    )

    response = _client(app, session).put(
        "/agent/model",
        headers=_AUTH,
        json={"modelo": "gpt-5.6-sol"},
    )

    assert response.status_code == 200
    assert response.json() == {"modelo": "gpt-5.6-sol", "validado": True}
    assert credential.modelo == "gpt-5.6-sol"
    assert credential.api_key_encrypted == "ciphertext"
    assert seen == [("openai", "sk-existing", "gpt-5.6-sol")]
    assert session.commits == 1


def test_model_without_key_access_does_not_overwrite_selection(
    app, monkeypatch
) -> None:
    import app.routers.agent as agent_router

    credential = _credential()
    session = CredentialSession(credential)
    monkeypatch.setattr(agent_router, "decrypt_secret", lambda _value: "sk-existing")

    def deny(_provider: str, _key: str, model: str) -> bool:
        raise ModelAccessError(f"sem acesso a {model}")

    monkeypatch.setattr(agent_router, "validate_credential", deny)

    response = _client(app, session).put(
        "/agent/model",
        headers=_AUTH,
        json={"modelo": "gpt-5.6-sol"},
    )

    assert response.status_code == 422
    assert credential.modelo == "gpt-5.6-luna"
    assert credential.api_key_encrypted == "ciphertext"
    assert session.commits == 0


def test_model_outside_allowlist_is_rejected_before_database_write(app) -> None:
    session = CredentialSession(_credential())

    response = _client(app, session).put(
        "/agent/model",
        headers=_AUTH,
        json={"modelo": "modelo-inventado"},
    )

    assert response.status_code == 422
    assert session.commits == 0
