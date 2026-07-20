"""Tests for POST /contacts/{id}/unarchive (FECH-06/REATIVAR-1).

Caminho de volta do arquivamento: admin/pastor limpa
arquivada_em/arquivada_por/arquivada_motivo e grava a linha append-only de
auditoria com acao='reativada' (a metade do enum de PessoaArquivamentoEvento
modelada em W3.2A e nunca usada até aqui).

Mesmo padrão de fake do test_contacts_reactivate_communications: a sessão NÃO
adivinha o shape da query — compila o SELECT real de Pessoa e só devolve a
pessoa se o WHERE filtrar `pessoas.igreja_id` EXPLICITAMENTE com o tenant da
pessoa. Uma regressão que removesse o filtro explícito de tenant quebraria o
happy path (pessoa some) E o teste cross-tenant.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db.models import AppUser, Pessoa, PessoaArquivamentoEvento
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_PID = "00000000-0000-0000-0000-0000000000c8"
_IGREJA_A = "00000000-0000-0000-0000-000000000001"  # tenant do make_app_user
_IGREJA_B = "00000000-0000-0000-0000-000000000002"  # outro tenant
_ADMIN_ID = "00000000-0000-0000-0000-0000000000a1"  # app_user do make_app_user

_ARQUIVADA_EM = dt.datetime(2026, 7, 1, 12, 0, tzinfo=dt.timezone.utc)
_ARQUIVADA_POR = uuid.UUID("00000000-0000-0000-0000-0000000000aa")

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


class UnarchiveSession:
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


def make_pessoa(*, arquivada=True, igreja_id=_IGREJA_A):
    return SimpleNamespace(
        id=_PID,
        igreja_id=igreja_id,
        nome="Aristides Arquivado",
        telefone="+5589999990008",
        arquivada_em=_ARQUIVADA_EM if arquivada else None,
        arquivada_por=_ARQUIVADA_POR if arquivada else None,
        arquivada_motivo="Mudou de cidade" if arquivada else None,
    )


def _wire(app, *, session, clerk) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    return TestClient(app)


def _post(client: TestClient):
    return client.post(f"/contacts/{_PID}/unarchive", headers=_AUTH)


def test_unarchive_happy_path_admin(app) -> None:
    """Campos arquivada_* ficam nulos + evento acao='reativada' + commit."""
    pessoa = make_pessoa(arquivada=True)
    session = UnarchiveSession(
        app_user=make_app_user(), roles=["admin"], pessoa=pessoa
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = _post(client)
    assert resp.status_code == 200
    body = resp.json()

    # Os 3 campos de arquivamento voltam a NULL — pessoa volta às listas.
    assert pessoa.arquivada_em is None
    assert pessoa.arquivada_por is None
    assert pessoa.arquivada_motivo is None

    assert body["pessoa_id"] == _PID
    assert body["arquivada"] is False
    # Registra QUEM reativou (app_user autenticado que executou a ação).
    assert body["reativada_por"] == _ADMIN_ID

    # Linha de auditoria append-only com a metade 'reativada' do enum,
    # espelho da linha 'arquivada' gravada por archive_pessoa.
    assert len(session.added) == 1
    evento = session.added[0]
    assert isinstance(evento, PessoaArquivamentoEvento)
    assert evento.acao == "reativada"
    assert str(evento.pessoa_id) == _PID
    assert str(evento.igreja_id) == _IGREJA_A
    assert str(evento.ator_id) == _ADMIN_ID
    # Motivo do arquivamento original preservado na trilha (a Pessoa perdeu o campo).
    assert "Mudou de cidade" in evento.motivo
    assert session.committed is True


def test_unarchive_allows_pastor(app) -> None:
    """Guard é admin/pastor: pastor (sem admin) também reativa."""
    pessoa = make_pessoa(arquivada=True)
    session = UnarchiveSession(
        app_user=make_app_user(), roles=["pastor"], pessoa=pessoa
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = _post(client)
    assert resp.status_code == 200
    assert pessoa.arquivada_em is None
    assert session.committed is True


def test_unarchive_forbidden_for_non_privileged_role(app) -> None:
    """RBAC real: papel não autorizado leva 403 e NADA muda."""
    pessoa = make_pessoa(arquivada=True)
    session = UnarchiveSession(
        app_user=make_app_user(), roles=["lider_celula"], pessoa=pessoa
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = _post(client)
    assert resp.status_code == 403
    assert pessoa.arquivada_em is not None  # intocada
    assert session.added == []
    assert session.committed is False


def test_unarchive_cross_tenant_is_404(app) -> None:
    """Pessoa de OUTRA igreja não é alcançável (filtro explícito de igreja_id)."""
    pessoa = make_pessoa(arquivada=True, igreja_id=_IGREJA_B)
    session = UnarchiveSession(
        app_user=make_app_user(), roles=["admin"], pessoa=pessoa
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = _post(client)
    assert resp.status_code == 404
    assert pessoa.arquivada_em is not None  # intocada
    assert session.added == []
    assert session.committed is False


def test_unarchive_invalid_uuid_is_404(app) -> None:
    session = UnarchiveSession(
        app_user=make_app_user(), roles=["admin"], pessoa=make_pessoa()
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = client.post("/contacts/nao-e-uuid/unarchive", headers=_AUTH)
    assert resp.status_code == 404


class PhoneConflictSession(UnarchiveSession):
    """flush() estoura a unique_violation do índice parcial de telefone."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.rolled_back = False

    def flush(self) -> None:
        raise IntegrityError(
            "UPDATE pessoas ...", {}, SimpleNamespace(pgcode="23505")
        )

    def rollback(self) -> None:
        self.rolled_back = True


def test_unarchive_phone_conflict_is_409(app) -> None:
    """Outra pessoa ATIVA já usa o telefone (uq_pessoas_telefone_ativa) → 409.

    Sem o tratamento, a IntegrityError do flush viraria HTTP 500 genérico.
    """
    pessoa = make_pessoa(arquivada=True)
    session = PhoneConflictSession(
        app_user=make_app_user(), roles=["admin"], pessoa=pessoa
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = _post(client)
    assert resp.status_code == 409
    assert "pessoa ativa" in resp.json()["detail"]
    assert session.rolled_back is True
    assert session.committed is False


def test_unarchive_not_archived_is_409(app) -> None:
    """Reativar pessoa NÃO arquivada → 409 (padrão de conflito do archive)."""
    pessoa = make_pessoa(arquivada=False)
    session = UnarchiveSession(
        app_user=make_app_user(), roles=["admin"], pessoa=pessoa
    )
    client = _wire(app, session=session, clerk=FakeClerk())
    resp = _post(client)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Pessoa não está arquivada"
    assert pessoa.arquivada_em is None
    assert session.added == []
    assert session.committed is False
