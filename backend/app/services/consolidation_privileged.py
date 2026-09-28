"""Server-owned V3 projections for the closed WhatsApp catalog."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass, replace
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.models import Consolidacao, Pessoa, WorkQueueItem
from app.db.rls_observability import TenantScopeError, require_tenant_scope
from app.services.consolidation_whatsapp import (
    CONSOLIDATION_WHATSAPP_ROLES,
    consolidation_enabled_from_environment,
    consolidation_panel_link,
)


_SAO_PAULO_TZ = ZoneInfo('America/Sao_Paulo')
_PENDING_TYPES = frozenset({'conectar_celula', 'fonovisita'})
_MAX_VISIBLE_PENDING_ITEMS = 10
_MAX_PANEL_LINK_CHARS = 256


@dataclass(frozen=True, slots=True)
class PendingConsolidationItem:
    """Technical pending-task facts, deliberately without display content."""

    work_queue_item_id: uuid.UUID
    consolidacao_id: uuid.UUID
    pessoa_id: uuid.UUID
    responsavel_id: uuid.UUID | None
    assignment_revision: int
    task_type: str
    due_at: dt.datetime | None
    first_name: str | None = None

    def __post_init__(self) -> None:
        for value in (
            self.work_queue_item_id,
            self.consolidacao_id,
            self.pessoa_id,
        ):
            if type(value) is not uuid.UUID or value.int == 0:
                raise ValueError('identificador de pendência inválido')
        if self.responsavel_id is not None and (
            type(self.responsavel_id) is not uuid.UUID or self.responsavel_id.int == 0
        ):
            raise ValueError('responsável inválido')
        if type(self.assignment_revision) is not int or self.assignment_revision < 0:
            raise ValueError('revisão inválida')
        if self.task_type not in _PENDING_TYPES:
            raise ValueError('tipo de pendência inválido')
        if self.due_at is not None and (
            type(self.due_at) is not dt.datetime or self.due_at.tzinfo is None
        ):
            raise ValueError('prazo inválido')
        if self.task_type == 'conectar_celula' and self.due_at is None:
            raise ValueError('prazo inválido')
        if self.task_type == 'fonovisita' and self.due_at is not None:
            raise ValueError('prazo inválido')
        if self.first_name is not None:
            from app.services.consolidation_whatsapp import template_first_name

            if template_first_name(self.first_name) != self.first_name:
                raise ValueError('nome de template inválido')


@dataclass(frozen=True, slots=True)
class PendingConsolidationReply:
    response: str
    projection_sha256: str


def valid_pending_consolidation_reply_metadata(value: object) -> bool:
    return bool(
        type(value) is dict
        and set(value) == {'projection_sha256'}
        and type(value['projection_sha256']) is str
        and len(value['projection_sha256']) == 64
        and all(character in '0123456789abcdef' for character in value['projection_sha256'])
    )


def _opaque_code(item_id: uuid.UUID) -> str:
    return f'P-{item_id.hex[:10].upper()}'


def _unique_codes(items: tuple[PendingConsolidationItem, ...]) -> tuple[str, ...] | None:
    codes = tuple(_opaque_code(item.work_queue_item_id) for item in items)
    return codes if len(codes) == len(set(codes)) else None


def _projection_sha256(
    items: tuple[PendingConsolidationItem, ...],
    *,
    own_assignment: bool,
) -> str:
    payload = {
        'projection_policy': {
            'max_panel_link_chars': _MAX_PANEL_LINK_CHARS,
            'max_visible_items': _MAX_VISIBLE_PENDING_ITEMS,
            'own_detail': 'first_name_task_due_opaque_code',
            'order': 'work_queue_item_id',
            'visible_selection': 'own_then_work_queue_item_id',
        },
        'mode': 'own' if own_assignment else 'coordination',
        'total_count': len(items),
        'items': [
            {
                'work_queue_item_id': str(item.work_queue_item_id),
                'consolidacao_id': str(item.consolidacao_id),
                'pessoa_id': str(item.pessoa_id),
                'responsavel_id': str(item.responsavel_id)
                if item.responsavel_id is not None
                else None,
                'assignment_revision': item.assignment_revision,
                'task_type': item.task_type,
                'due_at': item.due_at.astimezone(dt.timezone.utc).isoformat(
                    timespec='microseconds'
                )
                if item.due_at is not None
                else None,
                'first_name': item.first_name,
            }
            for item in items
        ],
    }
    encoded = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _own_detail(item: PendingConsolidationItem) -> str:
    if item.first_name is None:
        raise ValueError('projeção inválida')
    task_label = {
        'conectar_celula': 'conexão com célula',
        'fonovisita': 'fonovisita',
    }[item.task_type]
    if item.due_at is None:
        deadline = 'prazo não definido'
    else:
        local = item.due_at.astimezone(_SAO_PAULO_TZ)
        deadline = f'prazo {local:%d/%m/%Y às %H:%M}'
    return (
        f'{item.first_name}, {task_label}, {deadline}, '
        f'código {_opaque_code(item.work_queue_item_id)}'
    )


def render_pending_consolidation_reply(
    items: tuple[PendingConsolidationItem, ...],
    *,
    own_assignment: bool,
    panel_link: str | None,
) -> PendingConsolidationReply:
    """Render a bounded non-PII queue projection and its technical fence."""

    if type(items) is not tuple or type(own_assignment) is not bool:
        raise ValueError('projeção inválida')
    if (
        type(panel_link) is not str
        and panel_link is not None
    ) or (type(panel_link) is str and len(panel_link) > _MAX_PANEL_LINK_CHARS):
        raise ValueError('link inválido')
    if any(type(item) is not PendingConsolidationItem for item in items):
        raise ValueError('projeção inválida')
    ordered = tuple(sorted(items, key=lambda item: str(item.work_queue_item_id)))
    if own_assignment:
        own_items = tuple(item for item in ordered if item.first_name is not None)
        other_items = tuple(item for item in ordered if item.first_name is None)
        visible = (
            own_items[:_MAX_VISIBLE_PENDING_ITEMS]
            + other_items[:max(0, _MAX_VISIBLE_PENDING_ITEMS - len(own_items))]
        )
        own_items = tuple(item for item in visible if item.first_name is not None)
        other_items = tuple(item for item in visible if item.first_name is None)
    else:
        visible = ordered[:_MAX_VISIBLE_PENDING_ITEMS]
        own_items = ()
        other_items = visible
    count = len(ordered)
    remaining = count - len(visible)
    if count == 0:
        response = 'Não há pendências de consolidação no seu escopo.'
    elif own_assignment:
        if not own_items:
            raise ValueError('projeção inválida')
        noun = 'pendência' if len(own_items) == 1 else 'pendências'
        details = '; '.join(_own_detail(item) for item in own_items)
        response = f'Você tem {len(own_items)} {noun} de consolidação: {details}.'
        if other_items:
            other_noun = 'pendência' if len(other_items) == 1 else 'pendências'
            response += f' Há {len(other_items)} outras {other_noun} de consolidação no seu escopo'
            codes = _unique_codes(other_items)
            if codes is not None:
                response += f': {", ".join(codes)}'
            response += '.'
        if remaining:
            total_noun = 'pendência' if count == 1 else 'pendências'
            remaining_noun = 'pendência' if remaining == 1 else 'pendências'
            response += (
                f' Há {count} {total_noun} de consolidação no seu escopo. '
                f'Restam {remaining} {remaining_noun} no painel.'
            )
    else:
        noun = 'pendência' if count == 1 else 'pendências'
        response = f'Há {count} {noun} de consolidação'
        codes = _unique_codes(visible)
        if codes is not None:
            response += f': {", ".join(codes)}'
        response += ' no seu escopo.'
        if remaining:
            remaining_noun = 'pendência' if remaining == 1 else 'pendências'
            response += f' Restam {remaining} {remaining_noun} no painel.'
    if panel_link:
        response += f' Abra o painel: {panel_link}'
    return PendingConsolidationReply(
        response=response,
        projection_sha256=_projection_sha256(ordered, own_assignment=own_assignment),
    )


def _pending_statement(
    igreja_id: uuid.UUID,
    *,
    lock_sources: bool = False,
):
    statement = (
        select(WorkQueueItem, Consolidacao)
        .join(
            Consolidacao,
            and_(
                Consolidacao.igreja_id == WorkQueueItem.igreja_id,
                Consolidacao.id == WorkQueueItem.consolidacao_id,
            ),
        )
        .where(
            WorkQueueItem.igreja_id == igreja_id,
            WorkQueueItem.consolidacao_id.is_not(None),
            WorkQueueItem.tipo.in_(_PENDING_TYPES),
            WorkQueueItem.status.in_(('aberto', 'assumido')),
            Consolidacao.concluida.is_(False),
            Consolidacao.abandonada_em.is_(None),
        )
    )
    if lock_sources:
        # The reply worker already owns Conversation -> Pessoa. Assignment owns
        # Consolidação before its destination Pessoa. Skip a contended source
        # instead of waiting in the inverse order, then let the projection
        # comparison suppress the stale pending response before HTTP.
        statement = statement.with_for_update(
            of=Consolidacao,
            skip_locked=True,
        ).execution_options(populate_existing=True)
    return statement


def _pending_item(
    work_item: object,
    consolidacao: object,
    *,
    igreja_id: uuid.UUID,
) -> PendingConsolidationItem | None:
    work_id = getattr(work_item, 'id', None)
    consolidacao_id = getattr(consolidacao, 'id', None)
    pessoa_id = getattr(consolidacao, 'pessoa_id', None)
    responsavel_id = getattr(consolidacao, 'responsavel_id', None)
    task_type = getattr(work_item, 'tipo', None)
    due_at = getattr(work_item, 'prazo', None)
    if (
        type(work_id) is not uuid.UUID
        or work_id.int == 0
        or type(consolidacao_id) is not uuid.UUID
        or consolidacao_id.int == 0
        or type(pessoa_id) is not uuid.UUID
        or pessoa_id.int == 0
        or getattr(work_item, 'igreja_id', None) != igreja_id
        or getattr(consolidacao, 'igreja_id', None) != igreja_id
        or getattr(work_item, 'consolidacao_id', None) != consolidacao_id
        or task_type not in _PENDING_TYPES
        or getattr(work_item, 'pessoa_id', None) != pessoa_id
        or getattr(work_item, 'responsavel_id', None) != responsavel_id
        or getattr(work_item, 'status', None) not in {'aberto', 'assumido'}
        or getattr(consolidacao, 'concluida', None) is not False
        or getattr(consolidacao, 'abandonada_em', None) is not None
    ):
        return None
    try:
        return PendingConsolidationItem(
            work_queue_item_id=work_id,
            consolidacao_id=consolidacao_id,
            pessoa_id=pessoa_id,
            responsavel_id=responsavel_id,
            assignment_revision=getattr(consolidacao, 'assignment_revision', None),
            task_type=task_type,
            due_at=due_at,
        )
    except ValueError:
        return None


def _with_current_first_names(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    items: tuple[PendingConsolidationItem, ...],
) -> tuple[PendingConsolidationItem, ...] | None:
    """Attach only normalized first names for the current responsible user."""

    person_ids = tuple(sorted({item.pessoa_id for item in items}, key=str))
    if not person_ids:
        return ()
    rows = session.execute(
        select(Pessoa.id, Pessoa.nome).where(
            Pessoa.igreja_id == igreja_id,
            Pessoa.id.in_(person_ids),
            Pessoa.arquivada_em.is_(None),
        )
    ).all()
    names = {
        pessoa_id: name
        for pessoa_id, name in rows
        if type(pessoa_id) is uuid.UUID and pessoa_id in person_ids
    }
    if len(names) != len(person_ids):
        return None
    from app.services.consolidation_whatsapp import template_first_name

    resolved: list[PendingConsolidationItem] = []
    for item in items:
        first_name = template_first_name(names.get(item.pessoa_id))
        if first_name is None:
            return None
        resolved.append(replace(item, first_name=first_name))
    return tuple(resolved)


def consolidation_pending_reply(
    session: Session,
    *,
    context: object,
    for_transport: bool = False,
) -> PendingConsolidationReply | None:
    """Build a current, opaque V3 queue projection under the existing scope."""

    from app.config import get_settings
    from app.services.whatsapp_privilege import PrivilegeContext

    if (
        type(context) is not PrivilegeContext
        or not bool(context.roles & CONSOLIDATION_WHATSAPP_ROLES)
        or not consolidation_enabled_from_environment(context.igreja_id)
    ):
        return None
    try:
        require_tenant_scope(
            session,
            expected_igreja_id=context.igreja_id,
            source='consolidation_pending_reply',
        )
        statement = _pending_statement(
            context.igreja_id,
            lock_sources=for_transport,
        )
        rows = session.execute(
            statement.order_by(WorkQueueItem.created_at.asc(), WorkQueueItem.id.asc())
        ).all()
    except (TenantScopeError, TypeError, ValueError):
        return None
    items: list[PendingConsolidationItem] = []
    for row in rows:
        try:
            work_item, consolidacao = row
        except (TypeError, ValueError):
            return None
        item = _pending_item(work_item, consolidacao, igreja_id=context.igreja_id)
        if item is None:
            return None
        items.append(item)
    ordered_items = tuple(sorted(items, key=lambda item: str(item.work_queue_item_id)))
    own_items = tuple(
        item for item in ordered_items if item.responsavel_id == context.app_user_id
    )
    if own_items:
        visible = _with_current_first_names(
            session,
            igreja_id=context.igreja_id,
            items=own_items[:_MAX_VISIBLE_PENDING_ITEMS],
        )
        if visible is None:
            return None
        names_by_item_id = {
            item.work_queue_item_id: item
            for item in visible
        }
        visible = tuple(
            names_by_item_id.get(item.work_queue_item_id, item)
            for item in ordered_items
        )
    else:
        visible = ordered_items
    panel_link = consolidation_panel_link(get_settings().frontend_url)
    return render_pending_consolidation_reply(
        visible,
        own_assignment=bool(own_items),
        panel_link=panel_link,
    )


def consolidation_pending_reply_still_authorized(
    session: Session,
    *,
    context: object,
    response: object,
    projection_sha256: object,
) -> bool:
    """Rebuild a queued reply and suppress it if its scope changed."""

    if (
        type(response) is not str
        or type(projection_sha256) is not str
        or len(projection_sha256) != 64
        or any(character not in '0123456789abcdef' for character in projection_sha256)
    ):
        return False
    current = consolidation_pending_reply(session, context=context, for_transport=True)
    return bool(
        current is not None
        and current.response == response
        and current.projection_sha256 == projection_sha256
    )


__all__ = [
    'PendingConsolidationItem',
    'PendingConsolidationReply',
    'consolidation_pending_reply',
    'consolidation_pending_reply_still_authorized',
    'render_pending_consolidation_reply',
    'valid_pending_consolidation_reply_metadata',
]
