"""Visão geral do dashboard (#2): escopo por papel + normalização das contagens.

Cobre o domínio puro (has_full_overview, normalize_counts) e a GARANTIA de
escopo no endpoint: quem não tem visão completa e não lidera células recebe
zeros (não vaza os totais da igreja).
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    Base,
    Celula,
    CelulaMembro,
    Pessoa,
    RolePermission,
    UserRole,
)
from app.db.session import get_db
from app.deps import CurrentUser
from app.domain.dashboard_overview import (
    ETAPA_BUCKETS,
    TIPO_BUCKETS,
    has_full_overview,
    normalize_counts,
)
from app.routers.dashboard import OverviewOut, overview
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_OVERVIEW = "/dashboard/overview"


# ---- domínio puro ---------------------------------------------------------
def test_has_full_overview_admin_pastor_and_senior() -> None:
    assert has_full_overview(["admin"]) is True
    assert has_full_overview(["pastor"]) is True
    assert has_full_overview(["lider_g12"]) is True
    assert has_full_overview(["lider_consol"]) is True


def test_has_full_overview_scoped_roles() -> None:
    # Só admin/pastor/G12/consolidação veem tudo; os demais caem no escopo célula.
    assert has_full_overview(["lider_celula"]) is False
    assert has_full_overview(["lider_mult"]) is False
    assert has_full_overview(["operador"]) is False
    assert has_full_overview(["membro"]) is False
    assert has_full_overview([]) is False
    # Papel acumulado sênior amplia: célula + g12 => visão completa.
    assert has_full_overview(["lider_celula", "lider_g12"]) is True


def test_normalize_counts_fills_buckets_and_ignores_unknown() -> None:
    out = normalize_counts({"visitante": 3, "sem_interesse": 1, "xpto": 9}, TIPO_BUCKETS)
    assert out["visitante"] == 3
    assert out["sem_interesse"] == 1
    assert out["contato"] == 0  # bucket ausente vira 0
    assert "xpto" not in out  # chave estranha é ignorada
    etapa = normalize_counts({"ganhar": 5}, ETAPA_BUCKETS)
    assert etapa == {"ganhar": 5, "consolidar": 0, "discipular": 0, "enviar": 0}


# ---- endpoint: garantia de escopo (zeros para quem não deve ver) ----------
class _Res:
    def __init__(self, *, scalar=None, scalars=None, rows=None, mapping=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []
        self._rows = rows or []
        self._mapping = mapping

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def all(self):
        return list(self._rows)

    def unique(self):
        return self

    def mappings(self):
        return self

    def one(self):
        return self._mapping

    def one_or_none(self):
        return self._mapping


class DashboardSession:
    """Roteia auth + lookups do overview. Foca nos caminhos de escopo vazio."""

    def __init__(self, *, app_user, roles, pessoa_id=None, cell_ids=None) -> None:
        self.app_user = app_user
        self.roles = roles
        self.pessoa_id = pessoa_id
        self.cell_ids = cell_ids or []

    def execute(self, statement, params=None) -> _Res:
        sql = str(statement)
        if "count(" in sql.lower() and "FROM pessoas" in sql:
            return _Res(
                mapping={
                    "total": 0,
                    "decisoes_jesus": 0,
                    "sem_interesse": 0,
                    **{f"tipo_{bucket}": 0 for bucket in TIPO_BUCKETS},
                    **{f"etapa_{bucket}": 0 for bucket in ETAPA_BUCKETS},
                }
            )
        if "count(" in sql.lower() and "FROM celulas" in sql:
            return _Res(mapping={"ativas": 0, "lideres": 0})
        descs = list(getattr(statement, "column_descriptions", []) or [])
        if not descs:
            return _Res()
        d0 = descs[0]
        ent = d0.get("entity")
        name = d0.get("name")
        if ent is AppUser:
            # select(AppUser) (auth) vs select(AppUser.pessoa_id) (escopo).
            if name == "pessoa_id":
                return _Res(
                    mapping={
                        "pessoa_id": self.pessoa_id,
                        "has_cells": bool(self.cell_ids),
                    }
                )
            self.app_user.roles = [SimpleNamespace(papel=role) for role in self.roles]
            return _Res(scalar=self.app_user)
        if ent is RolePermission:
            return _Res(rows=[])  # matriz vazia => defaults (dashboard sempre ok)
        if ent is UserRole:
            return _Res(scalars=self.roles)
        if ent is Celula and name == "id":
            return _Res(scalars=self.cell_ids)
        return _Res()

    def commit(self) -> None:  # pragma: no cover
        pass

    def close(self) -> None:  # pragma: no cover
        pass


def _wire(app, session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def _assert_empty(body: dict) -> None:
    assert body["scope"] == "celula"
    assert body["total"] == 0
    assert body["decisoesJesus"] == 0
    assert body["celulasAtivas"] == 0
    assert body["lideresCelula"] == 0
    assert body["semInteresse"] == 0
    assert set(body["porTipo"]) == set(TIPO_BUCKETS)
    assert all(v == 0 for v in body["porTipo"].values())
    assert all(v == 0 for v in body["porEtapa"].values())


def test_overview_cell_leader_without_linked_pessoa_is_empty(app) -> None:
    session = DashboardSession(
        app_user=make_app_user(), roles=["lider_celula"], pessoa_id=None
    )
    resp = _wire(app, session).get(_OVERVIEW, headers=_AUTH)
    assert resp.status_code == 200
    _assert_empty(resp.json())


def test_overview_cell_leader_without_cells_is_empty(app) -> None:
    session = DashboardSession(
        app_user=make_app_user(),
        roles=["lider_celula"],
        pessoa_id="00000000-0000-0000-0000-0000000000f1",
        cell_ids=[],
    )
    resp = _wire(app, session).get(_OVERVIEW, headers=_AUTH)
    assert resp.status_code == 200
    _assert_empty(resp.json())


def test_overview_member_is_empty(app) -> None:
    # membro não tem visão completa nem lidera células => zeros (sem vazamento).
    session = DashboardSession(
        app_user=make_app_user(), roles=["membro"], pessoa_id=None
    )
    resp = _wire(app, session).get(_OVERVIEW, headers=_AUTH)
    assert resp.status_code == 200
    _assert_empty(resp.json())


def _current_user(
    *, app_user_id: uuid.UUID, igreja_id: uuid.UUID, roles: set[str]
) -> CurrentUser:
    return CurrentUser(
        app_user_id=str(app_user_id),
        clerk_user_id="clerk_overview_test",
        igreja_id=str(igreja_id),
        email="overview@example.com",
        nome="Overview Test",
        roles=frozenset(roles),
    )


def _configure_sqlite(dbapi_connection, _record) -> None:
    dbapi_connection.create_function("now", 0, lambda: "2026-08-08 00:00:00")
    dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)


def _overview_db() -> tuple[Session, Engine, uuid.UUID, uuid.UUID]:
    """SQLite real para validar a equivalência do SQL agregado offline."""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    event.listen(engine, "connect", _configure_sqlite)
    Base.metadata.create_all(
        engine,
        tables=[
            Pessoa.__table__,
            Celula.__table__,
            CelulaMembro.__table__,
            AppUser.__table__,
        ],
    )
    session = Session(engine, expire_on_commit=False)
    igreja_id = uuid.uuid4()
    leader_id = uuid.uuid4()
    cell_a = uuid.uuid4()
    cell_b = uuid.uuid4()
    inactive_cell = uuid.uuid4()
    visitor_id = uuid.uuid4()
    csim_id = uuid.uuid4()
    inactive_membership_id = uuid.uuid4()
    inactive_cell_member_id = uuid.uuid4()
    archived_id = uuid.uuid4()
    session.add_all(
        [
            Pessoa(
                id=leader_id,
                igreja_id=igreja_id,
                nome="Lider",
                telefone="551100000001",
                tipo=None,
                etapa=None,
                celula_id=cell_a,
                aceitou_jesus=True,
                sem_interesse=False,
            ),
            Pessoa(
                id=visitor_id,
                igreja_id=igreja_id,
                nome="Visitante",
                telefone="551100000002",
                tipo="visitante",
                etapa="consolidar",
                celula_id=cell_a,
                sem_interesse=False,
            ),
            Pessoa(
                id=csim_id,
                igreja_id=igreja_id,
                nome="CSIM",
                telefone="551100000003",
                tipo="visitante",
                etapa="enviar",
                celula_id=cell_a,
                aceitou_jesus=True,
                sem_interesse=True,
            ),
            Pessoa(
                id=inactive_membership_id,
                igreja_id=igreja_id,
                nome="Vinculo inativo",
                telefone="551100000004",
                tipo="membro",
                etapa="enviar",
                celula_id=cell_b,
                sem_interesse=False,
            ),
            Pessoa(
                id=inactive_cell_member_id,
                igreja_id=igreja_id,
                nome="Lider dois",
                telefone="551100000005",
                tipo="lider",
                etapa="discipular",
                celula_id=cell_b,
                sem_interesse=False,
            ),
            Pessoa(
                id=archived_id,
                igreja_id=igreja_id,
                nome="Pessoa arquivada",
                telefone="551100000007",
                tipo="discipulo",
                etapa="enviar",
                celula_id=cell_a,
                sem_interesse=False,
                arquivada_em=dt.datetime(2026, 8, 1, tzinfo=dt.UTC),
            ),
            Pessoa(
                igreja_id=igreja_id,
                nome="Sem celula",
                telefone="551100000006",
                tipo="pastor",
                etapa="enviar",
                celula_id=None,
                sem_interesse=False,
            ),
            Celula(
                id=cell_a,
                igreja_id=igreja_id,
                nome="Celula A",
                lider_id=leader_id,
                cobertura_espiritual="Cobertura",
                ativo=True,
            ),
            Celula(
                id=cell_b,
                igreja_id=igreja_id,
                nome="Celula B",
                lider_id=leader_id,
                cobertura_espiritual="Cobertura",
                ativo=True,
            ),
            Celula(
                id=inactive_cell,
                igreja_id=igreja_id,
                nome="Celula inativa",
                lider_id=leader_id,
                cobertura_espiritual="Cobertura",
                ativo=False,
            ),
            # Fonte canônica do escopo do líder. Os espelhos Pessoa.celula_id
            # acima permanecem deliberadamente divergentes para provar que o
            # overview não volta a depender deles.
            CelulaMembro(
                igreja_id=igreja_id,
                celula_id=cell_a,
                pessoa_id=leader_id,
                ativo=True,
            ),
            CelulaMembro(
                igreja_id=igreja_id,
                celula_id=cell_a,
                pessoa_id=visitor_id,
                ativo=True,
            ),
            CelulaMembro(
                igreja_id=igreja_id,
                celula_id=cell_a,
                pessoa_id=csim_id,
                ativo=True,
            ),
            CelulaMembro(
                igreja_id=igreja_id,
                celula_id=cell_b,
                pessoa_id=inactive_membership_id,
                ativo=False,
            ),
            CelulaMembro(
                igreja_id=igreja_id,
                celula_id=inactive_cell,
                pessoa_id=inactive_cell_member_id,
                ativo=True,
            ),
            CelulaMembro(
                igreja_id=igreja_id,
                celula_id=cell_a,
                pessoa_id=archived_id,
                ativo=True,
            ),
        ]
    )
    session.commit()
    return session, engine, leader_id, igreja_id


def test_overview_aggregates_preserve_response_with_two_executes() -> None:
    session, engine, _leader_id, igreja_id = _overview_db()
    app_user_id = uuid.uuid4()
    statements: list[str] = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda _conn, _cursor, statement, _params, _ctx, _many: statements.append(
            statement
        ),
    )

    result = overview(
        session,
        _current_user(
            app_user_id=app_user_id, igreja_id=igreja_id, roles={"admin"}
        ),
    )

    assert result.model_dump() == {
        "scope": "igreja",
        "total": 6,
        "decisoesJesus": 2,
        "celulasAtivas": 2,
        "lideresCelula": 1,
        "semInteresse": 1,
        "porTipo": {
            "contato": 1,
            "visitante": 1,
            "discipulo": 0,
            "membro": 1,
            "lider": 1,
            "pastor": 1,
            "sem_interesse": 1,
        },
        "porEtapa": {
            "ganhar": 1,
            "consolidar": 1,
            "discipular": 1,
            "enviar": 2,
        },
    }
    assert len(statements) == 2
    session.close()


def test_overview_cell_scope_uses_only_active_canonical_memberships() -> None:
    session, engine, leader_id, igreja_id = _overview_db()
    app_user_id = uuid.uuid4()
    session.add(
        AppUser(
            id=app_user_id,
            igreja_id=igreja_id,
            pessoa_id=leader_id,
            nome="Lider",
            email="lider@example.com",
        )
    )
    session.commit()
    statements: list[str] = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda _conn, _cursor, statement, _params, _ctx, _many: statements.append(
            statement
        ),
    )

    result = overview(
        session,
        _current_user(
            app_user_id=app_user_id,
            igreja_id=igreja_id,
            roles={"lider_celula"},
        ),
    )

    assert result.scope == "celula"
    # Inclui líder, visitante e CSIM com vínculo ativo em célula ativa.
    assert result.total == 3
    # Exclui vínculo inativo apesar do espelho legado apontar para cell_b.
    assert result.porTipo["membro"] == 0
    # Exclui vínculo ativo em célula inativa.
    assert result.porTipo["lider"] == 0
    # Exclui pessoa arquivada mesmo com vínculo ativo em célula ativa.
    assert result.porTipo["discipulo"] == 0
    assert result.celulasAtivas == 2
    assert result.lideresCelula == 1
    assert result.porTipo["pastor"] == 0
    assert result.porEtapa["enviar"] == 0
    assert len(statements) == 3
    session.close()


def test_overview_cell_scope_without_led_active_cells_is_empty() -> None:
    session, _engine, _leader_id, igreja_id = _overview_db()
    app_user_id = uuid.uuid4()
    session.add(
        AppUser(
            id=app_user_id,
            igreja_id=igreja_id,
            pessoa_id=uuid.uuid4(),
            nome="Sem celulas",
            email="sem-celulas@example.com",
        )
    )
    session.commit()

    result = overview(
        session,
        _current_user(
            app_user_id=app_user_id,
            igreja_id=igreja_id,
            roles={"lider_celula"},
        ),
    )

    assert result == OverviewOut.empty("celula")
    session.close()
