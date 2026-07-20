"""Tests for POST /contacts/{id}/reactivate-communications (FECH-05/OPTIN-1).

Caminho de volta do opt-out: admin/pastor reativa comunicações de uma Pessoa,
gravando um ConsentRecord novo com termo_versao='reoptin:<versao>' (mesma
estrutura de _apply_optout em app/agent/runtime.py, que grava 'optout:<versao>').

O fake de sessão NÃO adivinha o shape da query: compila o SELECT real de Pessoa
e só devolve a pessoa se o WHERE filtrar `pessoas.igreja_id` EXPLICITAMENTE com
o tenant da pessoa — assim uma regressão que removesse o filtro explícito de
tenant quebraria o happy path (pessoa some) E o teste cross-tenant.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.models import AppUser, ConsentRecord, Pessoa
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_PID = "00000000-0000-0000-0000-0000000000b7"
_IGREJA_A = "00000000-0000-0000-0000-000000000001"  # tenant do make_app_user
_IGREJA_B = "00000000-0000-0000-0000-000000000002"  # outro tenant

_AUTH = {"Authorization": "Bearer good"}


class _R:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class ReoptinSession:
    """Roteia auth (AppUser/UserRole) + Pessoa com verificação do WHERE real."""

    def __init__(self, *, app_user, roles, pessoa=None) -> None:
        self.app_user = app_user
        self.roles = roles
        self.pessoa = pessoa
        self.added: list = []
        self.committed = False

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Pessoa:
            return _R(scalar=self._match_pessoa(statement))
        return _R(scalars=self.roles)

    def _match_pessoa(self, statement):
        """Só devolve a Pessoa se o WHERE compilado filtrar id E igreja_id.

        Prova de isolamento de tenant: sem o filtro explícito de
        `pessoas.igreja_id` no SQL, NENHUMA pessoa é encontrada (happy path
        falharia com 404); com o filtro, uma pessoa de OUTRA igreja nunca é
        alcançável porque o bind do tenant não bate com o dela.
        """
        if self.pessoa is None:
            return None
        compiled = statement.compile()
        sql = str(compiled)
        if "pessoas.igreja_id" not in sql or "pessoas.id" not in sql:
            return None
        bound = {str(v) for v in compiled.params.values()}
        if str(self.pessoa.id) in bound and str(self.pessoa.igreja_id) in bound:
            return self.pessoa
        return None

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:  # pragma: no cover - objeto já "vivo"
        pass

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


def make_pessoa(*, optout=True, igreja_id=_IGREJA_A):
    return SimpleNamespace(
        id=_PID,
        igreja_id=igreja_id,
        nome="Otília Optout",
        telefone="+5589999990007",
        optout=optout,
    )


def _wire(app, *, session, clerk) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    return TestClient(app)


def _post(client: TestClient):
    return client.post(
        f"/contacts/{_PID}/reactivate-communications", headers=_AUTH
    )


def test_reactivate_happy_path_admin(app) -> None:
    """optout=True -> False + ConsentRecord 'reoptin:<versao>' com ator persistido."""
    pessoa = make_pessoa(optout=True)
    session = ReoptinSession(
        app_user=make_app_user(), roles=["admin"], pessoa=pessoa
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = _post(client)
    assert resp.status_code == 200
    body = resp.json()

    expected_termo = f"reoptin:{get_settings().agent_term_version}"
    assert pessoa.optout is False
    assert body["optout"] is False
    assert body["ja_ativa"] is False
    assert body["termo_versao"] == expected_termo
    # Registra QUEM reativou (app_user autenticado que executou a ação).
    assert body["reativada_por"] == "00000000-0000-0000-0000-0000000000a1"

    # Consentimento gravado na MESMA estrutura de _apply_optout (runtime.py).
    assert len(session.added) == 1
    record = session.added[0]
    assert isinstance(record, ConsentRecord)
    assert record.termo_versao == expected_termo
    assert str(record.pessoa_id) == _PID
    assert str(record.igreja_id) == _IGREJA_A
    assert record.aceite_em is not None
    # Autoria DURÁVEL: quem reativou fica no próprio ConsentRecord persistido
    # (consent_records.ator_id, migration 20260720_191143) — não apenas na
    # resposta HTTP/log. NULL segue reservado aos fluxos automáticos.
    assert str(record.ator_id) == "00000000-0000-0000-0000-0000000000a1"
    assert session.committed is True


def test_reactivate_allows_pastor(app) -> None:
    """Guard é admin/pastor: pastor (sem admin) também reativa."""
    pessoa = make_pessoa(optout=True)
    session = ReoptinSession(
        app_user=make_app_user(), roles=["pastor"], pessoa=pessoa
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = _post(client)
    assert resp.status_code == 200
    assert pessoa.optout is False
    assert session.committed is True


def test_reactivate_forbidden_for_non_privileged_role(app) -> None:
    """RBAC real: papel não autorizado leva 403 e NADA muda."""
    pessoa = make_pessoa(optout=True)
    session = ReoptinSession(
        app_user=make_app_user(), roles=["lider_celula"], pessoa=pessoa
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = _post(client)
    assert resp.status_code == 403
    assert pessoa.optout is True
    assert session.added == []
    assert session.committed is False


def test_reactivate_cross_tenant_is_404(app) -> None:
    """Pessoa de OUTRA igreja não é alcançável (filtro explícito de igreja_id)."""
    pessoa = make_pessoa(optout=True, igreja_id=_IGREJA_B)
    session = ReoptinSession(
        app_user=make_app_user(), roles=["admin"], pessoa=pessoa
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = _post(client)
    assert resp.status_code == 404
    assert pessoa.optout is True  # intocada
    assert session.added == []
    assert session.committed is False


def test_reactivate_invalid_uuid_is_404(app) -> None:
    session = ReoptinSession(
        app_user=make_app_user(), roles=["admin"], pessoa=make_pessoa()
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.post(
        "/contacts/nao-e-uuid/reactivate-communications", headers=_AUTH
    )
    assert resp.status_code == 404


def test_reactivate_idempotent_when_not_opted_out(app) -> None:
    """Pessoa já ativa: 200 com ja_ativa=True, sem consentimento duplicado."""
    pessoa = make_pessoa(optout=False)
    session = ReoptinSession(
        app_user=make_app_user(), roles=["admin"], pessoa=pessoa
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = _post(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ja_ativa"] is True
    assert body["optout"] is False
    assert session.added == []
