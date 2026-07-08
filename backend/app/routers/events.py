"""Events router — church events (RF-35/RF-39 / Agenda de Eventos).

Endpoints:
  - GET    /events              paginated events (RNF-09)
  - POST   /events              create a tenant event (persisted locally only)
  - GET    /events/{id}         single tenant event or 404 (EVT-2)
  - PUT    /events/{id}         edit a manual tenant event (EVT-2)
  - DELETE /events/{id}         remove a tenant event (EVT-2)
  - POST   /events/{id}/confirm manual confirmation of an 'a_confirmar' event

EVT-6 PR6.0 — o push legado app→Google foi DESARMADO no POST /events. Ele usava o
token/calendar GLOBAIS de `settings` ("Legacy"), nunca os tokens OAuth por igreja
(`calendar_sync`): em produção isso fazia todas as igrejas escreverem numa única
conta Google compartilhada (risco multi-tenant) e gerava órfãos — PUT não
ressincroniza e DELETE não remove no Google. Agora o evento nasce só no banco com
`google_event_id=null` → `sincronizado=false`. O `GoogleCalendarClient` legado
permanece no código (e seguro pelo guard B2), reservado para um push POR IGREJA de
fase futura. O import Google (Google→app como 'a_confirmar') é o próximo passo
(EVT-6 PR6.1, read-only por igreja).

EVT-2 (CRUD + manual confirmation) is tenant-scoped: every by-id lookup filters
by `igreja_id` on top of RLS, so an event from another tenant is never reachable.
Edit/delete do NOT touch Google Calendar (out of scope, EVT-6+).
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Conversation, Event, EventNotifyTarget
from app.db.session import get_db
from app.deps import CurrentUser, get_current_user, require_role
from app.domain.phone import normalize_phone
from app.routers._common import Page, PaginationParams
from app.services.event_notify import notify_event_confirmed

logger = logging.getLogger("pastorai.events")

# EVT-1: `hora` é texto livre na coluna; aqui validamos HH:MM (24h) no payload
# para não persistir lixo (espelha a CHECK constraint events_hora_formato_chk).
_HORA_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

# EVT-2 — valores do enum event_status usados na confirmação manual.
STATUS_CONFIRMADO = "confirmado"
STATUS_A_CONFIRMAR = "a_confirmar"

# P0b-2 — valores do enum event_tipo (DB, criado no EVT-1). Literal dá validação
# 422 no payload e serializa como string simples; None = evento sem categoria
# (legado/opcional, coluna events.tipo é nullable).
EventTipo = Literal["culto", "reuniao", "celula", "especial", "conferencia"]

# EVT-8 PR1 (D1) — allowlist COLETIVA reestruturada. Literal dá 422 no payload
# para valores fora da lista. Os 5 valores antigos do EVT-8a
# (discipulos/visitantes/casais/jovens/criancas) SAÍRAM do MVP (podem voltar como
# segmentações futuras); a seleção INDIVIDUAL virou `contatos`
# (event_notify_targets), fora deste enum. A resolução de cada público em
# telefones é o PR2 (resolver); aqui só se valida e persiste a intenção.
PublicoAlvo = Literal[
    "toda_igreja",
    "pastores",
    "g12_pastoral",
    "lideres_celula",
]
_PUBLICO_ALVO_MAX = 4

# EVT-8 PR1 (D6) — canal padrão do MVP; envio real (WhatsApp) é EVT-9.
CANAL_PADRAO = "whatsapp"

# EVT-8 PR1 (D4) — a hora do evento é local (texto HH:MM sem fuso). Normalizamos
# `notificar_em` no fuso da igreja (mesmo de app/domain/cell_meetings_schedule).
_SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")


def _normalize_hora(value: str | None) -> str | None:
    """Normaliza/valida `hora` HH:MM (24h); vazio vira None. Reusado nos schemas."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not _HORA_RE.match(value):
        raise ValueError("hora deve estar no formato HH:MM (24h)")
    return value


router = APIRouter(prefix="/events", tags=["events"])


class IndividualTargetOut(BaseModel):
    """Um contato individual da notificação, como persistido (EVT-8 PR1)."""

    pessoaId: str | None = None  # noqa: N815
    telefone: str | None = None


class EventOut(BaseModel):
    id: str
    titulo: str
    # EVT-1: nullable porque eventos semanais (recorrencia='semanal') não têm
    # data específica — espelha events.data, que deixou de ser NOT NULL.
    data: dt.date | None = None
    hora: str | None = None
    descricao: str | None = None
    googleEventId: str | None = None  # noqa: N815
    sincronizado: bool
    # EVT-2: expõe estado da Agenda (aditivo). Optional porque instâncias
    # transientes (server_default só vale no DB) podem ter status=None até o flush.
    status: str | None = None
    tipo: EventTipo | None = None
    origem: str | None = None
    recorrencia: str | None = None
    confirmadoEm: dt.datetime | None = None  # noqa: N815
    confirmadoPor: str | None = None  # noqa: N815
    # EVT-8a — intenção de comunicação persistida no confirm (aditivo, camelCase).
    # None em eventos legados/sem body — coluna é nullable desde o EVT-1.
    publicoAlvo: list[str] | None = None  # noqa: N815
    antecedenciaHoras: int | None = None  # noqa: N815
    mensagemConfirmacao: str | None = None  # noqa: N815
    # EVT-8 PR1 — configuração de notificação do evento (aditivo). `notificarEm`:
    # quando disparar (normalizado, D4). `notificacaoEnviadaEm`: NULL = pendente/
    # futuro — NADA é enviado neste PR. `canal`: whatsapp no MVP (D6). `contatos`:
    # seleção individual — só volta na resposta do confirm (não carregada na
    # listagem, para não fazer um SELECT por evento).
    notificarEm: dt.datetime | None = None  # noqa: N815
    notificacaoEnviadaEm: dt.datetime | None = None  # noqa: N815
    canal: str | None = None
    contatos: list[IndividualTargetOut] | None = None

    @classmethod
    def from_model(
        cls, e: Event, *, contatos: list[IndividualTargetOut] | None = None
    ) -> "EventOut":
        return cls(
            id=str(e.id),
            titulo=e.titulo,
            data=e.data,
            hora=e.hora,
            descricao=e.descricao,
            googleEventId=e.google_event_id,
            sincronizado=e.google_event_id is not None,
            status=e.status,
            tipo=e.tipo,
            origem=e.origem,
            recorrencia=e.recorrencia,
            confirmadoEm=e.confirmado_em,
            confirmadoPor=str(e.confirmado_por) if e.confirmado_por else None,
            publicoAlvo=e.publico_alvo,
            antecedenciaHoras=e.antecedencia_horas,
            mensagemConfirmacao=e.mensagem_confirmacao,
            notificarEm=e.notificar_em,
            notificacaoEnviadaEm=e.notificacao_enviada_em,
            canal=e.canal,
            contatos=contatos,
        )


class CreateEventRequest(BaseModel):
    titulo: str = Field(min_length=1, max_length=200)
    data: dt.date
    hora: str | None = Field(default=None, max_length=10)
    descricao: str | None = Field(default=None, max_length=2000)
    tipo: EventTipo | None = None

    @field_validator("titulo")
    @classmethod
    def _titulo(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("titulo obrigatório")
        return value

    @field_validator("hora")
    @classmethod
    def _hora(cls, value: str | None) -> str | None:
        return _normalize_hora(value)


class UpdateEventRequest(BaseModel):
    """Edição parcial de um evento manual (EVT-2). Campos None = inalterados."""

    titulo: str | None = Field(default=None, max_length=200)
    data: dt.date | None = None
    hora: str | None = Field(default=None, max_length=10)
    descricao: str | None = Field(default=None, max_length=2000)
    tipo: EventTipo | None = None

    @field_validator("titulo")
    @classmethod
    def _titulo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("titulo não pode ser vazio")
        return value

    @field_validator("hora")
    @classmethod
    def _hora(cls, value: str | None) -> str | None:
        return _normalize_hora(value)


class IndividualTargetInput(BaseModel):
    """Um contato individual selecionado para a notificação (EVT-8 PR1, D3).

    A seleção vem de contatos que já conversaram no WhatsApp da igreja (o front
    manda `pessoaId` quando a conversa tem pessoa vinculada, senão o `telefone`).
    O backend valida cada item contra `conversations` do tenant — sem digitação
    livre de telefone. Cada item precisa de pessoaId OU telefone.
    """

    pessoaId: str | None = None  # noqa: N815
    telefone: str | None = None

    @model_validator(mode="after")
    def _requires_identity(self) -> "IndividualTargetInput":
        tem_tel = bool(self.telefone and self.telefone.strip())
        if not self.pessoaId and not tem_tel:
            raise ValueError("cada contato precisa de pessoaId ou telefone")
        return self


class ConfirmEventRequest(BaseModel):
    """Configuração de notificação enviada na confirmação (EVT-8 PR1).

    Tudo opcional: confirmar sem body (ou com `{}`) mantém o comportamento
    anterior (confirma sem notificação). Este PR apenas PERSISTE a intenção
    (público coletivo, contatos individuais, quando, canal, mensagem) — NÃO envia
    nem dispara comunicação alguma (o envio real é EVT-9).
    """

    publicoAlvo: list[PublicoAlvo] | None = None  # noqa: N815
    contatos: list[IndividualTargetInput] | None = None
    antecedenciaHoras: int | None = Field(default=None, ge=0)  # noqa: N815
    notificarEm: dt.datetime | None = None  # noqa: N815
    canal: Literal["whatsapp"] | None = None
    mensagemConfirmacao: str | None = None  # noqa: N815

    @field_validator("publicoAlvo")
    @classmethod
    def _publico(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        # teto checado no BRUTO (antes do dedup), como no EVT-8a.
        if len(value) > _PUBLICO_ALVO_MAX:
            raise ValueError(f"publicoAlvo aceita no máximo {_PUBLICO_ALVO_MAX} itens")
        # dedup preservando a ordem; lista vazia normaliza para None.
        deduped: list[str] = []
        for item in value:
            if item not in deduped:
                deduped.append(item)
        return deduped or None

    @field_validator("contatos")
    @classmethod
    def _contatos(
        cls, value: list[IndividualTargetInput] | None
    ) -> list[IndividualTargetInput] | None:
        if value is None:
            return None
        # Teto defensivo; a resolução real e o dedup por identidade acontecem no
        # handler, contra `conversations`. Lista vazia normaliza para None.
        if len(value) > 500:
            raise ValueError("contatos aceita no máximo 500 itens")
        return value or None

    @field_validator("mensagemConfirmacao")
    @classmethod
    def _mensagem(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if len(value) > 2000:
            raise ValueError("mensagemConfirmacao aceita no máximo 2000 caracteres")
        return value


def _get_event(db: Session, current_user: CurrentUser, event_id: str) -> Event:
    """Busca um evento do tenant por id ou levanta 404.

    Escopo de tenant em dois cintos: a RLS já filtra por igreja_id, e ainda
    adicionamos o predicado explícito `igreja_id` — um evento de outro tenant
    nunca é alcançável, mesmo que o GUC da RLS não estivesse em vigor. Id
    malformado também vira 404 (não vaza diferença entre inválido e inexistente).
    """
    try:
        event_uuid = uuid.UUID(event_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evento não encontrado"
        ) from exc

    event = db.execute(
        select(Event).where(
            Event.id == event_uuid,
            Event.igreja_id == uuid.UUID(current_user.igreja_id),
        )
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evento não encontrado"
        )
    return event


@router.get("", response_model=Page[EventOut])
def list_events(
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> Page[EventOut]:
    """Return the tenant's events, soonest first (RNF-09)."""
    rows = db.execute(
        select(Event)
        .order_by(Event.data.asc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()
    total = len(db.execute(select(Event.id)).scalars().all())
    return Page[EventOut](
        items=[EventOut.from_model(e) for e in rows],
        page=pagination.page,
        pageSize=pagination.page_size,
        total=total,
    )


@router.post("", response_model=EventOut)
def create_event(
    payload: CreateEventRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["pastor"])),
) -> EventOut:
    """Create a tenant event (persisted locally only).

    EVT-6 PR6.0: o push Google legado global foi removido daqui (ver docstring do
    módulo) — criava risco multi-tenant e órfãos. O evento nasce com
    `google_event_id=null` → `sincronizado=false`. A sincronização com o Google
    volta como push POR IGREJA (via calendar_sync) numa fase futura.
    """

    event = Event(
        igreja_id=uuid.UUID(current_user.igreja_id),
        titulo=payload.titulo,
        data=payload.data,
        hora=payload.hora,
        descricao=payload.descricao,
        tipo=payload.tipo,
        google_event_id=None,
    )
    db.add(event)
    db.flush()
    db.refresh(event)
    db.commit()

    return EventOut.from_model(event)


@router.get("/{event_id}", response_model=EventOut)
def get_event(
    event_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> EventOut:
    """Retorna um único evento do tenant ou 404 (RLS + igreja_id).

    Leitura aberta a qualquer usuário autenticado do tenant (como GET /events).
    """
    return EventOut.from_model(_get_event(db, current_user, event_id))


@router.put("/{event_id}", response_model=EventOut)
def update_event(
    event_id: str,
    payload: UpdateEventRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["pastor"])),
) -> EventOut:
    """Edita um evento manual do tenant (pastor/admin).

    Atualização parcial: campos omitidos/None ficam inalterados (espelha
    PATCH /contacts). NÃO re-sincroniza com o Google Calendar — sync na edição é
    escopo de fase posterior (EVT-6+).
    """
    event = _get_event(db, current_user, event_id)

    if payload.titulo is not None:
        event.titulo = payload.titulo
    if payload.data is not None:
        event.data = payload.data
    if payload.hora is not None:
        event.hora = payload.hora
    if payload.descricao is not None:
        event.descricao = payload.descricao
    # tipo é opcional/nullable: `null` explícito limpa a categoria, omissão
    # preserva. Por isso testa presença no payload (model_fields_set), não `is
    # not None` como os demais campos — que não são apagáveis por design.
    if "tipo" in payload.model_fields_set:
        event.tipo = payload.tipo

    db.flush()
    db.refresh(event)
    db.commit()
    return EventOut.from_model(event)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["pastor"])),
) -> Response:
    """Remove um evento do tenant (pastor/admin). Tenant-scoped (RLS + igreja_id).

    NÃO remove o evento espelhado no Google Calendar — fora do escopo (EVT-6+).
    """
    event = _get_event(db, current_user, event_id)
    db.delete(event)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _event_start_dt(event: Event) -> dt.datetime | None:
    """Início do evento no fuso America/Sao_Paulo, ou None se não tem data.

    A hora é texto HH:MM (validado no create/edit); sem hora assume 00:00.
    """
    if event.data is None:
        return None
    hora = event.hora or "00:00"
    try:
        h, m = (int(x) for x in hora.split(":", 1))
    except (ValueError, AttributeError):
        h, m = 0, 0
    return dt.datetime(
        event.data.year, event.data.month, event.data.day, h, m, tzinfo=_SAO_PAULO_TZ
    )


def _derive_notificar_em(
    event: Event, payload: ConfirmEventRequest
) -> dt.datetime | None:
    """Normaliza o "quando" (D4) para um único timestamptz.

    Precedência: `notificarEm` explícito (data/hora específica) sobre
    `antecedenciaHoras` (X antes do evento). Um `notificarEm` naive é interpretado
    no fuso da igreja. Retorna None quando não há como derivar (ex.: antecedência
    informada mas o evento não tem data — recorrente semanal).
    """
    if payload.notificarEm is not None:
        alvo = payload.notificarEm
        if alvo.tzinfo is None:
            alvo = alvo.replace(tzinfo=_SAO_PAULO_TZ)
        return alvo
    if payload.antecedenciaHoras is not None:
        inicio = _event_start_dt(event)
        if inicio is None:
            return None
        return inicio - dt.timedelta(hours=payload.antecedenciaHoras)
    return None


def _resolve_contatos(
    db: Session,
    igreja_id: uuid.UUID,
    contatos: list[IndividualTargetInput],
) -> list[tuple[uuid.UUID | None, str | None]]:
    """Valida cada contato individual contra `conversations` do tenant (D3).

    Cada item precisa corresponder a uma conversa EXISTENTE da própria igreja
    (quem já falou no WhatsApp) — senão 422: isso bloqueia telefone digitado à
    mão e contato de outro tenant (o predicado `igreja_id` fica no WHERE, defesa
    em profundidade além da RLS). Preferimos o `pessoa_id` da conversa; sem pessoa
    vinculada, guardamos o telefone canônico. Dedup por identidade, preservando a
    ordem. NÃO envia nada — só resolve a intenção.
    """
    resolvidos: list[tuple[uuid.UUID | None, str | None]] = []
    vistos: set[tuple[str | None, str | None]] = set()
    for c in contatos:
        if c.pessoaId:
            try:
                pessoa_uuid = uuid.UUID(c.pessoaId)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="pessoaId inválido",
                ) from exc
            conv = db.execute(
                select(Conversation).where(
                    Conversation.pessoa_id == pessoa_uuid,
                    Conversation.igreja_id == igreja_id,
                )
            ).scalar_one_or_none()
        else:
            try:
                telefone = normalize_phone(c.telefone or "")
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="telefone inválido",
                ) from exc
            conv = db.execute(
                select(Conversation).where(
                    Conversation.telefone == telefone,
                    Conversation.igreja_id == igreja_id,
                )
            ).scalar_one_or_none()
        if conv is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Contato não encontrado nas conversas do WhatsApp da igreja",
            )
        # D3 — prefere pessoa_id quando a conversa tem pessoa vinculada.
        pessoa_id = conv.pessoa_id
        tel_final = None if pessoa_id is not None else conv.telefone
        chave = (str(pessoa_id) if pessoa_id is not None else None, tel_final)
        if chave in vistos:
            continue
        vistos.add(chave)
        resolvidos.append((pessoa_id, tel_final))
    return resolvidos


@router.post("/{event_id}/confirm", response_model=EventOut)
def confirm_event(
    event_id: str,
    payload: ConfirmEventRequest | None = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["pastor"])),
) -> EventOut:
    """Confirmação manual de um evento 'a_confirmar' (pastor/admin).

    Só transita a partir de 'a_confirmar' (estado dos eventos importados do
    Google, EVT-6). Confirmar um evento que não está 'a_confirmar' retorna 409.
    Em sucesso: status='confirmado', grava confirmado_em (UTC) e confirmado_por
    (app_user atual). Tenant-scoped.

    EVT-8 PR1: aceita body OPCIONAL de configuração de notificação
    (`ConfirmEventRequest`). Sem body (ou `{}`) o comportamento é idêntico ao
    anterior (confirma sem notificação). Quando vem, PERSISTE a intenção — público
    coletivo, contatos individuais (validados contra as conversas do WhatsApp do
    tenant), `notificar_em` normalizado, canal e mensagem. NÃO envia nem agenda
    comunicação: o disparo real é EVT-9. A validação (409 de estado e 422 do
    payload) acontece ANTES de qualquer persistência.
    """
    event = _get_event(db, current_user, event_id)

    if event.status != STATUS_A_CONFIRMAR:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evento não está aguardando confirmação",
        )

    igreja_id = uuid.UUID(current_user.igreja_id)

    # EVT-8 PR1 — valida a intenção ANTES de confirmar: payload inválido (contato
    # de outro tenant, telefone livre, notificar_em depois do evento) não confirma
    # nem persiste nada.
    contatos_resolvidos: list[tuple[uuid.UUID | None, str | None]] = []
    notificar_em: dt.datetime | None = None
    if payload is not None:
        notificar_em = _derive_notificar_em(event, payload)
        inicio = _event_start_dt(event)
        if notificar_em is not None and inicio is not None and notificar_em >= inicio:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="notificarEm deve ser anterior ao início do evento",
            )
        if payload.contatos:
            contatos_resolvidos = _resolve_contatos(db, igreja_id, payload.contatos)

    event.status = STATUS_CONFIRMADO
    event.confirmado_em = dt.datetime.now(dt.timezone.utc)
    event.confirmado_por = uuid.UUID(current_user.app_user_id)

    contatos_out: list[IndividualTargetOut] | None = None
    if payload is not None:
        event.publico_alvo = payload.publicoAlvo
        event.antecedencia_horas = payload.antecedenciaHoras
        event.mensagem_confirmacao = payload.mensagemConfirmacao
        event.notificar_em = notificar_em
        # Só define canal quando há alguma intenção de notificação; um confirm
        # "seco" (body vazio) não passa a fingir que há WhatsApp configurado.
        tem_notificacao = bool(
            payload.publicoAlvo
            or payload.contatos
            or payload.antecedenciaHoras is not None
            or payload.notificarEm is not None
        )
        if tem_notificacao:
            event.canal = payload.canal or CANAL_PADRAO
        for pessoa_id, telefone in contatos_resolvidos:
            db.add(
                EventNotifyTarget(
                    event_id=event.id,
                    igreja_id=igreja_id,
                    pessoa_id=pessoa_id,
                    telefone=telefone,
                )
            )
        if contatos_resolvidos:
            contatos_out = [
                IndividualTargetOut(
                    pessoaId=str(p) if p is not None else None, telefone=t
                )
                for p, t in contatos_resolvidos
            ]

    db.flush()
    db.refresh(event)
    db.commit()

    # EVT-7 PR1: aviso interno best-effort, atrás da flag AGENDA_NOTIFY_ENABLED.
    # A confirmação já foi commitada acima; o aviso nunca pode 500 o confirm, então
    # engolimos qualquer erro (o próprio notify já trata falha de envio). É outro
    # fluxo (equipe interna via agenda_alert_recipients), não a notificação do
    # evento do EVT-8.
    try:
        notify_event_confirmed(db, event)
    except Exception:  # noqa: BLE001 - aviso é best-effort, não derruba a confirmação
        logger.exception("Falha inesperada ao avisar confirmação de evento")

    return EventOut.from_model(event, contatos=contatos_out)
