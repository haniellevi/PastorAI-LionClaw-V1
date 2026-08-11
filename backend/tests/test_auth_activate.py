"""Tests for the invite activation flow (POST /auth/activate + GET /auth/invite).

The invited app_user starts without a Clerk account (clerk_user_id NULL).
Activation verifies the signed invite token, creates the Clerk user with the
chosen password and links it, flipping the account to 'ativo'. Validated offline.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import AppUser, Base, Celula, Igreja, Pessoa, UserRole
from app.db.session import get_db
from app.routers import auth as auth_router
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk

_AID = "00000000-0000-0000-0000-0000000000a1"
_PESSOA_ID = "00000000-0000-0000-0000-0000000000b1"
_PID = "00000000-0000-0000-0000-0000000000b9"
_CELULA_ID = "00000000-0000-0000-0000-0000000000c1"


class _Scalars:
    def __init__(self, items) -> None:
        self._items = items

    def all(self) -> list:
        return list(self._items)


class _Result:
    def __init__(self, scalar=None, items=None) -> None:
        self._scalar = scalar
        self._items = items or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self) -> _Scalars:
        return _Scalars(self._items)


class InviteSession:
    """Minimal session: returns the invited app_user, records commit, and
    supports the Parte B path (Pessoa dedup lookup + insert)."""

    def __init__(
        self,
        app_user=None,
        pessoas=None,
        celula=None,
        linked_user_id=None,
        raise_commit: bool = False,
    ) -> None:
        self.app_user = app_user
        if pessoas is None and getattr(app_user, "pessoa_id", None) is not None:
            pessoas = [
                SimpleNamespace(
                    id=app_user.pessoa_id,
                    igreja_id=app_user.igreja_id,
                    telefone="11999990000",
                    celula_id=None,
                    arquivada_em=None,
                )
            ]
        self.pessoas = list(pessoas or [])  # dedup candidates for Parte B
        self.celula = celula
        self.linked_user_id = linked_user_id
        self.raise_commit = raise_commit
        self.added: list = []
        self.committed = False
        self.rolled_back = False
        self.statements: list = []

    def execute(self, statement, params=None) -> _Result:
        self.statements.append(statement)
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        name = descs[0].get("name") if descs else None
        if ent is AppUser and name == "id":
            return _Result(scalar=self.linked_user_id)
        if ent is AppUser:
            return _Result(scalar=self.app_user)
        if ent is Pessoa:
            pessoas = self.pessoas
            if "arquivada_em IS NULL" in str(statement):
                pessoas = [
                    p
                    for p in pessoas
                    if getattr(p, "arquivada_em", None) is None
                ]
            return _Result(
                scalar=(pessoas[0] if pessoas else None),
                items=pessoas,
            )
        if ent is Celula:
            if "lider_id" in str(statement.whereclause):
                lider_id = getattr(self.celula, "lider_id", None)
                if lider_id is None:
                    return _Result()
            return _Result(scalar=self.celula)
        return _Result()

    def add(self, obj) -> None:
        self.added.append(obj)
        if isinstance(obj, Pessoa) and obj not in self.pessoas:
            self.pessoas.append(obj)

    def begin_nested(self):
        # UNIQ-PESSOA-1: INSERT roda num SAVEPOINT; sem corrida na fake é no-op.
        from contextlib import nullcontext

        return nullcontext()

    def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = _PID

    def commit(self) -> None:
        if self.raise_commit:
            raise RuntimeError("database commit failed")
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:  # pragma: no cover
        pass


def make_invited(
    *,
    clerk_user_id=None,
    email: str = "novo@igreja.org",
    nome: str = "Pastor Novo",
    igreja: str = "Igreja Nova",
    pessoa_id=_PESSOA_ID,
    celula_pendente_id=None,
    status="convidado",
):
    return SimpleNamespace(
        id=_AID,
        clerk_user_id=clerk_user_id,
        email=email,
        nome=nome,
        status=status,
        pessoa_id=pessoa_id,
        celula_pendente_id=celula_pendente_id,
        igreja_id="00000000-0000-0000-0000-000000000001",
        igreja=SimpleNamespace(nome=igreja),
    )


def _wire(app, *, session, clerk, raise_server_exceptions: bool = True) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


# ---- GET /auth/invite/{token} ---------------------------------------------
def test_invite_info_returns_data(app) -> None:
    client = _wire(app, session=InviteSession(make_invited()), clerk=FakeClerk(invite_app_user_id=_AID))
    resp = client.get("/auth/invite/sometoken")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "novo@igreja.org"
    assert body["nome"] == "Pastor Novo"
    assert body["igreja"] == "Igreja Nova"


def test_invite_info_invalid_token(app) -> None:
    client = _wire(app, session=InviteSession(make_invited()), clerk=FakeClerk(raise_invite=True))
    assert client.get("/auth/invite/bad").status_code == 400


def test_invite_info_already_activated(app) -> None:
    client = _wire(
        app,
        session=InviteSession(make_invited(clerk_user_id="clerk_existing")),
        clerk=FakeClerk(invite_app_user_id=_AID),
    )
    assert client.get("/auth/invite/tok").status_code == 409


# ---- POST /auth/activate ---------------------------------------------------
def test_activate_creates_access(app) -> None:
    invited = make_invited()
    session = InviteSession(invited)
    client = _wire(
        app,
        session=session,
        clerk=FakeClerk(invite_app_user_id=_AID, created_clerk_id="clerk_brand_new"),
    )
    resp = client.post("/auth/activate", json={"token": "tok", "password": "umaSenha123"})
    assert resp.status_code == 200
    assert invited.clerk_user_id == "clerk_brand_new"
    assert invited.status == "ativo"
    assert session.committed is True


def test_activate_invalid_token(app) -> None:
    client = _wire(app, session=InviteSession(make_invited()), clerk=FakeClerk(raise_invite=True))
    resp = client.post("/auth/activate", json={"token": "bad", "password": "umaSenha123"})
    assert resp.status_code == 400


def test_activate_already_activated(app) -> None:
    client = _wire(
        app,
        session=InviteSession(make_invited(clerk_user_id="clerk_x")),
        clerk=FakeClerk(invite_app_user_id=_AID),
    )
    resp = client.post("/auth/activate", json={"token": "tok", "password": "umaSenha123"})
    assert resp.status_code == 409


def test_activate_rejects_short_password(app) -> None:
    client = _wire(app, session=InviteSession(make_invited()), clerk=FakeClerk(invite_app_user_id=_AID))
    resp = client.post("/auth/activate", json={"token": "tok", "password": "curta"})
    assert resp.status_code == 422


def test_activate_clerk_failure_is_502(app) -> None:
    invited = make_invited()
    session = InviteSession(invited)
    clerk = FakeClerk(invite_app_user_id=_AID, raise_create=True)
    client = _wire(
        app,
        session=session,
        clerk=clerk,
    )
    resp = client.post("/auth/activate", json={"token": "tok", "password": "umaSenha123"})
    assert resp.status_code == 502
    assert session.rolled_back is True
    assert session.committed is False


@pytest.mark.parametrize("raise_delete", [False, True])
def test_activate_database_failure_compensates_new_clerk_identity(
    app, raise_delete
) -> None:
    invited = make_invited()
    session = InviteSession(invited, raise_commit=True)
    clerk = FakeClerk(
        invite_app_user_id=_AID,
        created_clerk_id="clerk_created_for_failed_activation",
        raise_delete=raise_delete,
    )

    resp = _wire(
        app,
        session=session,
        clerk=clerk,
        raise_server_exceptions=False,
    ).post("/auth/activate", json={"token": "tok", "password": "umaSenha123"})

    assert resp.status_code == 500
    assert session.rolled_back is True
    assert clerk.create_calls == 1
    assert clerk.delete_calls == 1


def test_revoked_invite_token_cannot_reactivate(app) -> None:
    invited = make_invited(status="revogado")
    clerk = FakeClerk(invite_app_user_id=_AID)
    client = _wire(app, session=InviteSession(invited), clerk=clerk)
    assert client.get("/auth/invite/tok").status_code == 400
    resp = client.post(
        "/auth/activate", json={"token": "tok", "password": "umaSenha123"}
    )
    assert resp.status_code == 400
    assert clerk.create_calls == 0


def test_activate_rejects_second_app_user_for_same_person_before_clerk(app) -> None:
    invited = make_invited()
    session = InviteSession(invited, linked_user_id="00000000-0000-0000-0000-0000000000ff")
    clerk = FakeClerk(invite_app_user_id=_AID)
    resp = _wire(app, session=session, clerk=clerk).post(
        "/auth/activate", json={"token": "tok", "password": "umaSenha123"}
    )
    assert resp.status_code == 409
    assert clerk.create_calls == 0
    assert session.rolled_back is True


@pytest.mark.parametrize(
    ("arquivada_em", "sem_interesse"),
    [("2026-08-11T12:00:00Z", False), (None, True)],
)
def test_activate_parte_a_revalidates_person_eligibility_before_clerk(
    app, arquivada_em, sem_interesse
) -> None:
    invited = make_invited()
    pessoa = SimpleNamespace(
        id=_PESSOA_ID,
        igreja_id=invited.igreja_id,
        telefone="11999990000",
        celula_id=None,
        arquivada_em=arquivada_em,
        sem_interesse=sem_interesse,
    )
    session = InviteSession(invited, pessoas=[pessoa])
    clerk = FakeClerk(invite_app_user_id=_AID)

    resp = _wire(app, session=session, clerk=clerk).post(
        "/auth/activate", json={"token": "tok", "password": "umaSenha123"}
    )

    assert resp.status_code == 409
    assert session.rolled_back is True
    assert session.committed is False
    assert clerk.create_calls == 0
    assert clerk.delete_calls == 0


def test_activate_rejects_global_clerk_email_without_password_reset(app) -> None:
    invited = make_invited()
    session = InviteSession(invited)
    clerk = FakeClerk(
        invite_app_user_id=_AID,
        existing_clerk_id="user_from_another_church",
    )
    resp = _wire(app, session=session, clerk=clerk).post(
        "/auth/activate", json={"token": "tok", "password": "umaSenha123"}
    )
    assert resp.status_code == 409
    assert clerk.create_calls == 0
    assert clerk.set_password_calls == 0
    assert session.rolled_back is True


def test_activate_parte_b_clerk_failure_rolls_back_prepared_person(app) -> None:
    invited = make_invited(pessoa_id=None)
    session = InviteSession(invited, pessoas=[])
    clerk = FakeClerk(invite_app_user_id=_AID, raise_create=True)
    resp = _wire(app, session=session, clerk=clerk).post(
        "/auth/activate",
        json={
            "token": "tok",
            "password": "umaSenha123",
            "telefone": "(11) 98888-7777",
        },
    )
    assert resp.status_code == 502
    assert session.rolled_back is True
    assert session.committed is False


# ---- Parte B (pessoa nova completa o cadastro na ativação) ----------------
def test_invite_info_flags_parte_b(app) -> None:
    # Sem pessoa vinculada => o convite pede o cadastro (telefone) na ativação.
    parte_b = InviteSession(make_invited(pessoa_id=None, celula_pendente_id=_CELULA_ID))
    parte_a = InviteSession(make_invited())
    assert (
        _wire(app, session=parte_b, clerk=FakeClerk(invite_app_user_id=_AID))
        .get("/auth/invite/tok")
        .json()["precisaCadastro"]
        is True
    )
    assert (
        _wire(app, session=parte_a, clerk=FakeClerk(invite_app_user_id=_AID))
        .get("/auth/invite/tok")
        .json()["precisaCadastro"]
        is False
    )


def test_activate_parte_b_requires_phone(app) -> None:
    invited = make_invited(pessoa_id=None, celula_pendente_id=_CELULA_ID)
    client = _wire(app, session=InviteSession(invited), clerk=FakeClerk(invite_app_user_id=_AID))
    resp = client.post("/auth/activate", json={"token": "tok", "password": "umaSenha123"})
    assert resp.status_code == 400
    assert invited.clerk_user_id is None  # não cria conta órfã


def test_activate_parte_b_legacy_pending_cell_creates_person_without_membership(app) -> None:
    invited = make_invited(pessoa_id=None, celula_pendente_id=_CELULA_ID)
    celula = SimpleNamespace(id=_CELULA_ID, igreja_id=invited.igreja_id)
    session = InviteSession(invited, celula=celula)  # sem candidatos de dedup -> cria nova
    client = _wire(
        app,
        session=session,
        clerk=FakeClerk(invite_app_user_id=_AID, created_clerk_id="clerk_b"),
    )
    resp = client.post(
        "/auth/activate",
        json={"token": "tok", "password": "umaSenha123", "telefone": "(11) 98888-7777"},
    )
    assert resp.status_code == 200
    assert invited.clerk_user_id == "clerk_b"
    assert invited.status == "ativo"
    # O convite legado continua ativando, mas acesso e membresia são superfícies
    # separadas: não reaproveita a célula pendente nem cria CelulaMembro.
    assert len(session.added) == 1
    nova = next(o for o in session.added if isinstance(o, Pessoa))
    assert nova.tipo == "membro"
    assert nova.celula_id is None
    assert invited.pessoa_id == nova.id
    assert invited.celula_pendente_id is None


def test_activate_parte_b_persists_link_before_locked_reload(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prova a regressão de SessionLocal(autoflush=False) com Session real.

    A preparação escreve os atributos apenas na instância ORM. A releitura com
    ``populate_existing`` restaura os valores antigos se ``activate`` não fizer
    flush explícito antes do lock.
    """

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _sqlite_functions(dbapi_connection, _connection_record) -> None:
        dbapi_connection.create_function(
            "now", 0, lambda: dt.datetime.now(dt.timezone.utc).isoformat()
        )
        dbapi_connection.create_function(
            "gen_random_uuid", 0, lambda: uuid.uuid4().hex
        )

    Base.metadata.create_all(
        engine,
        tables=[
            Igreja.__table__,
            Pessoa.__table__,
            AppUser.__table__,
            UserRole.__table__,
            Celula.__table__,
        ],
    )
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )
    session = factory()
    try:
        # Inclui dígito hexadecimal alfabético para o SQLite preservar TEXT;
        # UUIDs só numéricos recebem afinidade NUMERIC nesse dialeto de teste.
        igreja_id = uuid.UUID("00000000-0000-0000-0000-00000000001a")
        session.add(Igreja(id=igreja_id, nome="Igreja", status="ativa"))
        session.flush()
        session.add(
            AppUser(
                id=uuid.UUID(_AID),
                igreja_id=igreja_id,
                pessoa_id=None,
                celula_pendente_id=uuid.UUID(_CELULA_ID),
                nome="Convite Parte B",
                email="parte-b@igreja.org",
                status="convidado",
            )
        )
        session.commit()

        created_person_id = uuid.UUID("00000000-0000-0000-0000-0000000000f1")

        def _prepare_without_implicit_flush(
            db, app_user, telefone_raw: str, normalized: str
        ) -> None:
            pessoa = Pessoa(
                id=created_person_id,
                igreja_id=igreja_id,
                nome=app_user.nome,
                telefone=telefone_raw,
                email=app_user.email,
                tipo="membro",
            )
            db.add(pessoa)
            db.flush()  # como insert_pessoa_or_get_winner: só Pessoa já existe
            app_user.pessoa_id = pessoa.id
            app_user.celula_pendente_id = None

        monkeypatch.setattr(
            auth_router, "_prepare_cadastro_pessoa", _prepare_without_implicit_flush
        )
        monkeypatch.setattr(
            auth_router, "sync_role_after_activation", lambda db, app_user: None
        )
        client = _wire(
            app,
            session=session,
            clerk=FakeClerk(
                invite_app_user_id=_AID,
                created_clerk_id="clerk_real_session",
            ),
        )

        resp = client.post(
            "/auth/activate",
            json={
                "token": "tok",
                "password": "umaSenha123",
                "telefone": "(11) 98888-7766",
            },
        )

        assert resp.status_code == 200, resp.text
        session.expire_all()
        persisted = session.get(AppUser, uuid.UUID(_AID))
        assert persisted is not None
        assert persisted.pessoa_id == created_person_id
        assert persisted.celula_pendente_id is None
        assert persisted.clerk_user_id == "clerk_real_session"
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("tipo", ["membro", "pastor", "lider"])
def test_activate_parte_b_rejects_existing_identity_by_phone_before_clerk(
    app, tipo
) -> None:
    # Telefone auto-declarado não prova que o destinatário é esta Pessoa.
    existing = SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000e5",
        telefone="11988887777",
        celula_id=None,
        tipo=tipo,
    )
    invited = make_invited(pessoa_id=None, celula_pendente_id=_CELULA_ID)
    celula = SimpleNamespace(id=_CELULA_ID, igreja_id=invited.igreja_id)
    session = InviteSession(invited, pessoas=[existing], celula=celula)
    clerk = FakeClerk(invite_app_user_id=_AID, created_clerk_id="clerk_dedup")
    client = _wire(
        app,
        session=session,
        clerk=clerk,
    )
    resp = client.post(
        "/auth/activate",
        json={"token": "tok", "password": "umaSenha123", "telefone": "(11) 98888-7777"},
    )
    assert resp.status_code == 409
    assert existing.celula_id is None
    assert invited.pessoa_id is None
    assert invited.celula_pendente_id == _CELULA_ID
    assert session.added == []
    assert session.rolled_back is True
    assert clerk.create_calls == 0


def test_activate_parte_b_existing_cell_identity_is_not_adopted(app) -> None:
    existing = SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000e6",
        telefone="11988887777",
        celula_id="00000000-0000-0000-0000-0000000000c9",
    )
    invited = make_invited(pessoa_id=None, celula_pendente_id=_CELULA_ID)
    session = InviteSession(invited, pessoas=[existing])
    clerk = FakeClerk(invite_app_user_id=_AID, created_clerk_id="clerk_dedup2")
    client = _wire(
        app,
        session=session,
        clerk=clerk,
    )
    resp = client.post(
        "/auth/activate",
        json={"token": "tok", "password": "umaSenha123", "telefone": "(11) 98888-7777"},
    )
    assert resp.status_code == 409
    assert existing.celula_id == "00000000-0000-0000-0000-0000000000c9"
    assert invited.pessoa_id is None
    assert invited.celula_pendente_id == _CELULA_ID
    assert session.added == []
    assert clerk.create_calls == 0


def test_activate_parte_b_archived_phone_is_not_recreated(app) -> None:
    archived = SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000e7",
        igreja_id="00000000-0000-0000-0000-000000000001",
        telefone="11988887777",
        celula_id=None,
        arquivada_em="2026-08-11T12:00:00Z",
    )
    invited = make_invited(pessoa_id=None)
    session = InviteSession(invited, pessoas=[archived])
    clerk = FakeClerk(invite_app_user_id=_AID)

    resp = _wire(app, session=session, clerk=clerk).post(
        "/auth/activate",
        json={
            "token": "tok",
            "password": "umaSenha123",
            "telefone": "(11) 98888-7777",
        },
    )

    assert resp.status_code == 409
    assert invited.pessoa_id is None
    assert session.added == []
    assert session.rolled_back is True
    assert clerk.create_calls == 0


def test_activate_parte_b_rejects_concurrent_dedup_winner_before_clerk(
    app, monkeypatch
) -> None:
    invited = make_invited(pessoa_id=None)
    session = InviteSession(invited, pessoas=[])
    winner = SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000ef",
        igreja_id=invited.igreja_id,
        telefone="11988887777",
        celula_id=None,
    )
    monkeypatch.setattr(
        "app.routers.auth.insert_pessoa_or_get_winner",
        lambda *_args, **_kwargs: winner,
    )
    clerk = FakeClerk(invite_app_user_id=_AID)

    resp = _wire(app, session=session, clerk=clerk).post(
        "/auth/activate",
        json={
            "token": "tok",
            "password": "umaSenha123",
            "telefone": "(11) 98888-7777",
        },
    )

    assert resp.status_code == 409
    assert invited.pessoa_id is None
    assert clerk.create_calls == 0
    assert session.rolled_back is True
