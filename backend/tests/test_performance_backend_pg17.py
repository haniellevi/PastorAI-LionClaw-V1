"""Actual SQL/RLS proofs for read models, on a guarded disposable PG17.

Minimal synthetic relations use the current mapped column types. These tests
prove queries and isolation, not the production migration catalog or data.
"""

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.db import models as m
from app.db.tenant_session import mark_tenant_scoped
from app.deps import CurrentUser
from app.domain.cell_meetings_schedule import meeting_has_passed
from app.domain.cell_report_snapshot import build_cell_report_snapshot_v2
from app.routers._common import PaginationParams
from app.routers.auth import bootstrap
from app.routers.cell_central import _past_meeting_filter, get_dashboard, get_pending_reports
from app.routers.cells import cells_summary, led_cells_today, list_cells, lookup_cells
from app.routers.contacts import list_contacts, lookup_contacts
from app.routers.events import IndividualTargetInput, _resolve_contatos, list_events
from app.routers.platform_admin import admin_metrics
from app.routers.pipeline import list_pipeline, pipeline_summary
from app.routers.reports import list_reports
from app.routers.setup import get_setup_checklist
from app.routers.team import list_members
from tests.conftest_rls import rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration


def uid(value: int) -> uuid.UUID:
    return uuid.UUID(int=value)


TENANT, OTHER, USER, ACTOR, CELL = map(uid, (1, 2, 11, 21, 31))


def principal(*roles, tenant=TENANT):
    return CurrentUser(app_user_id=str(USER), clerk_user_id="synthetic", igreja_id=str(tenant),
        email="synthetic@example.invalid", nome="Sintético", roles=frozenset(roles), is_owner=True)


@pytest.fixture(scope="module")
def query_engine(rls_database_url):
    engine = create_engine(rls_database_url, connect_args={"options": "-c search_path=performance_backend,public"})
    models = [m.Igreja, m.AppUser, m.UserRole, m.RolePermission, m.Pessoa, m.Celula, m.CelulaMembro,
        m.CelulaReuniao, m.CelulaSolicitacao, m.CelulaAviso, m.CelulaMaterial,
        m.CelulaPresenca, m.CelulaVisitante, m.CelulaExpectativaVisitante,
        m.WhatsappConnection, m.LlmCredential, m.Subscription, m.Plano, m.Event, m.Conversation, m.AiUsageLog]
    with engine.begin() as conn:
        assert conn.execute(text("show server_version_num")).scalar_one().startswith("17")
        conn.execute(text("CREATE SCHEMA performance_backend"))
        conn.execute(text("DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') "
            "THEN CREATE ROLE authenticated NOLOGIN NOINHERIT NOBYPASSRLS; END IF; END $$"))
        conn.execute(text("GRANT USAGE ON SCHEMA performance_backend TO authenticated"))
        for model in models:
            table = model.__table__
            columns = ",".join(f'"{c.name}" {c.type.compile(dialect=postgresql.dialect())}' for c in table.columns)
            conn.execute(text(f'CREATE TABLE "{table.name}" ({columns})'))
            conn.execute(text(f'GRANT SELECT ON "{table.name}" TO authenticated'))
            if "igreja_id" in table.c:
                conn.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))
                conn.execute(text(f'ALTER TABLE "{table.name}" FORCE ROW LEVEL SECURITY'))
                conn.execute(text(f'CREATE POLICY tenant ON "{table.name}" USING '
                    "(igreja_id = nullif(current_setting('app.tenant_igreja_id',true),'')::uuid)"))
            elif model is m.Igreja:
                conn.execute(text('ALTER TABLE igrejas ENABLE ROW LEVEL SECURITY'))
                conn.execute(text("CREATE POLICY tenant ON igrejas USING "
                    "(id = nullif(current_setting('app.tenant_igreja_id',true),'')::uuid)"))
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA performance_backend CASCADE"))
        engine.dispose()


@pytest.fixture
def read_session(query_engine):
    with query_engine.connect() as conn:
        transaction = conn.begin()
        conn.execute(m.Igreja.__table__.insert(), [
            {"id": TENANT, "nome": "Sintética A", "status": "ativa", "logo_path": "synthetic/logo", "plano": "free"},
            {"id": OTHER, "nome": "Sintética B", "status": "ativa", "logo_path": None, "plano": None},
        ])
        conn.execute(m.Plano.__table__.insert(), [{"id": uid(101), "codigo": "free", "preco_mensal": 0, "ativo": False}])
        conn.execute(m.AppUser.__table__.insert(), [
            {"id": USER, "igreja_id": TENANT, "pessoa_id": ACTOR, "nome": "Ator A", "email": "a@example.invalid", "status": "ativo"},
            {"id": uid(12), "igreja_id": TENANT, "pessoa_id": None, "nome": "Revogado", "email": "rev@example.invalid", "status": "revogado"},
            {"id": uid(13), "igreja_id": OTHER, "pessoa_id": uid(23), "nome": "Ator B", "email": "b@example.invalid", "status": "ativo"},
        ])
        conn.execute(m.UserRole.__table__.insert(), [
            {"id": uid(111), "igreja_id": TENANT, "user_id": USER, "papel": "pastor"},
            {"id": uid(112), "igreja_id": OTHER, "user_id": uid(13), "papel": "admin"},
        ])
        conn.execute(m.RolePermission.__table__.insert(), [
            {"id": uid(121), "igreja_id": TENANT, "papel": "membro", "tela": "calendario"},
            {"id": uid(122), "igreja_id": OTHER, "papel": "membro", "tela": "pessoas"},
            {"id": uid(123), "igreja_id": TENANT, "papel": "lider_celula", "tela": "central-celula"},
        ])
        conn.execute(m.Pessoa.__table__.insert(), [
            {"id": ACTOR, "igreja_id": TENANT, "nome": "João A", "telefone": "559900000001", "tipo": "membro",
                "sem_interesse": False, "presencas_celula": 0, "aceitou_jesus": False, "created_at": dt.datetime(2026, 1, 1)},
            {"id": uid(22), "igreja_id": TENANT, "nome": "Maria A", "telefone": "559900000002", "tipo": "visitante",
                "sem_interesse": False, "presencas_celula": 0, "aceitou_jesus": False, "created_at": dt.datetime(2026, 1, 2)},
            {"id": uid(23), "igreja_id": OTHER, "nome": "João B", "telefone": "559900000003", "tipo": "membro",
                "sem_interesse": False, "presencas_celula": 0, "aceitou_jesus": False, "created_at": dt.datetime(2026, 1, 3)},
        ])
        conn.execute(m.Celula.__table__.insert(), [
            {"id": CELL, "igreja_id": TENANT, "lider_id": ACTOR, "nome": "Árvore", "cobertura_espiritual":"Sintética", "ativo": True, "created_at": dt.datetime(2026,1,1)},
            {"id": uid(32), "igreja_id": TENANT, "lider_id": ACTOR, "nome": "Casa", "cobertura_espiritual":"Sintética", "ativo": True, "created_at": dt.datetime(2026,1,2)},
            {"id": uid(33), "igreja_id": OTHER, "lider_id": uid(23), "nome": "Árvore B", "cobertura_espiritual":"Sintética", "ativo": True, "created_at": dt.datetime(2026,1,3)},
        ])
        conn.execute(m.CelulaReuniao.__table__.insert(), [
            {"id": uid(41), "igreja_id": TENANT, "celula_id": CELL, "data": dt.date(2000,1,1), "hora": "19:30", "status": "planejada", "relatorio_status": "pendente"},
            {"id": uid(42), "igreja_id": TENANT, "celula_id": uid(32), "data": dt.date(2000,1,2), "hora": None, "status": "planejada", "relatorio_status": "pendente"},
            {"id": uid(43), "igreja_id": OTHER, "celula_id": uid(33), "data": dt.date(2000,1,1), "hora": "19:00", "status": "planejada", "relatorio_status": "pendente"},
            {"id": uid(44), "igreja_id": TENANT, "celula_id": CELL, "data": dt.date(2999,1,1), "hora": "19:30", "status": "planejada", "relatorio_status": "pendente"},
            {"id": uid(45), "igreja_id": TENANT, "celula_id": uid(32), "data": dt.date(2999,1,1), "hora": "19:30", "status": "planejada", "relatorio_status": "pendente"},
        ])
        for model, values in [
            (m.WhatsappConnection, {"id":uid(51),"igreja_id":TENANT,"status":"online"}),
            (m.LlmCredential, {"id":uid(52),"igreja_id":TENANT,"validado":True,"ativo":True}),
        ]:
            conn.execute(model.__table__.insert(), values)
        session = Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        statements = []
        def record(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)
        event.listen(conn, "before_cursor_execute", record)
        mark_tenant_scoped(session, TENANT, source="synthetic-performance-test")
        statements.clear()
        try:
            yield session, statements, conn
        finally:
            session.close()
            event.remove(conn, "before_cursor_execute", record)
            if transaction.is_active:
                transaction.rollback()


def test_bootstrap_effective_matrix_is_tenant_filtered(read_session):
    db, queries, _ = read_session
    result = bootstrap(db=db, current_user=principal("pastor"))
    assert result.permissions.matriz["membro"] == ["dashboard", "calendario"]
    assert "central-celula" not in result.permissions.matriz["lider_celula"]
    assert len(queries) == 1


def test_setup_one_statement_retains_owner_complimentary_and_revoked_rules(read_session):
    db, queries, _ = read_session
    result = get_setup_checklist(db=db, current_user=principal("admin"))
    assert {item.id: item.done for item in result.items} == {
        "identidade": True, "equipe": False, "celulas": True, "whatsapp": True,
        "agente": True, "assinatura": True,
    }
    assert len(queries) == 1


def test_lookups_and_pipeline_search_count_before_page_and_do_not_leak_tenant(read_session):
    db, queries, _ = read_session
    people = lookup_contacts(db=db, current_user=principal("pastor"), view="all", q="João", pagination=PaginationParams(1,1))
    assert people.total == 1 and [p.id for p in people.items] == [str(ACTOR)]
    assert people.items[0].liderDeCelula
    pipeline = list_pipeline(db=db, current_user=principal("pastor"), etapa="ganhar", q="Maria", pagination=PaginationParams(1,1))
    assert pipeline.total == 1 and [p.nome for p in pipeline.items] == ["Maria A"]
    cells = lookup_cells(db=db, current_user=principal("pastor"), q="Árvore", pagination=PaginationParams(1,1))
    assert cells.total == 1 and [c.id for c in cells.items] == [str(CELL)]
    assert all(c.ativo for c in cells.items)
    assert any("LIMIT" in sql for sql in queries)


def test_contacts_search_advertises_support_and_preserves_scope(read_session):
    db, _, _ = read_session
    page = list_contacts(db=db, current_user=principal("pastor"), view="all", q="João",
                         pagination=PaginationParams(1, 1))
    assert page.model_dump().get("searchSupported") is True
    assert page.total == 1 and [person.id for person in page.items] == [str(ACTOR)]
    assert page.items[0].liderDeCelula


def test_leader_lookup_fails_closed_without_actor_membership(read_session):
    db, _, _ = read_session
    member = principal("membro")
    result = lookup_contacts(db=db, current_user=member, view="all", q=None, pagination=PaginationParams(1,20))
    assert [p.id for p in result.items] == [str(ACTOR)]
    cells = lookup_cells(db=db, current_user=member, q=None, pagination=PaginationParams(1,20))
    assert cells.total == 0


@pytest.mark.parametrize("endpoint", [list_cells, lookup_cells])
def test_cell_search_matches_visible_leader_before_count_and_pagination(read_session, endpoint):
    db, queries, _ = read_session
    first = endpoint(db=db, current_user=principal("pastor"), q="JOÃO A", pagination=PaginationParams(1, 1))
    second = endpoint(db=db, current_user=principal("pastor"), q="JOÃO A", pagination=PaginationParams(2, 1))
    assert first.total == second.total == 2
    assert len(first.items) == len(second.items) == 1
    assert {first.items[0].id, second.items[0].id} == {str(CELL), str(uid(32))}
    assert len(queries) == (8 if endpoint is list_cells else 4)
    if endpoint is list_cells:
        assert first.items[0].liderNome == second.items[0].liderNome == "João A"


@pytest.mark.parametrize("endpoint", [list_cells, lookup_cells])
def test_cell_search_does_not_disclose_a_leader_outside_contact_visibility(read_session, endpoint):
    db, _, conn = read_session
    db.rollback()
    conn.execute(m.Celula.__table__.update().where(m.Celula.id == CELL).values(lider_id=uid(22)))
    conn.execute(m.CelulaMembro.__table__.insert(), {
        "id": uid(91), "igreja_id": TENANT, "celula_id": CELL, "pessoa_id": ACTOR,
        "papel": "membro", "ativo": True,
    })
    mark_tenant_scoped(db, TENANT, source="synthetic-cell-name-visibility")
    assert endpoint(db=db, current_user=principal("membro"), q="Maria A", pagination=PaginationParams(1, 20)).total == 0
    assert endpoint(db=db, current_user=principal("membro"), q="Sem líder", pagination=PaginationParams(1, 20)).total == 0
    visible = endpoint(db=db, current_user=principal("membro"), q="Árvore", pagination=PaginationParams(1, 20))
    assert visible.total == 1 and [cell.id for cell in visible.items] == [str(CELL)]
    if endpoint is list_cells:
        assert visible.items[0].liderNome is None


@pytest.mark.parametrize("endpoint", [list_cells, lookup_cells])
def test_cell_search_excludes_archived_and_other_tenant_leader_names(read_session, endpoint):
    db, _, conn = read_session
    db.rollback()
    conn.execute(m.Pessoa.__table__.update().where(m.Pessoa.id == ACTOR).values(arquivada_em=dt.datetime(2026, 9, 1)))
    conn.execute(m.Celula.__table__.insert(), {
        "id": uid(34), "igreja_id": TENANT, "lider_id": uid(23), "nome": "Referência sintética inconsistente",
        "cobertura_espiritual": "Sintética", "ativo": True, "created_at": dt.datetime(2026, 1, 4),
    })
    mark_tenant_scoped(db, TENANT, source="synthetic-cell-name-tenant")
    for query in ("João A", "João B"):
        assert endpoint(db=db, current_user=principal("pastor"), q=query, pagination=PaginationParams(1, 20)).total == 0


@pytest.mark.parametrize("endpoint", [list_cells, lookup_cells])
def test_cell_search_preserves_leaderless_label_and_literal_wildcards(read_session, endpoint):
    db, _, conn = read_session
    db.rollback()
    conn.execute(m.Pessoa.__table__.update().where(m.Pessoa.id == ACTOR).values(nome="João %_/ literal"))
    conn.execute(m.Celula.__table__.insert(), {
        "id": uid(35), "igreja_id": TENANT, "lider_id": None, "nome": "Comunidade sem referência",
        "cobertura_espiritual": "Sintética", "ativo": True, "created_at": dt.datetime(2026, 1, 5),
    })
    mark_tenant_scoped(db, TENANT, source="synthetic-cell-search-literal")
    leaderless = endpoint(db=db, current_user=principal("pastor"), q="sem LÍDER", pagination=PaginationParams(1, 20))
    assert leaderless.total == 1 and [cell.id for cell in leaderless.items] == [str(uid(35))]
    for query in ("%", "_", "/"):
        page = endpoint(db=db, current_user=principal("pastor"), q=query, pagination=PaginationParams(1, 20))
        assert page.total == 2 and {cell.id for cell in page.items} == {str(CELL), str(uid(32))}


@pytest.mark.parametrize("endpoint", [list_cells, lookup_cells])
def test_cell_search_reuses_assigned_conversation_contact_exception(read_session, endpoint):
    db, _, conn = read_session
    db.rollback()
    conn.execute(m.Celula.__table__.update().where(m.Celula.id == CELL).values(lider_id=uid(22)))
    conn.execute(m.CelulaMembro.__table__.insert(), {
        "id": uid(91), "igreja_id": TENANT, "celula_id": CELL, "pessoa_id": ACTOR,
        "papel": "membro", "ativo": True,
    })
    conn.execute(m.Conversation.__table__.insert(), {
        "id": uid(92), "igreja_id": TENANT, "pessoa_id": uid(22), "assumido_por": USER,
        "telefone": "550000000002", "estado": "humano",
    })
    mark_tenant_scoped(db, TENANT, source="synthetic-cell-search-assigned-contact")
    page = endpoint(db=db, current_user=principal("operador"), q="Maria A", pagination=PaginationParams(1, 20))
    assert page.total == 1 and [cell.id for cell in page.items] == [str(CELL)]
    if endpoint is list_cells:
        assert page.items[0].liderNome == "Maria A"


def test_central_count_page_names_and_future_exclusion(read_session):
    db, queries, _ = read_session
    page = get_pending_reports(db=db, current_user=principal("pastor"), page=2, page_size=1)
    assert page.total == 2 and len(page.items) == 1
    assert page.items[0].reuniao_id == str(uid(42))
    assert page.items[0].celula_nome == "Casa" and page.items[0].lider_nome == "João A"
    assert len(queries) == 4
    queries.clear()
    dashboard = get_dashboard(db=db, current_user=principal("pastor"))
    assert dashboard.relatorios_pendentes == 2
    assert len(queries) <= 7


def test_past_meeting_sql_matches_domain_at_time_and_missing_hour_boundaries(read_session):
    db, _, conn = read_session
    db.rollback()
    # This check uses an unscoped connection to seed a dense boundary sample.
    now = dt.datetime(2026,10,2,13,0,tzinfo=dt.timezone.utc)  # 10:00 São Paulo
    hours = [None,"09:59","10:00","10:01","invalid"," 09:59 "]
    rows = []
    for day_delta in (-1,0,1):
        for n, hour in enumerate(hours):
            rows.append({"id":uid(1000+day_delta*10+n),"igreja_id":TENANT,"celula_id":CELL,
                "data":dt.date(2026,10,2)+dt.timedelta(days=day_delta),"hora":hour})
    conn.execute(m.CelulaReuniao.__table__.insert(), rows)
    mark_tenant_scoped(db, TENANT, source="synthetic-performance-boundary")
    found = set(db.execute(select(m.CelulaReuniao.id).where(m.CelulaReuniao.id.in_([r["id"] for r in rows]), _past_meeting_filter(now))).scalars())
    expected = {r["id"] for r in rows if meeting_has_passed(data=r["data"],hora=r["hora"],now=now)}
    assert found == expected


def test_reports_page_is_bounded_and_invalid_sent_snapshot_outside_page_fails_closed(read_session):
    db, queries, conn = read_session
    good = list_reports(db=db, current_user=principal("pastor"), semana="1999-W52", pagination=PaginationParams(2,1))
    assert good.total == 2 and [p.id for p in good.items] == [str(uid(42))]
    assert any("LIMIT" in sql and "OFFSET" in sql for sql in queries)
    db.rollback()
    forged = build_cell_report_snapshot_v2(presentes=1, visitantes=0, decisoes=0, oferta_valor=None,
        observacoes=None, submission_effect_id="agent_effect_v1_"+"a"*64, submission_payload_digest="agent_payload_v1_"+"b"*64)
    forged["presencas"] = [{"estado":"compareceu"}]
    conn.execute(m.CelulaReuniao.__table__.update().where(m.CelulaReuniao.id == uid(42)).values(
        relatorio_status="enviado",relatorio_snapshot=forged))
    mark_tenant_scoped(db,TENANT,source="synthetic-performance-snapshot")
    with pytest.raises(HTTPException) as error:
        list_reports(db=db,current_user=principal("pastor"),semana="1999-W52",pagination=PaginationParams(1,1))
    assert error.value.status_code == 500
    assert error.value.detail["code"] == "INVALID_CELL_REPORT_SNAPSHOT"


def test_led_today_fetches_one_future_slot_for_all_led_cells(read_session):
    db, queries, _ = read_session
    result = led_cells_today(db=db,current_user=principal("lider_celula"))
    assert [c.nome for c in result.cells] == ["Árvore","Casa"]
    assert result.meeting.id == str(uid(44))
    assert result.meeting.data == "2999-01-01"
    assert result.meeting.tema == "Árvore: Reunião da célula"
    assert len(queries) == 3


def test_team_page_does_not_eager_fetch_igreja_or_all_tenant_roles(read_session):
    db, queries, _ = read_session
    result = list_members(db=db,current_user=principal("pastor"),pagination=PaginationParams(1,1))
    assert result.total == 2 and result.items[0].papeis == ["pastor"]
    assert len(queries) == 3
    assert not any("JOIN igrejas" in sql for sql in queries)
    assert "user_roles.user_id IN" in queries[-1]


def test_event_window_is_inclusive_and_draft_filter_never_leaks_to_member(read_session):
    db, queries, conn = read_session
    db.rollback()
    conn.execute(m.Event.__table__.insert(), [
        {"id":uid(61),"igreja_id":TENANT,"titulo":"Inicio","data":dt.date(2026,10,1),"status":"confirmado"},
        {"id":uid(62),"igreja_id":TENANT,"titulo":"Fim","data":dt.date(2026,10,31),"status":"confirmado"},
        {"id":uid(63),"igreja_id":TENANT,"titulo":"Rascunho","data":None,"status":"a_confirmar"},
        {"id":uid(64),"igreja_id":OTHER,"titulo":"Outra igreja","data":dt.date(2026,10,1),"status":"confirmado"},
    ])
    mark_tenant_scoped(db,TENANT,source="synthetic-performance-events")
    queries.clear()
    result = list_events(db=db,current_user=principal("membro"),pagination=PaginationParams(1,20),
        from_date=dt.date(2026,10,1),to_date=dt.date(2026,10,31))
    assert result.total == 2 and [e.titulo for e in result.items] == ["Inicio","Fim"]
    assert len(queries) == 2
    hidden = list_events(db=db,current_user=principal("membro"),pagination=PaginationParams(1,20),
        from_date=None,event_status="a_confirmar")
    assert hidden.total == 0
    drafts = list_events(db=db,current_user=principal("pastor"),pagination=PaginationParams(1,20),
        from_date=None,event_status="a_confirmar")
    assert drafts.total == 1 and drafts.items[0].data is None


def test_target_batch_preserves_order_and_dedupe_and_rejects_foreign_contact(read_session):
    db, queries, conn = read_session
    db.rollback()
    conn.execute(m.Conversation.__table__.insert(), [
        {"id":uid(71),"igreja_id":TENANT,"pessoa_id":ACTOR,"telefone":"00990000001"},
        {"id":uid(72),"igreja_id":TENANT,"pessoa_id":None,"telefone":"00990000002"},
        {"id":uid(73),"igreja_id":OTHER,"pessoa_id":uid(23),"telefone":"00990000003"},
    ])
    mark_tenant_scoped(db,TENANT,source="synthetic-performance-targets")
    queries.clear()
    targets = [IndividualTargetInput(telefone="5500990000002"),IndividualTargetInput(pessoaId=str(ACTOR)),
        IndividualTargetInput(telefone="00990000001")]
    result = _resolve_contatos(db,TENANT,targets)
    assert result == [(None,"00990000002"),(ACTOR,None)]
    assert len(queries) == 1
    with pytest.raises(HTTPException) as error:
        _resolve_contatos(db,TENANT,[IndividualTargetInput(pessoaId=str(uid(23)))])
    assert error.value.status_code == 422


def test_global_metrics_groups_in_database_and_reads_totals_in_one_statement(read_session):
    scoped_db, queries, conn = read_session
    scoped_db.rollback()
    with Session(bind=conn,join_transaction_mode="create_savepoint") as db:
        queries.clear()
        result = admin_metrics(db=db,_admin=None)
        assert result.totalIgrejas == 2 and result.totalMembros == 3 and result.totalPessoas == 3
        assert result.porStatus == {"ativa":2} and result.porPlano == {"free":1}
        assert result.mrr == 0 and result.custoIaTotal == 0
        assert len([q for q in queries if q.startswith("SELECT")]) == 3


def test_pipeline_summary_preserves_explicit_substage_and_decision_classification(read_session):
    db,queries,conn = read_session
    db.rollback()
    conn.execute(m.Pessoa.__table__.update().where(m.Pessoa.id == ACTOR).values(subetapa="visitante",aceitou_jesus=True))
    conn.execute(m.Pessoa.__table__.update().where(m.Pessoa.id == uid(22)).values(subetapa="novo_contato",presencas_celula=5))
    mark_tenant_scoped(db,TENANT,source="synthetic-performance-summary")
    queries.clear()
    result = pipeline_summary(db=db,current_user=principal("pastor"),etapa="ganhar")
    assert result.model_dump() == {"total":2,"novosContatos":1,"visitantesSemCelula":1,"visitantesComDecisao":1}
    assert len(queries) == 1
    visitors = list_pipeline(db=db,current_user=principal("pastor"),etapa="ganhar",group="visitantes",pagination=PaginationParams(1,20))
    assert visitors.total == 1 and [p.id for p in visitors.items] == [str(ACTOR)]
    filtered = pipeline_summary(db=db,current_user=principal("pastor"),etapa="ganhar",q="Maria")
    assert filtered.model_dump() == {"total":1,"novosContatos":1,"visitantesSemCelula":0,"visitantesComDecisao":0}


def test_cell_card_counts_keep_legacy_visible_person_mirror_without_global_people_download(read_session):
    db,queries,conn = read_session
    db.rollback()
    conn.execute(m.Pessoa.__table__.update().where(m.Pessoa.id.in_([ACTOR,uid(22)])).values(celula_id=CELL))
    mark_tenant_scoped(db,TENANT,source="synthetic-performance-cell-summary")
    queries.clear()
    summary = cells_summary(db=db,current_user=principal("pastor"))
    assert summary.model_dump() == {"total":2,"ativas":2,"semLider":0,"pessoasEmCelulas":2}
    assert len(queries) == 1
    rows = list_cells(db=db,current_user=principal("pastor"),pagination=PaginationParams(1,20))
    by_id = {c.id:c for c in rows.items}
    assert by_id[str(CELL)].membros == 1 and by_id[str(CELL)].visitantes == 1
    assert by_id[str(CELL)].liderNome == "João A"
    assert len(queries) == 5
    lookup = lookup_contacts(db=db,current_user=principal("pastor"),view="all",celula_id=CELL,pagination=PaginationParams(1,1))
    assert lookup.total == 2 and len(lookup.items) == 1


def test_agenda_window_opt_in_keeps_undated_recurrence_bounded_and_role_scoped(app, read_session):
    from fastapi.testclient import TestClient
    from app.db.session import get_db
    from app.deps import get_current_user

    db, _queries, conn = read_session
    db.rollback()
    conn.execute(m.Event.__table__.insert(), [
        {"id": uid(61), "igreja_id": TENANT, "titulo": "Boundary start", "data": dt.date(2026, 10, 1), "status": "confirmado", "recorrencia": "pontual"},
        {"id": uid(62), "igreja_id": TENANT, "titulo": "Weekly published", "data": None, "status": "confirmado", "recorrencia": "semanal"},
        {"id": uid(63), "igreja_id": TENANT, "titulo": "Weekly editorial draft", "data": None, "status": "a_confirmar", "recorrencia": "semanal"},
        {"id": uid(64), "igreja_id": OTHER, "titulo": "Other tenant weekly", "data": None, "status": "confirmado", "recorrencia": "semanal"},
        {"id": uid(65), "igreja_id": TENANT, "titulo": "Outside window", "data": dt.date(2026, 9, 30), "status": "confirmado", "recorrencia": "pontual"},
        {"id": uid(66), "igreja_id": TENANT, "titulo": "Boundary end", "data": dt.date(2026, 10, 31), "status": "confirmado", "recorrencia": "pontual"},
    ])
    mark_tenant_scoped(db, TENANT, source="synthetic-performance-recurrence")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: principal("membro")
    client = TestClient(app)
    window = {"fromDate": "2026-10-01", "toDate": "2026-10-31", "pageSize": 2}

    dashboard = client.get("/events", params=window)
    assert dashboard.status_code == 200
    assert dashboard.json()["total"] == 2
    assert {event["id"] for event in dashboard.json()["items"]} == {str(uid(61)), str(uid(66))}

    agenda = client.get("/events", params={**window, "includeUndated": "true"})
    assert agenda.status_code == 200
    assert agenda.json()["total"] == 3
    assert len(agenda.json()["items"]) == 2
    next_page = client.get("/events", params={**window, "includeUndated": "true", "page": 2})
    assert next_page.status_code == 200
    assert [event["id"] for event in next_page.json()["items"]] == [str(uid(62))]
    assert next_page.json()["items"][0]["data"] is None
    assert next_page.json()["items"][0]["recorrencia"] == "semanal"

    app.dependency_overrides[get_current_user] = lambda: principal("pastor")
    pastoral = client.get("/events", params={**window, "includeUndated": "true", "page": 2})
    assert pastoral.status_code == 200
    assert pastoral.json()["total"] == 4
    assert {event["id"] for event in pastoral.json()["items"]} == {str(uid(62)), str(uid(63))}
