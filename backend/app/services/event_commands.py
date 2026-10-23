"""Panel and WhatsApp event commands. Callers own commit and durable receipts."""
import uuid
from fastapi import HTTPException, status
from sqlalchemy import select, or_, and_, func
from sqlalchemy.orm import Session
from app.db.models import Event
from app.deps import CurrentUser
from app.domain.event_notifications import AGENDA_REMINDER_WINDOW_HOURS

STATUS_A_CONFIRMAR = 'a_confirmar'

def _visible_event_filters(current_user: CurrentUser) -> list:
    """Tenant and publication predicates shared by event reads.

    Pending Google imports are editorial drafts. Keeping this rule in the
    backend protects both the collection and direct-by-id reads; write routes
    already require pastor/admin and therefore retain access to confirmation.
    """
    filters = [Event.igreja_id == uuid.UUID(current_user.igreja_id)]
    if not current_user.has_any_role(["pastor"]):
        # Registros legados podem ter status NULL e continuam publicados. A
        # fronteira oculta somente o rascunho editorial explícito.
        filters.append(
            or_(Event.status.is_(None), Event.status != STATUS_A_CONFIRMAR)
        )
    return filters


def _get_event(
    db: Session,
    current_user: CurrentUser,
    event_id: str,
    *,
    for_update: bool = False,
) -> Event:
    """Busca um evento do tenant por id ou levanta 404.

    Escopo de tenant em dois cintos: a RLS já filtra por igreja_id, e ainda
    adicionamos o predicado explícito `igreja_id` — um evento de outro tenant
    nunca é alcançável, mesmo que o GUC da RLS não estivesse em vigor. Id
    malformado também vira 404 (não vaza diferença entre inválido e inexistente).

    `for_update=True` adiciona `SELECT ... FOR UPDATE`: pega o lock de linha
    pessimista na MESMA transação de quem valida+grava (confirmação manual), pra
    fechar a corrida check-then-act. Sob READ COMMITTED, uma segunda transação
    concorrente bloqueia no lock e, ao ser liberada, relê a linha já atualizada —
    a checagem de estado então enxerga o novo status. As leituras puras (GET/PUT/
    DELETE) seguem sem lock (default False).
    """
    try:
        event_uuid = uuid.UUID(event_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evento não encontrado"
        ) from exc

    stmt = select(Event).where(
        Event.id == event_uuid,
        *_visible_event_filters(current_user),
    )
    if for_update:
        stmt = stmt.with_for_update()
    event = db.execute(stmt).scalar_one_or_none()
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evento não encontrado"
        )
    return event


def _write_allowed(current_user):
    if not current_user.has_any_role(['pastor']):
        raise HTTPException(403, 'Sem permissão para alterar a agenda')


def _validate_reminder_configuration(publico_alvo, antecedencia_horas):
    if (
        type(antecedencia_horas) is int
        and antecedencia_horas in AGENDA_REMINDER_WINDOW_HOURS
        and not publico_alvo
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selecione ao menos um público para configurar o lembrete",
        )


def create(db, current_user, payload):
    _write_allowed(current_user)
    _validate_reminder_configuration(
        payload.publicoAlvo, payload.antecedenciaHoras
    )
    event = Event(
        igreja_id=uuid.UUID(current_user.igreja_id),
        titulo=payload.titulo,
        data=payload.data,
        hora=payload.hora,
        descricao=payload.descricao,
        tipo=payload.tipo,
        publico_alvo=payload.publicoAlvo,
        antecedencia_horas=payload.antecedenciaHoras,
        canal="whatsapp" if payload.antecedenciaHoras is not None else None,
        google_event_id=None,
    )
    db.add(event)
    db.flush()
    db.refresh(event)

    return event


def update(db, current_user, event_id, payload):
    _write_allowed(current_user)
    event = _get_event(db, current_user, event_id, for_update=True)
    fields = payload.model_fields_set
    reminder_fields = {"publicoAlvo", "antecedenciaHoras"}
    if fields.intersection(reminder_fields):
        _validate_reminder_configuration(
            payload.publicoAlvo
            if "publicoAlvo" in fields
            else event.publico_alvo,
            payload.antecedenciaHoras
            if "antecedenciaHoras" in fields
            else event.antecedencia_horas,
        )

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
    if "publicoAlvo" in fields:
        event.publico_alvo = payload.publicoAlvo
    if "antecedenciaHoras" in fields:
        event.antecedencia_horas = payload.antecedenciaHoras
        if payload.antecedenciaHoras is not None:
            # A newly selected relative window supersedes any absolute time
            # stored by event confirmation. Removing the relative window alone
            # leaves that independent absolute schedule intact.
            event.notificar_em = None
    if fields.intersection(reminder_fields):
        if event.antecedencia_horas is not None or event.notificar_em is not None:
            event.canal = "whatsapp"
        else:
            event.canal = None

    db.flush()
    db.refresh(event)
    return event


def delete(db, current_user, event_id):
    _write_allowed(current_user)
    event = _get_event(db, current_user, event_id)
    db.delete(event)


def list_page(db, current_user, *, pagination, from_date=None, to_date=None,
              event_status=None, include_undated=False, confirmed_only=False):
    filters = _visible_event_filters(current_user)
    if confirmed_only:
        filters.append(Event.status == 'confirmado')
    date_filters = []
    if to_date is not None:
        date_filters.append(Event.data <= to_date)
    if event_status is not None:
        filters.append(Event.status == event_status)
    if from_date is not None:
        date_filters.append(Event.data >= from_date)
    if date_filters:
        filters.append(or_(and_(*date_filters), Event.data.is_(None)) if include_undated else and_(*date_filters))

    rows = db.execute(
        select(Event)
        .where(*filters)
        .order_by(
            Event.data.asc().nulls_last(),
            Event.hora.asc().nulls_last(),
            Event.id.asc(),
        )
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).scalars().all()
    total = db.execute(
        select(func.count()).select_from(Event).where(*filters)
    ).scalar_one()
    return rows, int(total)
