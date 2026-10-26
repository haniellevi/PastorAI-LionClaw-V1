"""Baixa de alerta pastoral segue a mesma regra da leitura, em PG real com RLS.

Identidade real: token de sessão sintético assinado pelo ClerkClient, linha em
auth_sessions, get_current_user e papéis acumulados de user_roles. Somente o
segredo do ClerkClient é sintético; get_db entrega sessão não escopada como em
produção e o próprio get_current_user aplica o tenant.
"""

from __future__ import annotations

import os
import time
from uuid import UUID, uuid4
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import CurrentUser
from app.routers import cells
from app.services.clerk import ClerkClient, get_clerk_client
from tests.conftest_rls import assert_disposable_database
from tests.test_uv_turmas_pg import database, migrated_database  # noqa: F401

pytestmark = [
    pytest.mark.rls_integration,
    pytest.mark.usefixtures("rls_database_url"),
]


@pytest.fixture(scope="module")
def rls_database_url():
    url = os.environ.get("UV_TURMAS_DATABASE_URL", "").strip()
    if not url:
        pytest.fail("Baixa de alerta exige PostgreSQL local sintético via UV_TURMAS_DATABASE_URL; nenhum skip permitido")
    assert_disposable_database(url)
    parsed = urlsplit(url)
    if (
        parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.path != "/uv_turmas_test"
    ):
        pytest.fail("Use somente o PostgreSQL local descartável uv_turmas_test")
    return url


class _Settings:
    effective_session_secret = "synthetic-cell-alert-secret-only"
    session_ttl_hours = 8


# Chave do ator -> (papéis acumulados, chave da Pessoa vinculada ou None).
ACTORS = {
    "lider": (("lider_celula",), "lider"),
    "lider_acumulado": (("lider_celula", "lider_g12"), "lider_b"),
    "g12": (("lider_g12",), "g12"),
    "topo": (("lider_celula",), "topo"),
    "g12_acumulado": (("lider_celula", "lider_g12"), "g12_b"),
    "pastor": (("pastor",), None),
    "admin": (("admin",), None),
    "membro": (("membro",), "membro"),
    "fora": (("membro",), "fora"),
    "sem_pessoa": (("lider_celula",), None),
}


def _insert_pessoa(c, tenant, lider_id=None):
    pid = uuid4()
    c.execute(
        text("insert into pessoas(id,igreja_id,nome,telefone,lider_id) values(:p,:t,'Pessoa sintética',:f,:l)"),
        dict(p=pid, t=tenant, f="55" + str(pid.int)[:11], l=lider_id),
    )
    return pid


def _insert_cell(c, tenant, lider_id):
    cid = uuid4()
    c.execute(
        text("insert into celulas(id,igreja_id,nome,lider_id,cobertura_espiritual) values(:c,:t,'Célula sintética',:l,'Cobertura sintética')"),
        dict(c=cid, t=tenant, l=lider_id),
    )
    return cid


def _insert_alert(c, tenant, cell, pessoa):
    aid = uuid4()
    c.execute(
        text("insert into cell_alerts(id,igreja_id,celula_id,pessoa_id,gatilho,acao_esperada) values(:a,:t,:c,:p,'gatilho sintético','ação sintética')"),
        dict(a=aid, t=tenant, c=cell, p=pessoa),
    )
    return aid


@pytest.fixture
def world(database):
    """Igreja A: topo -> g12 -> lider -> célula C; igreja B com alerta próprio."""
    t, b = uuid4(), uuid4()
    p, users = {}, {}
    with database.begin() as c:
        for tenant in (t, b):
            c.execute(text("insert into igrejas(id,nome) values(:t,'Igreja sintética')"), dict(t=tenant))
        p["topo"] = _insert_pessoa(c, t)
        p["g12"] = _insert_pessoa(c, t, p["topo"])
        p["g12_b"] = _insert_pessoa(c, t)
        p["lider"] = _insert_pessoa(c, t, p["g12"])
        p["lider_b"] = _insert_pessoa(c, t, p["g12_b"])
        p["membro"] = _insert_pessoa(c, t, p["lider"])
        p["fora"] = _insert_pessoa(c, t)
        p["outro_lider"] = _insert_pessoa(c, t)
        cell = _insert_cell(c, t, p["lider"])
        cell_b_leader = _insert_cell(c, t, p["lider_b"])
        other_cell = _insert_cell(c, t, p["outro_lider"])
        c.execute(
            text("insert into celula_membro(igreja_id,celula_id,pessoa_id,papel) values(:t,:c,:p,'membro')"),
            dict(t=t, c=cell, p=p["membro"]),
        )
        alert = _insert_alert(c, t, cell, p["membro"])
        sibling = _insert_alert(c, t, cell, p["membro"])
        other_alert = _insert_alert(c, t, other_cell, p["outro_lider"])
        alert_b_leader = _insert_alert(c, t, cell_b_leader, p["lider_b"])
        foreign_person = _insert_pessoa(c, b)
        foreign_cell = _insert_cell(c, b, foreign_person)
        foreign_alert = _insert_alert(c, b, foreign_cell, foreign_person)
        for key, (roles, pessoa_key) in ACTORS.items():
            uid, sub = uuid4(), f"cell-alert-{key}-{uuid4().hex[:8]}"
            c.execute(
                text("insert into app_users(id,igreja_id,clerk_user_id,pessoa_id,status,nome,email) values(:u,:t,:s,:p,'ativo','Equipe sintética','synthetic@example.test')"),
                dict(u=uid, t=t, s=sub, p=p.get(pessoa_key) if pessoa_key else None),
            )
            for role in roles:
                c.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:t,:u,:r)"), dict(t=t, u=uid, r=role))
            users[key] = (uid, sub)
    clerk = ClerkClient(_Settings())
    tokens = {}
    with database.begin() as c:
        for key, (uid, sub) in users.items():
            token = clerk._mint_session_token(sub)  # noqa: SLF001
            jti = clerk.verify_session_token(token).claims["jti"]
            now = int(time.time())
            c.execute(
                text("insert into auth_sessions(jti,igreja_id,app_user_id,issued_at,expires_at) values(:j,:t,:u,to_timestamp(:i),to_timestamp(:i + 3600))"),
                dict(j=jti, t=t, u=uid, i=now),
            )
            tokens[key] = token

    app = FastAPI()
    app.include_router(cells.router)

    def db_override():
        session = Session(database)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    with TestClient(app) as client:
        yield dict(
            db=database, client=client, tokens=tokens, users=users, t=t, b=b,
            cell=cell, cell_b_leader=cell_b_leader, other_cell=other_cell,
            alert=alert, sibling=sibling, other_alert=other_alert,
            alert_b_leader=alert_b_leader, foreign_cell=foreign_cell,
            foreign_alert=foreign_alert, foreign_person=foreign_person, p=p,
        )


def _as(w, actor):
    return {"Authorization": f"Bearer {w['tokens'][actor]}"}


def _baixar(w, actor, cell, alert):
    return w["client"].post(f"/cells/{cell}/alerts/{alert}/baixar", headers=_as(w, actor))


def _tratados(w):
    with w["db"].connect() as c:
        return dict(c.execute(text("select id, tratado from cell_alerts")).all())


@pytest.mark.parametrize("actor", ["lider", "pastor", "admin"])
def test_authorized_baixa_persists_and_repeat_has_no_extra_effect(world, actor):
    w = world
    before = _tratados(w)
    response = _baixar(w, actor, w["cell"], w["alert"])
    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(w["alert"]) and response.json()["tratado"] is True
    after = _tratados(w)
    assert after == {**before, w["alert"]: True}

    detail = w["client"].get(f"/cells/{w['cell']}", headers=_as(w, actor))
    assert detail.status_code == 200
    assert [a["id"] for a in detail.json()["alerts"]] == [str(w["sibling"])]

    again = _baixar(w, actor, w["cell"], w["alert"])
    assert again.status_code == 200 and again.json()["tratado"] is True
    assert _tratados(w) == after


def test_accumulated_roles_direct_leader_can_baixar(world):
    w = world
    before = _tratados(w)
    response = _baixar(w, "lider_acumulado", w["cell_b_leader"], w["alert_b_leader"])
    assert response.status_code == 200, response.text
    assert _tratados(w) == {**before, w["alert_b_leader"]: True}


@pytest.mark.parametrize(
    ("actor", "cell_key", "alert_key", "read_status", "status"),
    [
        # lider_g12 superior: vê o cadastro da célula sem os alertas.
        ("g12", "cell", "alert", 200, 403),
        # Superior acumulando lider_celula + lider_g12, mas não líder direto.
        ("g12_acumulado", "cell_b_leader", "alert_b_leader", 200, 403),
        # Superior só lider_celula: leitura da célula já é 404.
        ("topo", "cell", "alert", 404, 404),
        ("membro", "cell", "alert", 200, 403),
        ("fora", "cell", "alert", 404, 404),
        ("sem_pessoa", "cell", "alert", 404, 404),
    ],
)
def test_baixa_refused_to_whoever_cannot_read_alerts(world, actor, cell_key, alert_key, read_status, status):
    w = world
    before = _tratados(w)
    detail = w["client"].get(f"/cells/{w[cell_key]}", headers=_as(w, actor))
    assert detail.status_code == read_status
    if read_status == 200:
        assert detail.json()["alerts"] == []

    response = _baixar(w, actor, w[cell_key], w[alert_key])
    assert response.status_code == status, response.text
    assert str(w[alert_key]) not in response.text
    assert "pessoaId" not in response.text
    assert _tratados(w) == before


@pytest.mark.parametrize(
    ("actor", "cell_key", "alert_key"),
    [
        ("lider", "cell", "other_alert"),
        ("lider", "cell", "foreign_alert"),
        ("lider", "foreign_cell", "foreign_alert"),
        ("pastor", "cell", "other_alert"),
        ("pastor", "cell", "foreign_alert"),
        ("pastor", "foreign_cell", "foreign_alert"),
        ("admin", "foreign_cell", "foreign_alert"),
    ],
)
def test_alert_of_other_cell_or_church_is_404(world, actor, cell_key, alert_key):
    w = world
    before = _tratados(w)
    response = _baixar(w, actor, w[cell_key], w[alert_key])
    assert response.status_code == 404, response.text
    assert _tratados(w) == before


@pytest.mark.parametrize("path", ["/cells/nao-uuid/alerts/{alert}/baixar", "/cells/{cell}/alerts/nao-uuid/baixar", "/cells/{cell}/alerts/{random}/baixar"])
def test_invalid_or_unknown_ids_are_404(world, path):
    w = world
    before = _tratados(w)
    url = path.format(alert=w["alert"], cell=w["cell"], random=uuid4())
    response = w["client"].post(url, headers=_as(w, "lider"))
    assert response.status_code == 404, response.text
    assert _tratados(w) == before


def test_application_guard_ignores_forged_cross_church_alert_without_rls(world):
    """A FK simples admite alerta da igreja B apontando para a célula A.

    Só como superusuário sintético (sem RLS) a linha forjada fica visível; o
    envelope CurrentUser aqui não prova autenticação, apenas o filtro explícito
    de igreja na projeção e na baixa, independente da RLS.
    """
    w = world
    with w["db"].begin() as c:
        forged = _insert_alert(c, w["b"], w["cell"], w["foreign_person"])
    uid, sub = w["users"]["pastor"]
    pastor = CurrentUser(
        app_user_id=str(uid), clerk_user_id=sub, igreja_id=str(w["t"]),
        email="synthetic@example.test", nome="Pastor sintético", roles=frozenset({"pastor"}),
    )
    before = _tratados(w)
    with Session(w["db"]) as db:
        assert db.execute(text("select rolbypassrls from pg_roles where rolname=current_user")).scalar_one() is True
        detail = cells.get_cell(str(w["cell"]), db=db, current_user=pastor)
        assert {a.id for a in detail.alerts} == {str(w["alert"]), str(w["sibling"])}
        with pytest.raises(HTTPException) as exc:
            cells.baixar_alert(str(w["cell"]), str(forged), db=db, current_user=pastor)
        assert exc.value.status_code == 404
    assert _tratados(w) == before
    assert UUID(str(forged)) in before and before[forged] is False
