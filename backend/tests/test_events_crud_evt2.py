"""EVT-2 — CRUD de eventos + confirmação manual.

Harness offline (FakeSession-style): roteia a auth (AppUser/UserRole) e o lookup
do Event por entidade, sem DB real. Cobre os contratos HTTP novos:

  - GET    /events/{id}          encontrado / 404 (inexistente ou outro tenant);
  - PUT    /events/{id}          edita campos permitidos;
  - DELETE /events/{id}          remove (204);
  - POST   /events/{id}/confirm  seta status/confirmado_em/confirmado_por; 409 se
                                  já confirmado;
  - POST   /events               bloqueia lider_g12, permite pastor/admin.

O filtro `igreja_id` no nível de query (defesa em profundidade além da RLS) é
provado inspecionando o PREDICADO WHERE do SELECT por id (`statement.whereclause`),
que exclui a projeção de colunas — `events.igreja_id` só aparece ali se `_get_event`
realmente filtra por tenant (e a asserção falha se o predicado for removido). O fake
ignora o WHERE ao devolver o objeto canônico, então o 404 "outro tenant" é simulado
com event=None (é o que a RLS + filtro igreja_id produziriam); a barreira efetiva
entre tenants é a RLS, exercitada fora deste harness offline.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Conversation, Event, EventNotifyTarget
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_EID = "00000000-0000-0000-0000-0000000000e2"
# id do app_user dono (igual ao de make_app_user) — vira confirmado_por.
_UID = "00000000-0000-0000-0000-0000000000a1"


class _R:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class EventSession:
    """Roteia auth (AppUser/UserRole), o lookup do Event e das Conversation."""

    def __init__(self, *, app_user, roles, event, conversation=None) -> None:
        self.app_user = app_user
        self.roles = roles
        self.event = event
        # Conversa devolvida para QUALQUER lookup de Conversation (o filtro de
        # tenant é provado inspecionando o WHERE, como no Event); None simula
        # contato de outro tenant/inexistente (o que a RLS + igreja_id removeriam).
        self.conversation = conversation
        self.committed = False
        self.deleted = None
        self.added = None
        self.added_all: list = []  # confirm pode adicionar N EventNotifyTarget.
        self.last_event_stmt = None
        self.last_conversation_stmt = None

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Event:
            self.last_event_stmt = statement
            return _R(scalar=self.event)
        if ent is Conversation:
            self.last_conversation_stmt = statement
            return _R(scalar=self.conversation)
        return _R(scalars=self.roles)

    def add(self, obj) -> None:
        self.added = obj
        self.added_all.append(obj)

    def delete(self, obj) -> None:
        self.deleted = obj

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


def make_event(
    *,
    status="confirmado",
    confirmado_em=None,
    confirmado_por=None,
    titulo="Culto",
    data=dt.date(2026, 1, 1),
    hora="19:30",
    descricao="Domingo",
    tipo=None,
    publico_alvo=None,
    antecedencia_horas=None,
    mensagem_confirmacao=None,
    notificar_em=None,
    notificacao_enviada_em=None,
    canal=None,
):
    return SimpleNamespace(
        id=_EID,
        igreja_id="00000000-0000-0000-0000-000000000001",
        titulo=titulo,
        data=data,
        hora=hora,
        descricao=descricao,
        google_event_id=None,
        status=status,
        tipo=tipo,
        origem="manual",
        recorrencia="pontual",
        confirmado_em=confirmado_em,
        confirmado_por=confirmado_por,
        # EVT-8a — colunas de comunicação (nullable desde o EVT-1).
        publico_alvo=publico_alvo,
        antecedencia_horas=antecedencia_horas,
        mensagem_confirmacao=mensagem_confirmacao,
        # EVT-8 PR1 — agendamento da notificação do evento (nullable).
        notificar_em=notificar_em,
        notificacao_enviada_em=notificacao_enviada_em,
        canal=canal,
    )


def make_conversation(*, pessoa_id=None, telefone="5511999990000"):
    """Conversa do WhatsApp do tenant (fonte da seleção individual, D3)."""
    return SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000c1",
        igreja_id="00000000-0000-0000-0000-000000000001",
        pessoa_id=pessoa_id,
        telefone=telefone,
    )


def _wire(app, *, session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    return TestClient(app)


def _session(*, roles, event=None, conversation=None):
    return EventSession(
        app_user=make_app_user(), roles=roles, event=event, conversation=conversation
    )


def _last_event_where(session) -> str:
    """SQL apenas do predicado WHERE do último SELECT de Event (sem a projeção).

    `str(stmt.whereclause)` rende só a cláusula WHERE — ex.:
    ``events.id = :id_1 AND events.igreja_id = :igreja_id_1`` — então a presença
    de ``events.igreja_id`` aqui prova o filtro de tenant, não a lista de colunas
    do SELECT (onde igreja_id sempre apareceria por ser coluna mapeada). Substring
    de ``tabela.coluna`` é estável a espaçamento/nome de bind param.
    """
    where = getattr(session.last_event_stmt, "whereclause", None)
    return str(where) if where is not None else ""


def _last_conversation_where(session) -> str:
    """WHERE do último SELECT de Conversation — prova o filtro de tenant (D3).

    A presença de ``conversations.igreja_id`` aqui garante que a validação de
    contato individual filtra por igreja (defesa em profundidade além da RLS): um
    contato de outro tenant nunca é aceito.
    """
    where = getattr(session.last_conversation_stmt, "whereclause", None)
    return str(where) if where is not None else ""


# ---- GET /events/{id} ------------------------------------------------------
def test_get_event_found(app) -> None:
    session = _session(roles=["admin"], event=make_event())
    resp = _wire(app, session=session).get(f"/events/{_EID}", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == _EID
    assert body["titulo"] == "Culto"
    assert body["status"] == "confirmado"
    assert body["origem"] == "manual"
    # Prova o filtro de tenant NO PREDICADO WHERE (não na projeção): _get_event
    # filtra por Event.id E Event.igreja_id. A asserção falha se o predicado
    # igreja_id for removido do router (defesa em profundidade além da RLS).
    where_sql = _last_event_where(session)
    assert "events.id" in where_sql
    assert "events.igreja_id" in where_sql


def test_get_event_404_other_tenant_or_missing(app) -> None:
    # event=None simula tanto inexistente quanto evento de outro tenant (que a
    # RLS + filtro igreja_id removeriam do resultado).
    session = _session(roles=["admin"], event=None)
    resp = _wire(app, session=session).get(f"/events/{_EID}", headers=_AUTH)
    assert resp.status_code == 404


def test_get_event_malformed_id_is_404(app) -> None:
    session = _session(roles=["admin"], event=make_event())
    resp = _wire(app, session=session).get("/events/nao-e-uuid", headers=_AUTH)
    assert resp.status_code == 404


# ---- PUT /events/{id} ------------------------------------------------------
def test_put_updates_allowed_fields(app) -> None:
    event = make_event(titulo="Antigo", hora="19:30", descricao="x")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).put(
        f"/events/{_EID}",
        headers=_AUTH,
        json={"titulo": "Culto Novo", "hora": "20:00", "descricao": "Atualizado"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["titulo"] == "Culto Novo"
    assert body["hora"] == "20:00"
    assert body["descricao"] == "Atualizado"
    assert event.titulo == "Culto Novo"
    assert event.hora == "20:00"
    assert session.committed is True


def test_put_omitted_fields_unchanged(app) -> None:
    event = make_event(titulo="Mantido", hora="19:30")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).put(
        f"/events/{_EID}", headers=_AUTH, json={"descricao": "só isso"}
    )
    assert resp.status_code == 200
    assert event.titulo == "Mantido"
    assert event.hora == "19:30"
    assert event.descricao == "só isso"


def test_put_rejects_invalid_hora(app) -> None:
    session = _session(roles=["pastor"], event=make_event())
    resp = _wire(app, session=session).put(
        f"/events/{_EID}", headers=_AUTH, json={"hora": "25:99"}
    )
    assert resp.status_code == 422


def test_put_404_when_missing(app) -> None:
    session = _session(roles=["pastor"], event=None)
    resp = _wire(app, session=session).put(
        f"/events/{_EID}", headers=_AUTH, json={"titulo": "X"}
    )
    assert resp.status_code == 404


# ---- DELETE /events/{id} ---------------------------------------------------
def test_delete_removes(app) -> None:
    event = make_event()
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).delete(f"/events/{_EID}", headers=_AUTH)
    assert resp.status_code == 204
    assert session.deleted is event
    assert session.committed is True


def test_delete_404_when_missing(app) -> None:
    session = _session(roles=["pastor"], event=None)
    resp = _wire(app, session=session).delete(f"/events/{_EID}", headers=_AUTH)
    assert resp.status_code == 404


# ---- POST /events/{id}/confirm ---------------------------------------------
def test_confirm_sets_status_and_audit_fields(app) -> None:
    event = make_event(status="a_confirmar")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm", headers=_AUTH
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmado"
    assert body["confirmadoEm"] is not None
    assert body["confirmadoPor"] == _UID
    assert event.status == "confirmado"
    assert event.confirmado_em is not None
    assert str(event.confirmado_por) == _UID
    assert session.committed is True


def test_confirm_already_confirmed_is_409(app) -> None:
    event = make_event(status="confirmado")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm", headers=_AUTH
    )
    assert resp.status_code == 409
    # não mexeu no evento.
    assert event.confirmado_em is None


def test_confirm_404_when_missing(app) -> None:
    session = _session(roles=["pastor"], event=None)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm", headers=_AUTH
    )
    assert resp.status_code == 404


# ---- POST /events — gate de papel (remove lider_g12) -----------------------
def test_create_blocks_lider_g12(app) -> None:
    session = _session(roles=["lider_g12"])
    resp = _wire(app, session=session).post(
        "/events",
        headers=_AUTH,
        json={"titulo": "Culto", "data": "2026-01-01", "hora": "19:30"},
    )
    assert resp.status_code == 403


def test_create_allows_pastor(app) -> None:
    session = _session(roles=["pastor"])
    resp = _wire(app, session=session).post(
        "/events",
        headers=_AUTH,
        json={"titulo": "Culto", "data": "2026-01-01", "hora": "19:30"},
    )
    assert resp.status_code == 200
    assert session.added is not None


def test_create_allows_admin(app) -> None:
    session = _session(roles=["admin"])
    resp = _wire(app, session=session).post(
        "/events",
        headers=_AUTH,
        json={"titulo": "Culto", "data": "2026-01-01", "hora": "19:30"},
    )
    assert resp.status_code == 200


# ---- POST /events — EVT-6 PR6.0: push Google legado desarmado ---------------
def test_create_does_not_call_legacy_google_push(app, monkeypatch) -> None:
    """O create NÃO invoca mais `GoogleCalendarClient.create_event`.

    O push legado usava o token GLOBAL de settings (risco multi-tenant) e gerava
    órfãos (PUT não ressincroniza, DELETE não remove). Aqui patchamos o método do
    cliente legado para registrar qualquer chamada: o evento deve ser criado só no
    banco, sem tocar esse caminho. Se alguém reintroduzir o push global, `calls`
    deixa de ser vazio e este teste falha.
    """
    calls: list = []

    def _record(self, **kwargs):  # pragma: no cover - não deve ser chamado
        calls.append(kwargs)
        return "should-not-be-used"

    monkeypatch.setattr(
        "app.services.google_calendar.GoogleCalendarClient.create_event", _record
    )

    session = _session(roles=["pastor"])
    resp = _wire(app, session=session).post(
        "/events",
        headers=_AUTH,
        json={"titulo": "Culto", "data": "2026-01-01", "hora": "19:30"},
    )

    assert resp.status_code == 200
    assert calls == []  # push legado nunca chamado
    assert session.added is not None
    body = resp.json()
    # contrato preservado: sem google_event_id => não sincronizado.
    assert body["sincronizado"] is False
    assert body.get("googleEventId") is None


# ---- P0b-2: tipo do evento na API (create/update/serialização/validação) ----
def test_create_persists_and_returns_tipo(app) -> None:
    session = _session(roles=["pastor"])
    resp = _wire(app, session=session).post(
        "/events",
        headers=_AUTH,
        json={"titulo": "Culto", "data": "2026-01-01", "hora": "19:30", "tipo": "culto"},
    )
    assert resp.status_code == 200
    assert resp.json()["tipo"] == "culto"
    assert session.added.tipo == "culto"


def test_create_without_tipo_defaults_none(app) -> None:
    session = _session(roles=["pastor"])
    resp = _wire(app, session=session).post(
        "/events",
        headers=_AUTH,
        json={"titulo": "Culto", "data": "2026-01-01", "hora": "19:30"},
    )
    assert resp.status_code == 200
    assert resp.json()["tipo"] is None
    assert session.added.tipo is None


def test_create_rejects_invalid_tipo(app) -> None:
    session = _session(roles=["pastor"])
    resp = _wire(app, session=session).post(
        "/events",
        headers=_AUTH,
        json={"titulo": "Culto", "data": "2026-01-01", "tipo": "banquete"},
    )
    assert resp.status_code == 422


def test_put_changes_tipo(app) -> None:
    event = make_event(tipo=None)
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).put(
        f"/events/{_EID}", headers=_AUTH, json={"tipo": "reuniao"}
    )
    assert resp.status_code == 200
    assert resp.json()["tipo"] == "reuniao"
    assert event.tipo == "reuniao"


def test_put_clears_tipo_with_explicit_null(app) -> None:
    event = make_event(tipo="culto")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).put(
        f"/events/{_EID}", headers=_AUTH, json={"tipo": None}
    )
    assert resp.status_code == 200
    assert resp.json()["tipo"] is None
    assert event.tipo is None


def test_put_omitted_tipo_unchanged(app) -> None:
    event = make_event(tipo="celula")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).put(
        f"/events/{_EID}", headers=_AUTH, json={"descricao": "só isso"}
    )
    assert resp.status_code == 200
    assert event.tipo == "celula"


def test_put_rejects_invalid_tipo(app) -> None:
    session = _session(roles=["pastor"], event=make_event())
    resp = _wire(app, session=session).put(
        f"/events/{_EID}", headers=_AUTH, json={"tipo": "banquete"}
    )
    assert resp.status_code == 422


def test_get_old_event_null_tipo_serializes(app) -> None:
    # evento legado sem categoria (tipo=None) não quebra a serialização.
    session = _session(roles=["admin"], event=make_event(tipo=None))
    resp = _wire(app, session=session).get(f"/events/{_EID}", headers=_AUTH)
    assert resp.status_code == 200
    assert resp.json()["tipo"] is None


# ---- EVT-8a: confirm com corpo opcional de comunicação ----------------------
def test_confirm_no_body_still_confirms(app) -> None:
    # sem body continua confirmando E não toca as colunas de comunicação.
    event = make_event(status="a_confirmar")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).post(f"/events/{_EID}/confirm", headers=_AUTH)
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmado"
    assert event.publico_alvo is None
    assert event.antecedencia_horas is None
    assert event.mensagem_confirmacao is None


def test_confirm_empty_body_still_confirms(app) -> None:
    event = make_event(status="a_confirmar")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm", headers=_AUTH, json={}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmado"
    body = resp.json()
    assert body["publicoAlvo"] is None
    assert body["antecedenciaHoras"] is None
    assert body["mensagemConfirmacao"] is None
    # EVT-8 PR1 — confirm "seco" não configura notificação nem toca canal/contatos.
    assert body["notificarEm"] is None
    assert body["canal"] is None
    assert body["contatos"] is None
    assert session.added_all == []  # nenhum EventNotifyTarget


def test_confirm_persists_communication_fields(app) -> None:
    # EVT-8 PR1 (D1) — taxonomia coletiva nova (toda_igreja/pastores/g12_pastoral/
    # lideres_celula). Canal assume whatsapp (D6) quando há intenção.
    event = make_event(status="a_confirmar")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={
            "publicoAlvo": ["pastores", "g12_pastoral"],
            "antecedenciaHoras": 24,
            "mensagemConfirmacao": "  Vem participar!  ",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmado"
    assert body["publicoAlvo"] == ["pastores", "g12_pastoral"]
    assert body["antecedenciaHoras"] == 24
    assert body["mensagemConfirmacao"] == "Vem participar!"  # trim aplicado
    assert body["canal"] == "whatsapp"  # D6 — canal padrão do MVP
    assert event.publico_alvo == ["pastores", "g12_pastoral"]
    assert event.antecedencia_horas == 24
    assert event.mensagem_confirmacao == "Vem participar!"
    assert event.canal == "whatsapp"


def test_confirm_publico_alvo_dedup_preserves_order(app) -> None:
    event = make_event(status="a_confirmar")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={"publicoAlvo": ["pastores", "pastores", "g12_pastoral", "pastores"]},
    )
    assert resp.status_code == 200
    assert resp.json()["publicoAlvo"] == ["pastores", "g12_pastoral"]
    assert event.publico_alvo == ["pastores", "g12_pastoral"]


def test_confirm_rejects_invalid_publico(app) -> None:
    # "banda" nunca foi válido; "jovens"/"lideres" saíram do MVP (D1) e agora
    # também caem no 422 do Literal.
    session = _session(roles=["pastor"], event=make_event(status="a_confirmar"))
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm", headers=_AUTH, json={"publicoAlvo": ["jovens"]}
    )
    assert resp.status_code == 422


def test_confirm_rejects_publico_over_four(app) -> None:
    # 5 itens (4 distintos + 1 repetido) => estoura o teto de 4 (checado no bruto).
    session = _session(roles=["pastor"], event=make_event(status="a_confirmar"))
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={
            "publicoAlvo": [
                "toda_igreja",
                "pastores",
                "g12_pastoral",
                "lideres_celula",
                "pastores",
            ]
        },
    )
    assert resp.status_code == 422


def test_confirm_rejects_negative_antecedencia(app) -> None:
    session = _session(roles=["pastor"], event=make_event(status="a_confirmar"))
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm", headers=_AUTH, json={"antecedenciaHoras": -1}
    )
    assert resp.status_code == 422


def test_confirm_blank_mensagem_becomes_null(app) -> None:
    event = make_event(status="a_confirmar")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={"mensagemConfirmacao": "   \n\t  "},
    )
    assert resp.status_code == 200
    assert resp.json()["mensagemConfirmacao"] is None
    assert event.mensagem_confirmacao is None


def test_confirm_rejects_mensagem_over_2000(app) -> None:
    session = _session(roles=["pastor"], event=make_event(status="a_confirmar"))
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={"mensagemConfirmacao": "a" * 2001},
    )
    assert resp.status_code == 422


def test_confirm_already_confirmed_ignores_communication_body(app) -> None:
    # 409 acontece ANTES de qualquer persistência nova: os 3 campos ficam intactos.
    event = make_event(
        status="confirmado",
        publico_alvo=["toda_igreja"],
        antecedencia_horas=12,
        mensagem_confirmacao="original",
    )
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={
            "publicoAlvo": ["pastores"],
            "antecedenciaHoras": 48,
            "mensagemConfirmacao": "nova",
        },
    )
    assert resp.status_code == 409
    assert event.publico_alvo == ["toda_igreja"]
    assert event.antecedencia_horas == 12
    assert event.mensagem_confirmacao == "original"


def test_get_legacy_event_null_communication_serializes(app) -> None:
    # evento legado (colunas de comunicação null) serializa sem quebrar.
    session = _session(roles=["admin"], event=make_event())
    resp = _wire(app, session=session).get(f"/events/{_EID}", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["publicoAlvo"] is None
    assert body["antecedenciaHoras"] is None
    assert body["mensagemConfirmacao"] is None


def test_confirm_with_body_makes_no_google_or_whatsapp_call(app, monkeypatch) -> None:
    """Confirmar com body de comunicação NÃO introduz push Google/WhatsApp.

    EVT-8a só persiste a intenção. O único caminho de comunicação segue sendo o
    `notify_event_confirmed` (EVT-7, best-effort atrás de flag) — aqui espionado
    para provar que continua sendo chamado exatamente uma vez e nada além dele.
    Se alguém plugar um envio Google/WhatsApp no confirm, `google_calls` deixa de
    ser vazio e o teste falha.
    """
    google_calls: list = []
    notify_calls: list = []

    def _record_google(self, **kwargs):  # pragma: no cover - não deve ser chamado
        google_calls.append(kwargs)
        return "should-not-be-used"

    def _spy_notify(db, event):
        notify_calls.append(event)

    monkeypatch.setattr(
        "app.services.google_calendar.GoogleCalendarClient.create_event",
        _record_google,
    )
    monkeypatch.setattr("app.routers.events.notify_event_confirmed", _spy_notify)

    event = make_event(status="a_confirmar")
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={
            "publicoAlvo": ["toda_igreja"],
            "antecedenciaHoras": 2,
            "mensagemConfirmacao": "Lembrete",
        },
    )

    assert resp.status_code == 200
    assert google_calls == []  # nenhum push Google novo
    assert len(notify_calls) == 1  # caminho de aviso EVT-7 inalterado


# ---- EVT-8 PR1 — seleção individual (contatos do WhatsApp, D3) --------------
_PID = "00000000-0000-0000-0000-0000000000c9"
_IGREJA = "00000000-0000-0000-0000-000000000001"


def test_confirm_individual_contact_by_pessoa_persists_target(app) -> None:
    # Contato por pessoaId: a conversa do tenant existe → vira EventNotifyTarget
    # com pessoa_id (D3: prefere pessoa). Nada de telefone livre.
    event = make_event(status="a_confirmar")
    session = _session(
        roles=["pastor"],
        event=event,
        conversation=make_conversation(pessoa_id=_PID, telefone="5511999990000"),
    )
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={"contatos": [{"pessoaId": _PID}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["contatos"] == [{"pessoaId": _PID, "telefone": None}]
    assert body["canal"] == "whatsapp"  # há intenção (contatos) → canal padrão
    # um EventNotifyTarget adicionado, tenant-correto, por pessoa.
    targets = [t for t in session.added_all if isinstance(t, EventNotifyTarget)]
    assert len(targets) == 1
    assert str(targets[0].pessoa_id) == _PID
    assert targets[0].telefone is None
    assert str(targets[0].event_id) == _EID
    assert str(targets[0].igreja_id) == _IGREJA


def test_confirm_individual_contact_phone_fallback(app) -> None:
    # Conversa SEM pessoa vinculada → guarda o telefone canônico (fallback D3).
    event = make_event(status="a_confirmar")
    session = _session(
        roles=["pastor"],
        event=event,
        conversation=make_conversation(pessoa_id=None, telefone="5511988887777"),
    )
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={"contatos": [{"telefone": "5511988887777"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["contatos"] == [
        {"pessoaId": None, "telefone": "5511988887777"}
    ]
    targets = [t for t in session.added_all if isinstance(t, EventNotifyTarget)]
    assert len(targets) == 1
    assert targets[0].pessoa_id is None
    assert targets[0].telefone == "5511988887777"


def test_confirm_individual_prefers_pessoa_when_conversation_has_one(app) -> None:
    # Mesmo mandando telefone, se a conversa tem pessoa vinculada, guarda pessoa.
    event = make_event(status="a_confirmar")
    session = _session(
        roles=["pastor"],
        event=event,
        conversation=make_conversation(pessoa_id=_PID, telefone="5511977776666"),
    )
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={"contatos": [{"telefone": "5511977776666"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["contatos"] == [{"pessoaId": _PID, "telefone": None}]


def test_confirm_rejects_contact_from_other_tenant(app) -> None:
    # conversation=None simula contato de outro tenant (a RLS + igreja_id o
    # removeriam). 422, e a confirmação NÃO acontece (valida antes de persistir).
    event = make_event(status="a_confirmar")
    session = _session(roles=["pastor"], event=event, conversation=None)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={"contatos": [{"pessoaId": _PID}]},
    )
    assert resp.status_code == 422
    assert event.status == "a_confirmar"  # não confirmou
    assert session.committed is False
    # prova o filtro de tenant NO PREDICADO WHERE da query de Conversation.
    where_sql = _last_conversation_where(session)
    assert "conversations.igreja_id" in where_sql


def test_confirm_rejects_contact_without_identity(app) -> None:
    # contato sem pessoaId nem telefone => 422 no schema (não chega ao handler).
    session = _session(roles=["pastor"], event=make_event(status="a_confirmar"))
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm", headers=_AUTH, json={"contatos": [{}]}
    )
    assert resp.status_code == 422


# ---- EVT-8 PR1 — normalização do "quando" (notificar_em, D4) ----------------
def test_confirm_derives_notificar_em_from_antecedencia(app) -> None:
    # evento 2026-01-01 19:30 (America/Sao_Paulo) - 24h => 2025-12-31 19:30 -03:00.
    event = make_event(
        status="a_confirmar", data=dt.date(2026, 1, 1), hora="19:30"
    )
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={"publicoAlvo": ["toda_igreja"], "antecedenciaHoras": 24},
    )
    assert resp.status_code == 200
    notificar_em = resp.json()["notificarEm"]
    assert notificar_em.startswith("2025-12-31T19:30:00")
    assert notificar_em.endswith("-03:00")
    assert event.notificar_em is not None


def test_confirm_explicit_notificar_em_before_event_ok(app) -> None:
    event = make_event(
        status="a_confirmar", data=dt.date(2026, 1, 1), hora="19:30"
    )
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={"notificarEm": "2026-01-01T08:00:00-03:00"},
    )
    assert resp.status_code == 200
    assert resp.json()["notificarEm"].startswith("2026-01-01T08:00:00")


def test_confirm_rejects_notificar_em_after_event(app) -> None:
    # data/hora específica precisa ser ANTES do início do evento (D4).
    event = make_event(
        status="a_confirmar", data=dt.date(2026, 1, 1), hora="19:30"
    )
    session = _session(roles=["pastor"], event=event)
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={"notificarEm": "2026-01-02T10:00:00-03:00"},
    )
    assert resp.status_code == 422
    assert event.status == "a_confirmar"


def test_confirm_with_contact_makes_no_whatsapp_send(app, monkeypatch) -> None:
    # EVT-8 PR1 só PERSISTE a intenção: configurar contatos NÃO dispara Evolution.
    evolution_calls: list = []
    google_calls: list = []

    def _record_send(self, instance, phone, text):  # pragma: no cover - não deve
        evolution_calls.append((instance, phone, text))
        return True

    def _record_google(self, **kwargs):  # pragma: no cover - não deve ser chamado
        google_calls.append(kwargs)
        return "should-not-be-used"

    monkeypatch.setattr(
        "app.services.evolution.EvolutionClient.send_text", _record_send
    )
    monkeypatch.setattr(
        "app.services.google_calendar.GoogleCalendarClient.create_event",
        _record_google,
    )

    event = make_event(status="a_confirmar")
    session = _session(
        roles=["pastor"],
        event=event,
        conversation=make_conversation(pessoa_id=_PID),
    )
    resp = _wire(app, session=session).post(
        f"/events/{_EID}/confirm",
        headers=_AUTH,
        json={
            "publicoAlvo": ["toda_igreja"],
            "contatos": [{"pessoaId": _PID}],
            "antecedenciaHoras": 2,
            "mensagemConfirmacao": "Lembrete",
        },
    )
    assert resp.status_code == 200
    assert evolution_calls == []  # nada enviado no WhatsApp
    assert google_calls == []
