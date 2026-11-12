"""RF-26 em PG real com RLS: configuração pelo admin, geração idempotente e
visibilidade só para o líder direto (outra célula e outra igreja não veem).

Identidade real como em ``test_cell_alerts_baixa_pg``: token de sessão
sintético, ``auth_sessions`` e papéis de ``user_roles``. O ciclo do cron usa a
mesma marcação de tenant da produção (papel ``authenticated`` + GUC), sem
BYPASSRLS. Todos os dados são sintéticos.
"""

from __future__ import annotations

import datetime as dt
import time
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import CelulaAlertaRegra
from app.db.session import get_db
from app.db.tenant_session import mark_tenant_scoped
from app.routers import cell_alert_rules, cells
from app.services import cell_alert_rules as svc
from app.services.clerk import ClerkClient, get_clerk_client
from tests.test_cell_alerts_baixa_pg import (  # noqa: F401
    _insert_cell,
    _insert_pessoa,
    _Settings,
    rls_database_url,
)
from tests.test_uv_turmas_pg import database, migrated_database  # noqa: F401

pytestmark = [
    pytest.mark.rls_integration,
    pytest.mark.usefixtures("rls_database_url"),
]

NOW = dt.datetime(2026, 11, 12, 15, 0, tzinfo=dt.timezone.utc)
TODAY = dt.date(2026, 11, 12)

ACTORS = {
    "admin": (("admin",), None, "t"),
    "pastor": (("pastor",), None, "t"),
    "lider": (("lider_celula",), "lider", "t"),
    "lider2": (("lider_celula",), "lider2", "t"),
    "admin_b": (("admin",), None, "b"),
    "lider_b": (("lider_celula",), "lider_b", "b"),
}


def _seed_cell_world(c, tenant, lider):
    """Célula com: membro em consolidação (prazo em 10h), visitante recente,
    reunião passada sem relatório e 2 membros ativos."""
    cell = _insert_cell(c, tenant, lider)
    membro = _insert_pessoa(c, tenant, lider)
    outro = _insert_pessoa(c, tenant, lider)
    for p in (membro, outro):
        c.execute(
            text("insert into celula_membro(igreja_id,celula_id,pessoa_id,papel) values(:t,:c,:p,'membro')"),
            dict(t=tenant, c=cell, p=p),
        )
    c.execute(
        text(
            "insert into consolidacoes(id,igreja_id,pessoa_id,tipo,progresso,concluida,prazo_conexao)"
            " values(:i,:t,:p,'individual',10,false,:prazo)"
        ),
        dict(i=(consolidacao := uuid4()), t=tenant, p=membro, prazo=NOW + dt.timedelta(hours=10)),
    )
    # Tarefa canônica de conexão ainda aberta (o prazo só vale enquanto ela existir).
    c.execute(
        text(
            "insert into work_queue_items(igreja_id,tipo,titulo,pessoa_id,consolidacao_id,status)"
            " values(:t,'conectar_celula','Conectar à célula',:p,:i,'aberto')"
        ),
        dict(t=tenant, p=membro, i=consolidacao),
    )
    reuniao = uuid4()
    c.execute(
        text("insert into celula_reuniao(id,igreja_id,celula_id,data,hora) values(:r,:t,:c,:d,'19:00')"),
        dict(r=reuniao, t=tenant, c=cell, d=TODAY - dt.timedelta(days=3)),
    )
    c.execute(
        text("insert into celula_visitante(igreja_id,reuniao_id,nome_visitante) values(:t,:r,'Visitante sintético')"),
        dict(t=tenant, r=reuniao),
    )
    return cell, membro


@pytest.fixture
def world(database, monkeypatch):
    monkeypatch.delenv(svc.ENV_ALLOWLIST, raising=False)
    t, b = uuid4(), uuid4()
    p, users = {}, {}
    with database.begin() as c:
        for tenant in (t, b):
            c.execute(text("insert into igrejas(id,nome) values(:t,'Igreja sintética')"), dict(t=tenant))
        p["lider"] = _insert_pessoa(c, t)
        p["lider2"] = _insert_pessoa(c, t)
        p["lider_b"] = _insert_pessoa(c, b)
        cell, membro = _seed_cell_world(c, t, p["lider"])
        cell2, _ = _seed_cell_world(c, t, p["lider2"])
        cell_b, _ = _seed_cell_world(c, b, p["lider_b"])
        tenants = {"t": t, "b": b}
        for key, (roles, pessoa_key, tk) in ACTORS.items():
            uid, sub = uuid4(), f"rf26-{key}-{uuid4().hex[:8]}"
            c.execute(
                text("insert into app_users(id,igreja_id,clerk_user_id,pessoa_id,status,nome,email) values(:u,:t,:s,:p,'ativo','Equipe sintética','synthetic@example.test')"),
                dict(u=uid, t=tenants[tk], s=sub, p=p.get(pessoa_key) if pessoa_key else None),
            )
            for role in roles:
                c.execute(text("insert into user_roles(igreja_id,user_id,papel) values(:t,:u,:r)"), dict(t=tenants[tk], u=uid, r=role))
            users[key] = (uid, sub, tenants[tk])
    clerk = ClerkClient(_Settings())
    tokens = {}
    with database.begin() as c:
        for key, (uid, sub, tenant) in users.items():
            token = clerk._mint_session_token(sub)  # noqa: SLF001
            jti = clerk.verify_session_token(token).claims["jti"]
            now = int(time.time())
            c.execute(
                text("insert into auth_sessions(jti,igreja_id,app_user_id,issued_at,expires_at) values(:j,:t,:u,to_timestamp(:i),to_timestamp(:i + 3600))"),
                dict(j=jti, t=tenant, u=uid, i=now),
            )
            tokens[key] = token

    app = FastAPI()
    app.include_router(cells.router)
    app.include_router(cell_alert_rules.router)

    def db_override():
        session = Session(database)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    with TestClient(app) as client:
        yield dict(db=database, client=client, tokens=tokens, t=t, b=b,
                   cell=cell, cell2=cell2, cell_b=cell_b, membro=membro, lider=p["lider"])


def _as(w, actor):
    return {"Authorization": f"Bearer {w['tokens'][actor]}"}


def _activate_all(w, actor):
    for tipo in svc.RULES:
        r = w["client"].put(f"/cell-alert-rules/{tipo}", json={"ativo": True, "parametros": {}}, headers=_as(w, actor))
        assert r.status_code == 200, r.text


def _cycle(w):
    return svc.run_cell_alert_cycle(lambda: Session(w["db"]), now=NOW)


def _alerts(w):
    with w["db"].connect() as c:
        return c.execute(
            text("select igreja_id, celula_id, regra_tipo, fato_chave, tratado from cell_alerts order by regra_tipo")
        ).all()


@pytest.mark.parametrize("table", ["celula_alerta_regras", "cell_alerts"])
def test_alert_tables_force_rls_and_narrow_grants(world, table):
    with world["db"].connect() as c:
        row = c.execute(text(
            "select relrowsecurity, relforcerowsecurity from pg_class where relname=:t"
        ), dict(t=table)).one()
        assert tuple(row) == (True, True)
        for role in ("anon", "service_role"):
            assert c.execute(text(
                "select has_table_privilege(:r, :t, 'select') or has_table_privilege(:r, :t, 'insert')"
                " or has_table_privilege(:r, :t, 'update') or has_table_privilege(:r, :t, 'delete')"
            ), dict(r=role, t=f"public.{table}")).scalar_one() is False
        assert c.execute(text(
            "select has_table_privilege('authenticated', :t, 'delete')"
        ), dict(t=f"public.{table}")).scalar_one() is False


def test_admin_configures_rules_others_refused(world):
    w = world
    r = w["client"].get("/cell-alert-rules", headers=_as(w, "admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["processamentoLiberado"] is False
    assert {x["tipo"] for x in body["regras"]} == set(svc.RULES)
    assert not any(x["ativo"] for x in body["regras"])

    for actor in ("lider", "pastor"):
        assert w["client"].get("/cell-alert-rules", headers=_as(w, actor)).status_code == 403
        assert w["client"].put(
            "/cell-alert-rules/meta_atingida", json={"ativo": True, "parametros": {}}, headers=_as(w, actor)
        ).status_code == 403

    ok = w["client"].put(
        "/cell-alert-rules/meta_atingida", json={"ativo": True, "parametros": {"meta_membros": 2}}, headers=_as(w, "admin")
    )
    assert ok.status_code == 200 and ok.json()["parametros"][0]["valor"] == 2
    bad = w["client"].put(
        "/cell-alert-rules/meta_atingida", json={"ativo": True, "parametros": {"meta_membros": 1}}, headers=_as(w, "admin")
    )
    assert bad.status_code == 422
    assert w["client"].put(
        "/cell-alert-rules/inexistente", json={"ativo": True}, headers=_as(w, "admin")
    ).status_code == 404

    # Admin da igreja B não vê a configuração da igreja A.
    rb = w["client"].get("/cell-alert-rules", headers=_as(w, "admin_b")).json()
    assert not any(x["ativo"] for x in rb["regras"])
    with Session(w["db"]) as s:
        mark_tenant_scoped(s, w["b"], source="test")
        assert s.execute(select(CelulaAlertaRegra)).scalars().all() == []


def test_gate_closed_generates_nothing(world):
    w = world
    _activate_all(w, "admin")
    assert _cycle(w) == 0
    assert _alerts(w) == []


def test_cycle_is_idempotent_scoped_and_survives_baixa(world, monkeypatch):
    w = world
    monkeypatch.setenv(svc.ENV_ALLOWLIST, f"{w['t']},{w['b']}")
    _activate_all(w, "admin")
    w["client"].put(
        "/cell-alert-rules/meta_atingida", json={"ativo": True, "parametros": {"meta_membros": 2}}, headers=_as(w, "admin")
    )
    assert w["client"].get("/cell-alert-rules", headers=_as(w, "admin")).json()["processamentoLiberado"] is True

    created = _cycle(w)
    rows = _alerts(w)
    # 5 regras x 2 células da igreja A; igreja B tem regras desligadas.
    assert created == 10 and len(rows) == 10
    assert {r.igreja_id for r in rows} == {w["t"]}
    assert {r.celula_id for r in rows} == {w["cell"], w["cell2"]}
    assert {r.regra_tipo for r in rows} == set(svc.RULES)

    assert _cycle(w) == 0 and len(_alerts(w)) == 10

    detail = w["client"].get(f"/cells/{w['cell']}", headers=_as(w, "lider")).json()
    assert len(detail["alerts"]) == 5
    meta = next(a for a in detail["alerts"] if a["gatilho"] == svc.RULES["meta_atingida"].titulo)
    assert meta["pessoaId"] is None
    consol = next(a for a in detail["alerts"] if a["gatilho"] == svc.RULES["liderado_em_consolidacao"].titulo)
    assert consol["pessoaId"] == str(w["membro"])
    assert "sintético" not in str(detail["alerts"])

    r = w["client"].post(f"/cells/{w['cell']}/alerts/{meta['id']}/baixar", headers=_as(w, "lider"))
    assert r.status_code == 200
    assert _cycle(w) == 0
    after = w["client"].get(f"/cells/{w['cell']}", headers=_as(w, "lider")).json()
    assert len(after["alerts"]) == 4


def test_leader_sees_only_own_cell_alerts(world, monkeypatch):
    w = world
    monkeypatch.setenv(svc.ENV_ALLOWLIST, f"{w['t']},{w['b']}")
    _activate_all(w, "admin")
    _activate_all(w, "admin_b")
    _cycle(w)
    assert {r.igreja_id for r in _alerts(w)} == {w["t"], w["b"]}

    own = w["client"].get(f"/cells/{w['cell']}", headers=_as(w, "lider"))
    assert own.status_code == 200 and len(own.json()["alerts"]) == 4  # meta 12 não atingida

    other = w["client"].get(f"/cells/{w['cell2']}", headers=_as(w, "lider"))
    assert other.status_code == 404 or other.json()["alerts"] == []
    foreign = w["client"].get(f"/cells/{w['cell_b']}", headers=_as(w, "lider"))
    assert foreign.status_code == 404
    foreign_b = w["client"].get(f"/cells/{w['cell']}", headers=_as(w, "lider_b"))
    assert foreign_b.status_code == 404
    own_b = w["client"].get(f"/cells/{w['cell_b']}", headers=_as(w, "lider_b"))
    assert own_b.status_code == 200 and len(own_b.json()["alerts"]) == 4

    pastor = w["client"].get(f"/cells/{w['cell2']}", headers=_as(w, "pastor"))
    assert pastor.status_code == 200 and len(pastor.json()["alerts"]) == 4

    with Session(w["db"]) as s:
        mark_tenant_scoped(s, w["t"], source="test")
        seen = s.execute(text("select distinct igreja_id from cell_alerts")).scalars().all()
    assert seen == [w["t"]]


def test_my_alerts_lists_only_direct_leader_cells(world, monkeypatch):
    w = world
    monkeypatch.setenv(svc.ENV_ALLOWLIST, f"{w['t']},{w['b']}")
    _activate_all(w, "admin")
    _activate_all(w, "admin_b")
    _cycle(w)

    mine = w["client"].get("/cells/me/alerts", headers=_as(w, "lider"))
    assert mine.status_code == 200, mine.text
    body = mine.json()
    assert len(body) == 4 and {a["celulaId"] for a in body} == {str(w["cell"])}

    other = w["client"].get("/cells/me/alerts", headers=_as(w, "lider2")).json()
    assert {a["celulaId"] for a in other} == {str(w["cell2"])}
    foreign = w["client"].get("/cells/me/alerts", headers=_as(w, "lider_b")).json()
    assert {a["celulaId"] for a in foreign} == {str(w["cell_b"])}
    # Sem Pessoa vinculada (admin/pastor sem célula própria): lista vazia.
    assert w["client"].get("/cells/me/alerts", headers=_as(w, "pastor")).json() == []

    first = body[0]
    r = w["client"].post(f"/cells/{first['celulaId']}/alerts/{first['id']}/baixar", headers=_as(w, "lider"))
    assert r.status_code == 200
    # Outro líder não baixa alerta da célula alheia.
    other_id = other[0]
    refused = w["client"].post(f"/cells/{other_id['celulaId']}/alerts/{other_id['id']}/baixar", headers=_as(w, "lider"))
    assert refused.status_code in (403, 404)
    left = w["client"].get("/cells/me/alerts", headers=_as(w, "lider")).json()
    assert first["id"] not in {a["id"] for a in left} and len(left) == 3


def test_connected_person_does_not_get_deadline_alert(world, monkeypatch):
    """contacts.link_cell resolve a fila de conexão e mantém prazo_conexao."""
    w = world
    monkeypatch.setenv(svc.ENV_ALLOWLIST, str(w["t"]))
    r = w["client"].put(
        "/cell-alert-rules/prazo_vencendo",
        json={"ativo": True, "parametros": {"antecedencia_horas": 48}},
        headers=_as(w, "admin"),
    )
    assert r.status_code == 200, r.text
    with w["db"].begin() as c:
        c.execute(
            text("update work_queue_items set status='resolvido' where igreja_id=:t and pessoa_id=:p and tipo='conectar_celula'"),
            dict(t=w["t"], p=w["membro"]),
        )
        prazo = c.execute(
            text("select prazo_conexao from consolidacoes where igreja_id=:t and pessoa_id=:p"),
            dict(t=w["t"], p=w["membro"]),
        ).scalar_one()
    assert prazo is not None  # o prazo continua preenchido, como no fluxo real

    _cycle(w)
    prazos = [r for r in _alerts(w) if r.regra_tipo == svc.PRAZO_VENCENDO]
    # Só a célula 2 (conexão ainda aberta) recebe alerta de prazo.
    assert {r.celula_id for r in prazos} == {w["cell2"]}


def test_my_alerts_name_people_only_when_visible(world, monkeypatch):
    w = world
    monkeypatch.setenv(svc.ENV_ALLOWLIST, str(w["t"]))
    with w["db"].begin() as c:
        c.execute(text("update pessoas set nome='Ana Sintética' where id=:p"), dict(p=w["membro"]))
        bruno = _insert_pessoa(c, w["t"], w["lider"])
        c.execute(text("update pessoas set nome='Bruno Sintético' where id=:p"), dict(p=bruno))
        c.execute(
            text("insert into celula_membro(igreja_id,celula_id,pessoa_id,papel) values(:t,:c,:p,'membro')"),
            dict(t=w["t"], c=w["cell"], p=bruno),
        )
        c.execute(
            text(
                "insert into consolidacoes(id,igreja_id,pessoa_id,tipo,progresso,concluida)"
                " values(:i,:t,:p,'individual',10,false)"
            ),
            dict(i=uuid4(), t=w["t"], p=bruno),
        )
    r = w["client"].put(
        "/cell-alert-rules/liderado_em_consolidacao",
        json={"ativo": True, "parametros": {}},
        headers=_as(w, "admin"),
    )
    assert r.status_code == 200, r.text
    _cycle(w)

    mine = w["client"].get("/cells/me/alerts", headers=_as(w, "lider")).json()
    consol = [a for a in mine if a["gatilho"] == svc.RULES["liderado_em_consolidacao"].titulo]
    assert len(consol) == 2
    # Dois alertas de pessoas diferentes ficam distinguíveis pelo nome.
    assert {a["pessoaNome"] for a in consol} == {"Ana Sintética", "Bruno Sintético"}
    assert len({(a["gatilho"], a["pessoaNome"]) for a in consol}) == 2

    # Líder de outra célula não recebe esses alertas nem os nomes.
    other = w["client"].get("/cells/me/alerts", headers=_as(w, "lider2")).json()
    assert other and all(a["celulaId"] == str(w["cell2"]) for a in other)
    assert "Ana Sintética" not in str(other) and "Bruno Sintético" not in str(other)
    # Líder de outra igreja também não.
    foreign = w["client"].get("/cells/me/alerts", headers=_as(w, "lider_b")).json()
    assert "Ana Sintética" not in str(foreign) and "Bruno Sintético" not in str(foreign)

    # Pessoa arquivada: o alerta continua, sem nome.
    with w["db"].begin() as c:
        c.execute(text("update pessoas set arquivada_em=now() where id=:p"), dict(p=w["membro"]))
    archived = w["client"].get("/cells/me/alerts", headers=_as(w, "lider")).json()
    ana = next(a for a in archived if a["pessoaId"] == str(w["membro"]) and a["gatilho"] == svc.RULES["liderado_em_consolidacao"].titulo)
    assert ana["pessoaNome"] is None
    with w["db"].begin() as c:
        c.execute(text("update pessoas set arquivada_em=null where id=:p"), dict(p=w["membro"]))

    # Pessoa que saiu da célula (fora do escopo de Pessoas do líder): sem nome.
    with w["db"].begin() as c:
        c.execute(
            text("update celula_membro set ativo=false where igreja_id=:t and pessoa_id=:p"),
            dict(t=w["t"], p=bruno),
        )
    after = w["client"].get("/cells/me/alerts", headers=_as(w, "lider")).json()
    bruno_alert = next(a for a in after if a["pessoaId"] == str(bruno))
    assert bruno_alert["pessoaNome"] is None
