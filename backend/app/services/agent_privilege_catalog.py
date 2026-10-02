"""Server-owned catalog and human-service adapters for closed S3 actions."""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    AppUser,
    Celula,
    CelulaMembro,
    CelulaReuniao,
    Conversation,
    Message,
    Pessoa,
    UserRole,
)
from app.db.rls_observability import require_tenant_scope
from app.db.tenant_session import TenantScopeError
from app.deps import CurrentUser
from app.domain import cell_meetings_schedule
from app.domain.agent_authz import MINISTERIAL_ROLES, CONSOLIDATION_TOOL_ROLES
from app.domain.consolidation import VALID_VINCULOS
from app.services.ministerial_actions import (
    can_mark_for_other, confirm_meeting_attendance, register_decision,
    register_own_visitor_expectation,
)
from app.services.whatsapp_agenda import (
    AGENDA_TIMEZONE,
    AgendaOccurrence,
    AgendaQuery,
    _query_rows,
    agenda_enabled_from_environment,
    agenda_read_allowed,
    occurrences_for_event,
)
from app.services.consolidation_whatsapp import (
    CONSOLIDATION_WHATSAPP_ROLES,
    consolidation_coordination_allowed,
    consolidation_enabled_from_environment,
    consolidation_responsible_allowed,
    consolidation_responsible_task_types,
)

ACTIONS = frozenset({'registrar_decisao', 'marcar_presenca', 'registrar_expectativa_visitante'})
PROPOSAL_ACTIONS = ACTIONS | frozenset({
    'configurar_lembrete_agenda',
    'configurar_lembrete_consolidacao',
    'marcar_fonovisita_feita',
    'atribuir_consolidacao',
})
_PERSON_ACTIONS = frozenset({'registrar_decisao', 'marcar_presenca'})
_OWN_PRESENCE_REQUEST = re.compile(
    r'(?:quero confirmar|confirmar|eu confirmo) minha presenca '
    r'na (?P<next>proxima )?reuniao(?: da minha celula)?'
)
_REMINDER_REQUEST = re.compile(
    r'\b(?:lembrete(?:s)?|lembre[- ]?me|avise[- ]?me|me[ -](?:lembre|avise))\b'
)
_SAFE_HOUR = re.compile(r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
_TERM_CHARS = frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:/-')
_CONFIRMATION_SUFFIX = '. Confirma esta ação? Responda SIM ou NÃO. A proposta vale por 10 minutos.'
_CONSOLIDATION_REMINDER_REQUESTS = frozenset({
    'quero ativar lembretes de consolidacao',
    'ativar lembretes de consolidacao',
})
_CONSOLIDATION_PENDING_TYPES = frozenset({'conectar_celula', 'fonovisita'})
_CONSOLIDATION_SELF_ASSIGNMENT = re.compile(r'(?<!\w)(?:para|pra)\s+mim(?!\w)')
_CONSOLIDATION_CODE = re.compile(r'(?<![\w-])P-[0-9A-F]{10}(?![\w-])', re.IGNORECASE)
_FONOVISITA_REQUEST = re.compile(r'(?<!\w)fonovisita(?!\w)')
_ASSIGNMENT_REQUEST = re.compile(r'(?<!\w)(?:atribuir|atribua|distribuir)(?!\w)')
_DECISION_REQUEST = re.compile(r'(?<!\w)registrar\s+decisao(?!\w)')
_CONSOLIDATION_QUERY_REQUEST = re.compile(r'(?<!\w)(?:pendencia(?:s)?|consolidacao)(?!\w)')
_CONSOLIDATION_FONOVISITA_COMMAND = re.compile(
    r'^(?:marcar|confirmar)\s+fonovisita(?:\s+feita)?(?:\s+P-[0-9A-F]{10})?$',
    re.IGNORECASE,
)
_CONSOLIDATION_ASSIGNMENT_COMMAND = re.compile(
    r'^(?:atribuir|atribua|distribuir)'
    r'(?:\s+(?:a\s+)?(?:consolidacao|pendencia))?'
    r'(?:\s+P-[0-9A-F]{10})?'
    r'\s+(?:para|pra)\s+(?P<target>.+)$',
    re.IGNORECASE,
)
_CONSOLIDATION_DECISION_COMMAND = re.compile(
    r'^registrar\s+decisao\s+de\s+(?P<target>.+)$', re.IGNORECASE
)
_CONSOLIDATION_QUERY_COMMANDS = frozenset({
    'pendencias de consolidacao',
    'quais pendencias de consolidacao',
    'quais pendencias de consolidacao existem',
    'consultar pendencias de consolidacao',
})


@dataclass(frozen=True)
class CatalogTarget:
    code: str
    arguments: Mapping[str, Any]
    summary: str
    sensitive: bool = False


@dataclass(frozen=True)
class ConsolidationRoutingProjection:
    """Safe V3-only description sent to the external closed-catalog router."""

    text: str
    required_codes: tuple[str, ...]
    handoff_only: bool = False


def action_allowed(context, code: str) -> bool:
    if code == 'registrar_decisao':
        return bool(context.roles & CONSOLIDATION_TOOL_ROLES)
    if code == 'marcar_presenca':
        return bool(context.roles & MINISTERIAL_ROLES)
    if code == 'configurar_lembrete_agenda':
        return agenda_read_allowed(context)
    if code == 'configurar_lembrete_consolidacao':
        return consolidation_responsible_allowed(context.roles)
    if code == 'consultar_pendencias_consolidacao':
        return consolidation_responsible_allowed(context.roles)
    if code == 'marcar_fonovisita_feita':
        return 'fonovisita' in consolidation_responsible_task_types(context.roles)
    if code == 'atribuir_consolidacao':
        return consolidation_coordination_allowed(context.roles)
    return False


def validated_action_arguments(code: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    if code == 'registrar_expectativa_visitante':
        from app.services.agent_action_proposals import (
            AgentAction, ProposalTarget, canonical_action_arguments,
        )
        if type(arguments) is not dict or set(arguments) != {'reuniao_id', 'nome_visitante'}:
            raise ValueError('action arguments')
        try:
            target = ProposalTarget('reuniao', uuid.UUID(arguments['reuniao_id']))
        except (TypeError, ValueError, AttributeError):
            raise ValueError('target') from None
        return canonical_action_arguments(AgentAction.REGISTRAR_EXPECTATIVA_VISITANTE, target, arguments)
    expected = {'pessoa_id', 'vinculo', 'celula_id'} if code == 'registrar_decisao' else {'pessoa_id', 'reuniao_id'}
    if code not in ACTIONS or set(arguments) != expected:
        raise ValueError('action arguments')
    args = dict(arguments)
    for key in expected - {'vinculo'}:
        if key == 'celula_id' and args[key] is None:
            continue
        if type(args[key]) is not str or str(uuid.UUID(args[key])) != args[key]:
            raise ValueError('target')
    if code == 'registrar_decisao' and args['vinculo'] not in VALID_VINCULOS:
        raise ValueError('vinculo')
    return args


def _user(context) -> CurrentUser:
    # The domain service receives only a revalidated server context, never claims
    # supplied by the model. No session is minted and no HTTP endpoint is called.
    return CurrentUser(app_user_id=str(context.app_user_id), clerk_user_id='',
        igreja_id=str(context.igreja_id), email='', nome='', roles=context.roles)


def _label(value: object, limit: int = 65) -> str:
    text = ''.join(c for c in str(value or '') if unicodedata.category(c) not in {'Cc','Cf'})
    return ' '.join(text.replace('<','(').replace('>',')').split())[:limit]


def _label_key(value: object) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', _label(value)).casefold()
                   if not unicodedata.combining(c))


def _mentioned_name(text: str, name: str) -> bool:
    normalized = ' '.join(''.join(c for c in unicodedata.normalize('NFKD', text).casefold()
        if not unicodedata.combining(c) and unicodedata.category(c) not in {'Cf'}).split())
    key = _label_key(name)
    return bool(key and re.search(r'(?<!\w)' + re.escape(key) + r'(?!\w)', normalized))


def _own_presence_intent(value: object) -> str | None:
    """Admit only an affirmative own request, never a name or loose keyword."""
    if type(value) is not str or not value or len(value) > 240:
        return None
    normalized = ''.join(char for char in unicodedata.normalize('NFKD', value).casefold()
                         if not unicodedata.combining(char))
    normalized = ' '.join(normalized.split()).rstrip('.!')
    match = _OWN_PRESENCE_REQUEST.fullmatch(normalized)
    return ('next' if match.group('next') else 'generic') if match else None


def _own_presence_requested(value: object) -> bool:
    return _own_presence_intent(value) is not None


def _own_presence_targets(session: Session, context, *, requested_text: object) -> tuple[CatalogTarget, ...]:
    intent = _own_presence_intent(requested_text)
    if intent is None:
        return ()
    selected = _own_meeting_selection(session, context, intent=intent)
    if selected is None:
        return ()
    cell, meeting = selected
    hour = f' às {meeting.hora}' if type(meeting.hora) is str and _SAFE_HOUR.fullmatch(meeting.hora) else ''
    return (CatalogTarget('marcar_presenca', MappingProxyType({
        'pessoa_id': str(context.pessoa_id), 'reuniao_id': str(meeting.id),
    }), f'Confirmar minha presença em {_label(cell.nome)}, {meeting.data.isoformat()}{hour}'),)


def own_visitor_command(value: object) -> tuple[bool, str | None]:
    """Separate a local attempt from a valid command; never project the name."""
    if type(value) is not str:
        return False, None
    text = value.strip()
    if not re.match(r'^(?:(?:n[aã]o|quero|se puder)\s+)?indicar\b', text, re.IGNORECASE):
        return False, None
    match = re.fullmatch(
        r'indicar (?P<name>.*?) como visitante na próxima reunião da minha célula',
        text, flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return True, None
    from app.services.agent_action_proposals import canonical_visitor_name, ProposalContractError
    try:
        return True, canonical_visitor_name(match.group('name'))
    except ProposalContractError:
        return True, None


def _own_visitor_targets(session: Session, context, *, requested_text: object) -> tuple[CatalogTarget, ...]:
    _, name = own_visitor_command(requested_text)
    if name is None:
        return ()
    selected = _own_meeting_selection(session, context, intent='next')
    if selected is None:
        return ()
    _, meeting = selected
    return (CatalogTarget('registrar_expectativa_visitante', MappingProxyType({
        'reuniao_id': str(meeting.id),
    }), 'Indicar visitante na próxima reunião da minha célula'),)


def visitor_expectation_arguments_authorized(session: Session, *, context, target, arguments, summary) -> bool:
    """Rebind private arguments to the anchored command and a current own slot."""
    from app.services.whatsapp_privilege import PrivilegeContext
    if type(context) is not PrivilegeContext or target.kind != 'reuniao':
        return False
    source = session.execute(select(Message.texto).where(
        Message.igreja_id == context.igreja_id, Message.conversation_id == context.conversation_id,
        Message.id == context.inbound_message_id, Message.direcao == 'in',
    )).scalar_one_or_none()
    _, name = own_visitor_command(source)
    if name is None or arguments != {'reuniao_id': str(target.id), 'nome_visitante': name}:
        return False
    targets = _own_visitor_targets(session, context, requested_text=source)
    return any(item.arguments['reuniao_id'] == str(target.id)
               and summary == item.summary + _CONFIRMATION_SUFFIX for item in targets)


def _own_meeting_selection(session: Session, context, *, intent: str):
    """Shared bounded own selection; membership never comes from leadership."""
    from app.services.whatsapp_privilege import PrivilegeContext

    if (type(context) is not PrivilegeContext or intent not in {'next', 'generic'}
        or any(type(value) is not uuid.UUID or value.int == 0 for value in (
            context.igreja_id, context.pessoa_id, context.app_user_id))):
        return None
    memberships = session.execute(select(CelulaMembro).where(
        CelulaMembro.igreja_id == context.igreja_id,
        CelulaMembro.pessoa_id == context.pessoa_id,
        CelulaMembro.ativo.is_(True),
    ).limit(2).execution_options(populate_existing=True)).scalars().all()
    if len(memberships) != 1:
        return None
    cell = session.execute(select(Celula).where(
        Celula.id == memberships[0].celula_id, Celula.igreja_id == context.igreja_id,
        Celula.ativo.is_(True),
    ).execution_options(populate_existing=True)).scalar_one_or_none()
    if cell is None:
        return None
    now = cell_meetings_schedule.now_in_sao_paulo()
    meetings = session.execute(select(CelulaReuniao).where(
        CelulaReuniao.igreja_id == context.igreja_id, CelulaReuniao.celula_id == cell.id,
        CelulaReuniao.data >= now.date(),
    ).order_by(CelulaReuniao.data, CelulaReuniao.id).limit(65)
        .execution_options(populate_existing=True)).scalars().all()
    sentinel = meetings[64] if len(meetings) > 64 else None
    eligible = [meeting for meeting in meetings[:64] if not cell_meetings_schedule.meeting_has_passed(
        data=meeting.data, hora=meeting.hora, now=now,
    )]
    if not eligible:
        return None
    if intent == 'generic':
        if sentinel is not None or len(eligible) != 1:
            return None
        meeting = eligible[0]
    else:
        first_date = eligible[0].data
        # Only a complete earliest date can determine "next". A sentinel on
        # that date can hide an earlier hour or a tie beyond the window.
        if sentinel is not None and sentinel.data <= first_date:
            return None
        first_day = [meeting for meeting in eligible if meeting.data == first_date]
        if len(first_day) == 1:
            meeting = first_day[0]  # E4 permits an absent hour when unambiguous.
        else:
            if any(type(meeting.hora) is not str or not _SAFE_HOUR.fullmatch(meeting.hora)
                   for meeting in first_day):
                return None
            earliest_hour = min(meeting.hora for meeting in first_day)
            earliest = [meeting for meeting in first_day if meeting.hora == earliest_hour]
            if len(earliest) != 1:
                return None
            meeting = earliest[0]
    return cell, meeting


def _valid_term_version(value: object) -> str | None:
    if (
        type(value) is not str
        or not 1 <= len(value) <= 128
        or value[0] not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
        or any(character not in _TERM_CHARS for character in value)
    ):
        return None
    return value


def _current_term_version() -> str | None:
    return _valid_term_version(getattr(get_settings(), 'agent_term_version', None))


def _agenda_reminder_requested(value: object) -> bool:
    if type(value) is not str or not value or len(value) > 1200:
        return False
    normalized = unicodedata.normalize('NFKD', value).casefold()
    normalized = ''.join(
        character
        for character in normalized
        if not unicodedata.combining(character) and unicodedata.category(character) != 'Cf'
    )
    return _REMINDER_REQUEST.search(' '.join(normalized.split())) is not None


def _consolidation_reminder_requested(value: object) -> bool:
    """Allow only an explicit, fixed opt-in request to enter the catalog.

    This is candidate admission only. The router still selects the closed
    catalog capability and S3 revalidates it before creating a proposal.
    """

    if type(value) is not str or not value or len(value) > 1200:
        return False
    normalized = unicodedata.normalize('NFKD', value).casefold()
    normalized = ''.join(
        character
        for character in normalized
        if not unicodedata.combining(character)
        and unicodedata.category(character) not in {'Cc', 'Cf'}
    )
    normalized = ' '.join(normalized.split()).strip(' .!?')
    return normalized in _CONSOLIDATION_REMINDER_REQUESTS


def _consolidation_reminder_target(
    context: object,
    *,
    requested_text: object,
) -> CatalogTarget | None:
    """Produce the self-only, current-term opt-in target without PII."""

    from app.services.whatsapp_privilege import PrivilegeContext

    if (
        type(context) is not PrivilegeContext
        or not _consolidation_reminder_requested(requested_text)
        or not consolidation_enabled_from_environment(context.igreja_id)
        or not action_allowed(context, 'configurar_lembrete_consolidacao')
        or type(context.pessoa_id) is not uuid.UUID
        or context.pessoa_id.int == 0
    ):
        return None
    term_version = _current_term_version()
    if term_version is None:
        return None
    return CatalogTarget(
        'configurar_lembrete_consolidacao',
        MappingProxyType({
            'pessoa_id': str(context.pessoa_id),
            'term_version': term_version,
        }),
        'Ativar lembretes de pendências de consolidação',
    )


def _occurrence_at(occurrence: AgendaOccurrence) -> str | None:
    if (
        type(occurrence.date) is not dt.date
        or type(occurrence.hour) is not str
        or _SAFE_HOUR.fullmatch(occurrence.hour) is None
    ):
        return None
    hour, minute = (int(piece) for piece in occurrence.hour.split(':'))
    local = dt.datetime.combine(
        occurrence.date,
        dt.time(hour=hour, minute=minute),
        tzinfo=AGENDA_TIMEZONE,
    )
    return local.astimezone(dt.timezone.utc).isoformat(timespec='microseconds')


def _agenda_reminder_targets_from_occurrences(
    occurrences: tuple[AgendaOccurrence, ...],
    *,
    requested_text: object,
    term_version: object,
    now: object,
) -> tuple[CatalogTarget, ...]:
    """Return only a deterministically selected future Agenda occurrence."""

    if (
        not _agenda_reminder_requested(requested_text)
        or _valid_term_version(term_version) is None
        or type(now) is not dt.datetime
        or now.tzinfo is None
    ):
        return ()
    local_now = now.astimezone(AGENDA_TIMEZONE)
    candidates: list[tuple[CatalogTarget, str, str, str]] = []
    for occurrence in occurrences:
        event_id = getattr(occurrence, 'event_id', None)
        label = _label(getattr(occurrence, 'label', None))
        occurrence_at = _occurrence_at(occurrence)
        if type(event_id) is not uuid.UUID or event_id.int == 0 or not label or occurrence_at is None:
            continue
        local_occurrence = dt.datetime.fromisoformat(occurrence_at).astimezone(AGENDA_TIMEZONE)
        if local_occurrence <= local_now:
            continue
        date_label = occurrence.date.strftime('%d/%m/%Y')
        iso_date = occurrence.date.isoformat()
        summary = f'Ativar lembretes da Agenda para {label} em {date_label} às {occurrence.hour}'
        candidates.append((
            CatalogTarget(
                'configurar_lembrete_agenda',
                MappingProxyType({
                    'event_id': str(event_id),
                    'occurrence_at': occurrence_at,
                    'term_version': term_version,
                }),
                summary,
            ),
            label,
            date_label,
            iso_date,
        ))
    candidates.sort(key=lambda item: (
        item[0].arguments['occurrence_at'],
        item[0].arguments['event_id'],
    ))
    if len(candidates) == 1:
        return (candidates[0][0],)
    selected = [
        target
        for target, label, date_label, iso_date in candidates
        if _mentioned_name(requested_text, label)
        and (date_label in requested_text or iso_date in requested_text)
    ]
    return tuple(selected) if len(selected) == 1 else ()


def _agenda_reminder_targets(
    session: Session,
    context: object,
    *,
    requested_text: object | None = None,
    now: dt.datetime | None = None,
) -> tuple[CatalogTarget, ...]:
    """Read a bounded confirmed-event projection after all S3 gates are closed."""

    from app.services.whatsapp_privilege import PrivilegeContext

    tenant = getattr(context, 'igreja_id', None)
    if (
        type(context) is not PrivilegeContext
        or type(tenant) is not uuid.UUID
        or not agenda_enabled_from_environment(tenant)
        or not agenda_read_allowed(context)
    ):
        return ()
    try:
        require_tenant_scope(
            session,
            expected_igreja_id=tenant,
            source='agent_privilege_catalog.agenda_reminder',
        )
    except (TenantScopeError, ValueError):
        return ()
    if requested_text is None:
        requested_text = session.execute(select(Message.texto).where(
            Message.igreja_id == tenant,
            Message.conversation_id == context.conversation_id,
            Message.id == context.inbound_message_id,
            Message.direcao == 'in',
        )).scalar_one_or_none()
    if not _agenda_reminder_requested(requested_text):
        return ()
    term_version = _current_term_version()
    observed = now or dt.datetime.now(AGENDA_TIMEZONE)
    if term_version is None or type(observed) is not dt.datetime or observed.tzinfo is None:
        return ()
    start = observed.astimezone(AGENDA_TIMEZONE).date()
    rows = _query_rows(
        session,
        igreja_id=tenant,
        query=AgendaQuery(days=30, page=1, include_drafts=False),
        start=start,
        end=start + dt.timedelta(days=29),
    )
    if rows is None:
        return ()
    occurrences = tuple(
        occurrence
        for event in rows
        for occurrence in occurrences_for_event(
            event,
            start=start,
            end=start + dt.timedelta(days=29),
        )
    )
    return _agenda_reminder_targets_from_occurrences(
        occurrences,
        requested_text=requested_text,
        term_version=term_version,
        now=observed,
    )


def agenda_reminder_arguments_authorized(
    session: Session,
    *,
    context: object,
    target: object,
    arguments: object,
    summary: object | None = None,
) -> bool:
    """Recompute the opaque selection before a reminder proposal is persisted."""

    from app.services.agent_action_proposals import (
        AgentAction,
        ProposalContractError,
        ProposalTarget,
        canonical_action_arguments,
    )
    from app.services.whatsapp_privilege import PrivilegeContext

    if (
        type(context) is not PrivilegeContext
        or type(target) is not ProposalTarget
        or type(arguments) is not dict
        or not agenda_enabled_from_environment(context.igreja_id)
        or not agenda_read_allowed(context)
    ):
        return False
    try:
        canonical = canonical_action_arguments(
            AgentAction.CONFIGURAR_LEMBRETE_AGENDA,
            target,
            arguments,
        )
    except ProposalContractError:
        return False
    for candidate in _agenda_reminder_targets(session, context):
        try:
            candidate_id = uuid.UUID(candidate.arguments['event_id'])
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if (
            candidate.code == 'configurar_lembrete_agenda'
            and target.kind == 'evento'
            and target.id == candidate_id
            and canonical == dict(candidate.arguments)
            and (
                summary is None
                or summary == f'{candidate.summary}{_CONFIRMATION_SUFFIX}'
            )
        ):
            return True
    return False


def consolidation_reminder_arguments_authorized(
    session: Session,
    *,
    context: object,
    target: object,
    arguments: object,
    summary: object | None = None,
) -> bool:
    """Revalidate a self-only consolidation opt-in before S3 persists it."""

    from app.services.agent_action_proposals import (
        AgentAction,
        ProposalContractError,
        ProposalTarget,
        canonical_action_arguments,
    )
    from app.services.whatsapp_privilege import PrivilegeContext

    if (
        type(context) is not PrivilegeContext
        or type(target) is not ProposalTarget
        or type(arguments) is not dict
    ):
        return False
    candidate = _consolidation_reminder_target(
        context,
        requested_text=_current_consolidation_message_text(session, context),
    )
    if candidate is None:
        return False
    try:
        canonical = canonical_action_arguments(
            AgentAction.CONFIGURAR_LEMBRETE_CONSOLIDACAO,
            target,
            arguments,
        )
    except ProposalContractError:
        return False
    return bool(
        target.kind == 'pessoa'
        and target.id == context.pessoa_id
        and canonical == dict(candidate.arguments)
        and (
            summary is None
            or summary == f'{candidate.summary}{_CONFIRMATION_SUFFIX}'
        )
    )


def _normalized_consolidation_text(value: object) -> str:
    if type(value) is not str or not value or len(value) > 1200:
        return ''
    normalized = unicodedata.normalize('NFKD', value).casefold()
    normalized = ''.join(
        character
        for character in normalized
        if not unicodedata.combining(character)
        and unicodedata.category(character) not in {'Cc', 'Cf'}
    )
    return ' '.join(normalized.split())


def _consolidation_code(item_id: object) -> str | None:
    if type(item_id) is not uuid.UUID or item_id.int == 0:
        return None
    return f'P-{item_id.hex[:10].upper()}'


def _source_from_pending_items(
    items: object,
    *,
    requested_text: object,
    one_track: bool,
):
    """Select a source only by an unambiguous opaque code or one track."""

    from app.services.consolidation_privileged import PendingConsolidationItem

    if type(items) is not tuple:
        return None
    codes: dict[str, PendingConsolidationItem] = {}
    tracks: dict[uuid.UUID, list[PendingConsolidationItem]] = {}
    for item in items:
        if type(item) is not PendingConsolidationItem:
            return None
        code = _consolidation_code(item.work_queue_item_id)
        if code is None or code in codes:
            return None
        codes[code] = item
        tracks.setdefault(item.consolidacao_id, []).append(item)
    normalized = _normalized_consolidation_text(requested_text)
    if not normalized:
        return None
    mentioned = tuple(
        dict.fromkeys(_CONSOLIDATION_CODE.findall(normalized.upper()))
    )
    if mentioned:
        if len(mentioned) != 1:
            return None
        return codes.get(mentioned[0])
    if not one_track or len(tracks) != 1:
        return None
    only_items = next(iter(tracks.values()))
    return min(only_items, key=lambda item: str(item.work_queue_item_id))


def _fonovisita_target_from_items(
    context: object,
    items: object,
    *,
    requested_text: object,
) -> CatalogTarget | None:
    """Build one fono target for the current responsible only."""

    from app.services.consolidation_privileged import PendingConsolidationItem
    from app.services.whatsapp_privilege import PrivilegeContext

    if (
        type(context) is not PrivilegeContext
        or not action_allowed(context, 'marcar_fonovisita_feita')
        or type(items) is not tuple
        or _FONOVISITA_REQUEST.search(_normalized_consolidation_text(requested_text)) is None
    ):
        return None
    candidates = tuple(
        item
        for item in items
        if type(item) is PendingConsolidationItem
        and item.task_type == 'fonovisita'
        and item.responsavel_id == context.app_user_id
    )
    item = _source_from_pending_items(
        candidates,
        requested_text=requested_text,
        one_track=True,
    )
    if item is None:
        return None
    code = _consolidation_code(item.work_queue_item_id)
    if code is None:
        return None
    return CatalogTarget(
        'marcar_fonovisita_feita',
        MappingProxyType({
            'work_queue_item_id': str(item.work_queue_item_id),
            'consolidacao_id': str(item.consolidacao_id),
            'assignment_revision': item.assignment_revision,
        }),
        f'Confirmar fonovisita pendente {code}',
    )


def _eligible_consolidation_users(session: Session, context: object) -> dict[uuid.UUID, str]:
    """Resolve eligible assignment targets server-side, without catalog PII."""

    from app.services.whatsapp_privilege import PrivilegeContext

    if (
        type(context) is not PrivilegeContext
        or not action_allowed(context, 'atribuir_consolidacao')
    ):
        return {}
    try:
        require_tenant_scope(
            session,
            expected_igreja_id=context.igreja_id,
            source='agent_privilege_catalog.consolidation_assignment',
        )
        rows = session.execute(
            select(AppUser.id, Pessoa.nome)
            .join(
                Pessoa,
                and_(
                    Pessoa.igreja_id == AppUser.igreja_id,
                    Pessoa.id == AppUser.pessoa_id,
                ),
            )
            .join(
                UserRole,
                and_(
                    UserRole.igreja_id == AppUser.igreja_id,
                    UserRole.user_id == AppUser.id,
                ),
            )
            .where(
                AppUser.igreja_id == context.igreja_id,
                AppUser.status == 'ativo',
                Pessoa.arquivada_em.is_(None),
                UserRole.papel.in_(tuple(sorted(CONSOLIDATION_WHATSAPP_ROLES))),
            )
        ).all()
    except (TenantScopeError, TypeError, ValueError, AttributeError):
        return {}
    users: dict[uuid.UUID, str] = {}
    for app_user_id, nome in rows:
        label = _label(nome)
        if (
            type(app_user_id) is not uuid.UUID
            or app_user_id.int == 0
            or not _label_key(label)
        ):
            return {}
        prior = users.setdefault(app_user_id, label)
        if prior != label:
            return {}
    return users


def _assignment_target_from_items(
    context: object,
    items: object,
    *,
    requested_text: object,
    eligible_users: object,
) -> CatalogTarget | None:
    """Select an open track and an eligible recipient without exposing names."""

    from app.services.whatsapp_privilege import PrivilegeContext

    if (
        type(context) is not PrivilegeContext
        or not action_allowed(context, 'atribuir_consolidacao')
        or type(eligible_users) is not dict
        or _ASSIGNMENT_REQUEST.search(_normalized_consolidation_text(requested_text)) is None
    ):
        return None
    item = _source_from_pending_items(
        items,
        requested_text=requested_text,
        one_track=True,
    )
    if item is None:
        return None
    users: dict[uuid.UUID, str] = {}
    for app_user_id, name in eligible_users.items():
        label = _label(name)
        if (
            type(app_user_id) is not uuid.UUID
            or app_user_id.int == 0
            or not _label_key(label)
        ):
            return None
        users[app_user_id] = label
    normalized = _normalized_consolidation_text(requested_text)
    if not normalized:
        return None
    names = Counter(_label_key(name) for name in users.values())
    mentioned = tuple(
        app_user_id
        for app_user_id, name in users.items()
        if names[_label_key(name)] == 1 and _mentioned_name(normalized, name)
    )
    self_requested = _CONSOLIDATION_SELF_ASSIGNMENT.search(normalized) is not None
    if self_requested:
        if mentioned or context.app_user_id not in users:
            return None
        responsavel_id = context.app_user_id
    elif len(mentioned) == 1:
        responsavel_id = mentioned[0]
    else:
        return None
    code = _consolidation_code(item.work_queue_item_id)
    if code is None:
        return None
    return CatalogTarget(
        'atribuir_consolidacao',
        MappingProxyType({
            'consolidacao_id': str(item.consolidacao_id),
            'responsavel_id': str(responsavel_id),
            'assignment_revision': item.assignment_revision,
        }),
        f'Atribuir consolidação da pendência {code} ao responsável indicado',
    )


def _decision_targets_for_requested_text(
    session: Session,
    context: object,
    *,
    requested_text: object,
) -> tuple[CatalogTarget, ...]:
    """Resolve existing decision candidates server-side from the anchored text."""

    tenant = getattr(context, 'igreja_id', None)
    if (
        type(requested_text) is not str
        or type(tenant) is not uuid.UUID
        or not action_allowed(context, 'registrar_decisao')
    ):
        return ()
    roster = session.execute(
        select(Pessoa.id, Pessoa.nome).where(
            Pessoa.igreja_id == tenant,
            Pessoa.arquivada_em.is_(None),
        )
    ).all()
    person_names = Counter(_label_key(name) for _, name in roster)
    requested_ids = [
        person_id
        for person_id, name in roster
        if person_names[_label_key(name)] == 1 and _mentioned_name(requested_text, name)
    ]
    if not requested_ids:
        return ()
    cell_names = Counter(
        _label_key(name)
        for name in session.execute(
            select(Celula.nome).where(Celula.igreja_id == tenant, Celula.ativo.is_(True))
        ).scalars()
    )
    people = session.execute(
        select(Pessoa)
        .where(
            Pessoa.igreja_id == tenant,
            Pessoa.id.in_(requested_ids),
            Pessoa.arquivada_em.is_(None),
        )
        .order_by(Pessoa.nome, Pessoa.id)
        .limit(8)
    ).scalars().all()
    targets: list[CatalogTarget] = []
    for person in people:
        if not _label_key(person.nome) or person_names[_label_key(person.nome)] != 1:
            continue
        name = _label(person.nome)
        targets.append(CatalogTarget('registrar_decisao', MappingProxyType({
            'pessoa_id': str(person.id), 'vinculo': 'visitante', 'celula_id': None,
        }), f'Registrar decisão de {name}, vínculo visitante'))
        cell = session.execute(
            select(Celula)
            .join(
                CelulaMembro,
                (CelulaMembro.celula_id == Celula.id)
                & (CelulaMembro.igreja_id == Celula.igreja_id),
            )
            .where(
                Celula.igreja_id == tenant,
                Celula.ativo.is_(True),
                CelulaMembro.pessoa_id == person.id,
                CelulaMembro.ativo.is_(True),
            )
            .limit(1)
        ).scalar_one_or_none()
        if cell is not None and cell_names[_label_key(cell.nome)] == 1:
            targets.append(CatalogTarget('registrar_decisao', MappingProxyType({
                'pessoa_id': str(person.id), 'vinculo': 'celula', 'celula_id': str(cell.id),
            }), f'Registrar decisão de {name}, vínculo célula {_label(cell.nome)}'))
    return tuple(targets[:16])


def _consolidation_decision_target(
    session: Session,
    context: object,
    *,
    requested_text: object,
) -> CatalogTarget | None:
    """Admit one exact V3 decision command without exposing its person label."""

    command = _normalized_consolidation_text(requested_text).strip(' .!?')
    match = _CONSOLIDATION_DECISION_COMMAND.fullmatch(command)
    if match is None:
        return None
    candidates = _decision_targets_for_requested_text(
        session,
        context,
        requested_text=requested_text,
    )
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    try:
        pessoa_id = uuid.UUID(candidate.arguments['pessoa_id'])
    except (KeyError, TypeError, ValueError):
        return None
    name = session.execute(
        select(Pessoa.nome).where(
            Pessoa.igreja_id == getattr(context, 'igreja_id', None),
            Pessoa.id == pessoa_id,
            Pessoa.arquivada_em.is_(None),
        )
    ).scalar_one_or_none()
    if _label_key(match.group('target')) != _label_key(name):
        return None
    return CatalogTarget(
        'registrar_decisao',
        MappingProxyType(dict(candidate.arguments)),
        'Registrar decisão da pessoa indicada',
    )


def _current_consolidation_message_text(session: Session, context: object) -> str | None:
    from app.services.whatsapp_privilege import PrivilegeContext

    if type(context) is not PrivilegeContext:
        return None
    try:
        text = session.execute(
            select(Message.texto)
            .join(
                Conversation,
                and_(
                    Conversation.igreja_id == Message.igreja_id,
                    Conversation.id == Message.conversation_id,
                ),
            )
            .where(
                Message.igreja_id == context.igreja_id,
                Message.conversation_id == context.conversation_id,
                Message.id == context.inbound_message_id,
                Message.direcao == 'in',
                Conversation.pessoa_id == context.pessoa_id,
            )
        ).scalar_one_or_none()
    except (TypeError, ValueError, AttributeError):
        return None
    return text if type(text) is str else None


def _consolidation_pending_items(session: Session, context: object):
    """Reuse the same current queue projection as the read-only V3 reply."""

    from app.services.consolidation_privileged import _pending_item, _pending_statement
    from app.services.whatsapp_privilege import PrivilegeContext

    if type(context) is not PrivilegeContext:
        return ()
    try:
        coordinator = consolidation_coordination_allowed(context.roles)
        responsible_types = consolidation_responsible_task_types(context.roles)
        if not coordinator and not responsible_types:
            return ()
        require_tenant_scope(
            session,
            expected_igreja_id=context.igreja_id,
            source='agent_privilege_catalog.consolidation_pending',
        )
        rows = session.execute(
            _pending_statement(
                context.igreja_id,
                responsavel_id=None if coordinator else context.app_user_id,
                task_types=None if coordinator else responsible_types,
            )
        ).all()
    except (TenantScopeError, TypeError, ValueError, AttributeError):
        return ()
    items = []
    for row in rows:
        try:
            work_item, consolidacao = row
        except (TypeError, ValueError):
            return ()
        item = _pending_item(work_item, consolidacao, igreja_id=context.igreja_id)
        if item is None:
            return ()
        if not coordinator and (
            item.responsavel_id != context.app_user_id
            or item.task_type not in responsible_types
        ):
            continue
        items.append(item)
    return tuple(items)


def _consolidation_fonovisita_targets(
    session: Session,
    context: object,
    *,
    requested_text: object | None = None,
) -> tuple[CatalogTarget, ...]:
    from app.services.whatsapp_privilege import PrivilegeContext

    if (
        type(context) is not PrivilegeContext
        or not consolidation_enabled_from_environment(context.igreja_id)
        or not action_allowed(context, 'marcar_fonovisita_feita')
    ):
        return ()
    text = requested_text if requested_text is not None else _current_consolidation_message_text(session, context)
    target = _fonovisita_target_from_items(
        context,
        _consolidation_pending_items(session, context),
        requested_text=text,
    )
    return (target,) if target is not None else ()


def _consolidation_assignment_targets(
    session: Session,
    context: object,
    *,
    requested_text: object | None = None,
) -> tuple[CatalogTarget, ...]:
    from app.services.whatsapp_privilege import PrivilegeContext

    if (
        type(context) is not PrivilegeContext
        or not consolidation_enabled_from_environment(context.igreja_id)
        or not action_allowed(context, 'atribuir_consolidacao')
    ):
        return ()
    text = requested_text if requested_text is not None else _current_consolidation_message_text(session, context)
    target = _assignment_target_from_items(
        context,
        _consolidation_pending_items(session, context),
        requested_text=text,
        eligible_users=_eligible_consolidation_users(session, context),
    )
    return (target,) if target is not None else ()


def _assignment_command_target_is_resolved(
    session: Session,
    context: object,
    command: str,
) -> bool:
    """Accept one closed assignment command only after server target resolution."""

    match = _CONSOLIDATION_ASSIGNMENT_COMMAND.fullmatch(command)
    if match is None:
        return False
    target = ' '.join(match.group('target').split())
    users = _eligible_consolidation_users(session, context)
    if target == 'mim':
        return getattr(context, 'app_user_id', None) in users
    target_key = _label_key(target)
    if not target_key:
        return False
    matches = tuple(
        app_user_id
        for app_user_id, name in users.items()
        if _label_key(name) == target_key
    )
    return len(matches) == 1


def _unsafe_consolidation_projection() -> ConsolidationRoutingProjection:
    return ConsolidationRoutingProjection(
        text='Solicitação de consolidação encaminhada para atendimento humano.',
        required_codes=(),
        handoff_only=True,
    )


def consolidation_routing_projection(
    session: Session,
    context: object,
) -> ConsolidationRoutingProjection | None:
    """Project a recognized V3 request without forwarding inbound free text."""

    from app.services.whatsapp_privilege import PrivilegeContext

    if (
        type(context) is not PrivilegeContext
        or not consolidation_enabled_from_environment(context.igreja_id)
    ):
        return None
    normalized = _normalized_consolidation_text(
        _current_consolidation_message_text(session, context)
    )
    if not normalized:
        return None
    command = normalized.strip(' .!?')
    reminder = _consolidation_reminder_requested(command)
    assignment = _ASSIGNMENT_REQUEST.search(normalized) is not None
    decision = _DECISION_REQUEST.search(normalized) is not None
    fonovisita = _FONOVISITA_REQUEST.search(normalized) is not None
    query = _CONSOLIDATION_QUERY_REQUEST.search(normalized) is not None
    if not (reminder or assignment or decision or fonovisita or query):
        return None
    if not consolidation_responsible_allowed(context.roles):
        return _unsafe_consolidation_projection()

    mutations = sum((reminder, assignment, decision, fonovisita))
    if mutations > 1:
        return _unsafe_consolidation_projection()
    if reminder:
        intents = ('ativação de lembretes de consolidação',)
        required = ('configurar_lembrete_consolidacao',)
        safe = command in _CONSOLIDATION_REMINDER_REQUESTS
    elif assignment:
        intents = ('atribuição de consolidação',)
        required = ('atribuir_consolidacao',)
        safe = _assignment_command_target_is_resolved(session, context, command)
    elif decision:
        intents = ('registro de decisão',)
        required = ('registrar_decisao',)
        safe = _consolidation_decision_target(
            session,
            context,
            requested_text=command,
        ) is not None
    elif fonovisita:
        intents = ('confirmação de fonovisita',)
        required = ('marcar_fonovisita_feita',)
        safe = _CONSOLIDATION_FONOVISITA_COMMAND.fullmatch(command) is not None
    else:
        intents = ('consulta de pendências de consolidação',)
        required = ()
        safe = command in _CONSOLIDATION_QUERY_COMMANDS
    if not safe:
        return _unsafe_consolidation_projection()

    text = 'Solicitação de ' + '; '.join(intents) + '.'
    codes = tuple(dict.fromkeys(code.upper() for code in _CONSOLIDATION_CODE.findall(normalized)))
    if len(codes) > 1:
        return _unsafe_consolidation_projection()
    if codes:
        text += f' Códigos opacos informados: {", ".join(codes)}.'
    return ConsolidationRoutingProjection(
        text=text,
        required_codes=required,
    )


def fonovisita_arguments_authorized(
    session: Session,
    *,
    context: object,
    target: object,
    arguments: object,
    summary: object | None = None,
) -> bool:
    from app.services.agent_action_proposals import (
        AgentAction,
        ProposalContractError,
        ProposalTarget,
        canonical_action_arguments,
    )
    from app.services.whatsapp_privilege import PrivilegeContext

    if type(context) is not PrivilegeContext or type(target) is not ProposalTarget or type(arguments) is not dict:
        return False
    try:
        canonical = canonical_action_arguments(AgentAction.MARCAR_FONOVISITA_FEITA, target, arguments)
    except ProposalContractError:
        return False
    for candidate in _consolidation_fonovisita_targets(session, context):
        if (
            target.kind == 'pendencia_consolidacao'
            and target.id == uuid.UUID(candidate.arguments['work_queue_item_id'])
            and canonical == dict(candidate.arguments)
            and (summary is None or summary == f'{candidate.summary}{_CONFIRMATION_SUFFIX}')
        ):
            return True
    return False


def assignment_arguments_authorized(
    session: Session,
    *,
    context: object,
    target: object,
    arguments: object,
    summary: object | None = None,
) -> bool:
    from app.services.agent_action_proposals import (
        AgentAction,
        ProposalContractError,
        ProposalTarget,
        canonical_action_arguments,
    )
    from app.services.whatsapp_privilege import PrivilegeContext

    if type(context) is not PrivilegeContext or type(target) is not ProposalTarget or type(arguments) is not dict:
        return False
    try:
        canonical = canonical_action_arguments(AgentAction.ATRIBUIR_CONSOLIDACAO, target, arguments)
    except ProposalContractError:
        return False
    for candidate in _consolidation_assignment_targets(session, context):
        if (
            target.kind == 'consolidacao'
            and target.id == uuid.UUID(candidate.arguments['consolidacao_id'])
            and canonical == dict(candidate.arguments)
            and (summary is None or summary == f'{candidate.summary}{_CONFIRMATION_SUFFIX}')
        ):
            return True
    return False


def execute_catalog_action(session: Session, context, code: str, arguments: Mapping[str, Any]) -> str:
    from app.services.whatsapp_privilege import PrivilegeContext
    if (
        type(context) is not PrivilegeContext
        or code not in ACTIONS
        or (code not in {'marcar_presenca', 'registrar_expectativa_visitante'} and not action_allowed(context, code))
    ):
        raise HTTPException(403, 'Ação não autorizada')
    args = validated_action_arguments(code, arguments)
    if code == 'registrar_expectativa_visitante':
        if any(type(value) is not uuid.UUID or value.int == 0 for value in (
            context.igreja_id, context.app_user_id, context.pessoa_id)):
            raise HTTPException(403, 'Ação não autorizada')
        row = register_own_visitor_expectation(session, _user(context),
            reuniao_id=uuid.UUID(args['reuniao_id']), nome_visitante=args['nome_visitante'],
            observacao_oracao=None, expected_actor_pessoa_id=context.pessoa_id)
        return str(row.id)
    person_id = uuid.UUID(args['pessoa_id'])
    if code == 'marcar_presenca':
        if person_id != context.pessoa_id:
            # Deny member-to-third-person calls before even looking up a person.
            if not action_allowed(context, code):
                raise HTTPException(403, 'Ação não autorizada')
        else:
            actor = session.execute(select(AppUser.pessoa_id).where(
                AppUser.id == context.app_user_id, AppUser.igreja_id == context.igreja_id,
            ).with_for_update()).scalar_one_or_none()
            if actor is None or actor != person_id:
                raise HTTPException(403, 'Vínculo do usuário alterado')
            meeting = session.execute(select(CelulaReuniao).where(
                CelulaReuniao.id == uuid.UUID(args['reuniao_id']),
                CelulaReuniao.igreja_id == context.igreja_id,
            ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
            if meeting is None:
                raise HTTPException(404, 'Reunião não encontrada')
            cell = session.execute(select(Celula).where(
                Celula.id == meeting.celula_id, Celula.igreja_id == context.igreja_id,
                Celula.ativo.is_(True),
            ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
            if cell is None:
                raise HTTPException(403, 'Célula sem vínculo elegível')
            if cell_meetings_schedule.meeting_has_passed(data=meeting.data, hora=meeting.hora):
                raise HTTPException(409, 'A reunião já ocorreu; não é possível confirmar presença')
    person = session.execute(select(Pessoa).where(Pessoa.id == person_id,
        Pessoa.igreja_id == context.igreja_id, Pessoa.arquivada_em.is_(None))).scalar_one_or_none()
    if person is None:
        raise HTTPException(404, 'Pessoa não encontrada')
    if code == 'registrar_decisao':
        row = register_decision(session, _user(context), pessoa_id=person_id,
            vinculo=args['vinculo'], origem='whatsapp',
            celula_id=uuid.UUID(args['celula_id']) if args['celula_id'] else None)
    elif person_id == context.pessoa_id:
        row = confirm_meeting_attendance(session, _user(context),
            reuniao_id=uuid.UUID(args['reuniao_id']), pessoa_id=None,
            expected_actor_pessoa_id=context.pessoa_id)
    else:
        row = confirm_meeting_attendance(session, _user(context),
            reuniao_id=uuid.UUID(args['reuniao_id']), pessoa_id=person_id)
    return str(row.id)


def _consolidation_catalog_groups(
    session: Session,
    context: object,
    *,
    requested_text: object,
) -> dict[str, list[CatalogTarget]]:
    from app.services.whatsapp_privilege import PrivilegeContext

    if (
        type(context) is not PrivilegeContext
        or not consolidation_enabled_from_environment(context.igreja_id)
        or not consolidation_responsible_allowed(context.roles)
    ):
        return {}
    grouped: dict[str, list[CatalogTarget]] = {}
    reminder = _consolidation_reminder_target(context, requested_text=requested_text)
    if reminder is not None:
        grouped['configurar_lembrete_consolidacao'] = [reminder]
    if action_allowed(context, 'registrar_decisao'):
        decision = _consolidation_decision_target(
            session,
            context,
            requested_text=requested_text,
        )
        if decision is not None:
            grouped['registrar_decisao'] = [decision]
    if action_allowed(context, 'consultar_pendencias_consolidacao'):
        grouped['consultar_pendencias_consolidacao'] = [CatalogTarget(
            'consultar_pendencias_consolidacao',
            MappingProxyType({}),
            'Consultar pendências de consolidação autorizadas',
        )]
    if action_allowed(context, 'marcar_fonovisita_feita'):
        targets = _consolidation_fonovisita_targets(
            session,
            context,
            requested_text=requested_text,
        )
        if targets:
            grouped['marcar_fonovisita_feita'] = list(targets)
    if action_allowed(context, 'atribuir_consolidacao'):
        targets = _consolidation_assignment_targets(
            session,
            context,
            requested_text=requested_text,
        )
        if targets:
            grouped['atribuir_consolidacao'] = list(targets)
    return grouped


_CATALOG_DESCRIPTIONS = {
    'registrar_expectativa_visitante': 'Indicar visitante próprio para a próxima reunião, após confirmação explícita',
    'registrar_decisao': 'Registrar decisão de fé de uma pessoa, após confirmação explícita',
    'marcar_presenca': 'Confirmar presença própria ou de terceiro autorizado em reunião de célula, após confirmação explícita',
    'consultar_vinculo': 'Consultar meu próprio vínculo cadastrado, com confirmação no painel',
    'consultar_celulas': 'Consultar dados das células autorizadas, com confirmação no painel',
    'consultar_agenda': 'Consultar agenda autorizada da igreja sem dados de pessoas',
    'configurar_lembrete_agenda': 'Ativar lembretes da Agenda para uma ocorrência, após confirmação explícita',
    'configurar_lembrete_consolidacao': (
        'Ativar lembretes das próprias pendências de consolidação, após confirmação explícita'
    ),
    'consultar_pendencias_consolidacao': (
        'Consultar pendências de consolidação autorizadas sem dados pessoais'
    ),
    'marcar_fonovisita_feita': (
        'Confirmar fonovisita pendente, após confirmação explícita'
    ),
    'atribuir_consolidacao': (
        'Atribuir uma consolidação a responsável elegível, após confirmação explícita'
    ),
}


def _catalog_from_groups(grouped: Mapping[str, list[CatalogTarget]]):
    from app.services.agent_privilege_routing import CandidateOption, ToolOption
    from app.services.semantic_routing import RouteChoice

    catalog = []
    mapping = {}
    for code, targets in grouped.items():
        summaries = Counter(' '.join(unicodedata.normalize('NFKD', target.summary).casefold().split())
                            for target in targets)
        targets = [target for target in targets if summaries[
            ' '.join(unicodedata.normalize('NFKD', target.summary).casefold().split())] == 1]
        if not targets:
            continue
        if code in {'consultar_agenda', 'consultar_pendencias_consolidacao'}:
            target = targets[0]
            if (
                len(targets) != 1
                or target.code != code
                or dict(target.arguments)
            ):
                continue
            catalog.append(ToolOption(code, RouteChoice.RESTRITA, _CATALOG_DESCRIPTIONS[code], ()))
            mapping[(code, None)] = target
            continue
        options = []
        for n, target in enumerate(targets, start=1):
            handle = f'h{n}'
            options.append(CandidateOption(handle, target.summary))
            mapping[(code, handle)] = target
        catalog.append(ToolOption(code, RouteChoice.RESTRITA, _CATALOG_DESCRIPTIONS[code], tuple(options)))
    return tuple(catalog), MappingProxyType(mapping)


def build_consolidation_catalog(session: Session, context: object):
    """Build only V3 options, never a general person or cell roster."""

    from app.services.whatsapp_privilege import PrivilegeContext

    if type(context) is not PrivilegeContext:
        return (), MappingProxyType({})
    requested_text = _current_consolidation_message_text(session, context)
    if requested_text is None:
        return (), MappingProxyType({})
    return _catalog_from_groups(
        _consolidation_catalog_groups(
            session,
            context,
            requested_text=requested_text,
        )
    )


def build_catalog(session: Session, context):
    """Bounded authorized candidates. Every selected handle is revalidated later.

    Operational actions expose only the name needed to select their target;
    phone numbers, addresses, pastoral text and financial data are never projected.
    """
    tenant = context.igreja_id
    grouped: dict[str, list[CatalogTarget]] = {}
    # Detect collisions before candidate limits: a homonym outside the first
    # page is still ambiguous. Only these server-side counts see other names.
    requested_text = session.execute(select(Message.texto).where(
        Message.igreja_id == tenant, Message.conversation_id == context.conversation_id,
        Message.id == context.inbound_message_id, Message.direcao == 'in',
    )).scalar_one_or_none() or ''
    visitor_attempt, _ = own_visitor_command(requested_text)
    if visitor_attempt:
        return _catalog_from_groups({'registrar_expectativa_visitante': list(
            _own_visitor_targets(session, context, requested_text=requested_text),
        )})
    own_request = _own_presence_requested(requested_text)
    if own_request:
        grouped['marcar_presenca'] = list(_own_presence_targets(
            session, context, requested_text=requested_text,
        ))
    roster = session.execute(select(Pessoa.id, Pessoa.nome).where(
        Pessoa.igreja_id == tenant, Pessoa.arquivada_em.is_(None))).all() if any(
            action_allowed(context, action) for action in _PERSON_ACTIONS) and not own_request else []
    person_names = Counter(_label_key(name) for _, name in roster)
    # Only a name explicitly present in this anchored request can enter a D
    # prompt. Unrelated roster entries and history never become model input.
    requested_ids = [person_id for person_id, name in roster
        if person_names[_label_key(name)] == 1 and _mentioned_name(requested_text, name)]
    cell_names = Counter(_label_key(name) for name in session.execute(
        select(Celula.nome).where(Celula.igreja_id == tenant,
            Celula.ativo.is_(True))).scalars()) if requested_ids else Counter()
    decision_targets = () if own_request else _decision_targets_for_requested_text(
        session,
        context,
        requested_text=requested_text,
    )
    if decision_targets:
        grouped['registrar_decisao'] = list(decision_targets)
    if requested_ids and action_allowed(context, 'marcar_presenca'):
        query = select(Celula).where(Celula.igreja_id == tenant, Celula.ativo.is_(True))
        # A superset is filtered by the same hierarchy rule used by the panel.
        cells = session.execute(query.order_by(Celula.id).limit(64)).scalars().all()
        targets = []
        for cell in cells:
            if (cell_names[_label_key(cell.nome)] != 1
                or not can_mark_for_other(session, _user(context), cell)):
                continue
            meeting_dates = Counter(session.execute(select(CelulaReuniao.data).where(
                CelulaReuniao.igreja_id == tenant, CelulaReuniao.celula_id == cell.id,
                CelulaReuniao.data >= dt.date.today() - dt.timedelta(days=14),
                CelulaReuniao.data <= dt.date.today() + dt.timedelta(days=14),
            )).scalars())
            meetings = session.execute(select(CelulaReuniao).where(
                CelulaReuniao.igreja_id == tenant, CelulaReuniao.celula_id == cell.id,
                CelulaReuniao.data >= dt.date.today() - dt.timedelta(days=14),
                CelulaReuniao.data <= dt.date.today() + dt.timedelta(days=14),
            ).order_by(CelulaReuniao.data, CelulaReuniao.id).limit(4)).scalars().all()
            members = session.execute(select(Pessoa).join(CelulaMembro,
                (CelulaMembro.pessoa_id == Pessoa.id) & (CelulaMembro.igreja_id == Pessoa.igreja_id))
                .where(Pessoa.igreja_id == tenant, Pessoa.arquivada_em.is_(None),
                    Pessoa.id.in_(requested_ids),
                    Pessoa.id != context.pessoa_id, CelulaMembro.celula_id == cell.id,
                    CelulaMembro.ativo.is_(True)).order_by(Pessoa.nome, Pessoa.id).limit(16)).scalars().all()
            for meeting in meetings:
                if meeting_dates[meeting.data] != 1:
                    continue
                for person in members:
                    if person_names[_label_key(person.nome)] != 1:
                        continue
                    targets.append(CatalogTarget('marcar_presenca', MappingProxyType({
                        'pessoa_id': str(person.id), 'reuniao_id': str(meeting.id),
                    }), f'Confirmar presença de {_label(person.nome)} em {_label(cell.nome)}, {meeting.data.isoformat()}'))
                    if len(targets) == 16:
                        break
                if len(targets) == 16:
                    break
            if len(targets) == 16:
                break
        grouped['marcar_presenca'] = targets
    # Confirmation of the panel session is requested before any sensitive read.
    grouped['consultar_vinculo'] = [CatalogTarget('consultar_vinculo', MappingProxyType({}), 'Consultar meu próprio vínculo cadastrado', True)]
    if context.roles & MINISTERIAL_ROLES:
        grouped['consultar_celulas'] = [CatalogTarget('consultar_celulas', MappingProxyType({}), 'Consultar células sob minha responsabilidade', True)]
    if agenda_enabled_from_environment(tenant) and agenda_read_allowed(context):
        grouped['consultar_agenda'] = [CatalogTarget(
            'consultar_agenda',
            MappingProxyType({}),
            'Consultar agenda autorizada da igreja',
        )]
        if _agenda_reminder_requested(requested_text):
            reminders = _agenda_reminder_targets(
                session,
                context,
                requested_text=requested_text,
            )
            if reminders:
                grouped['configurar_lembrete_agenda'] = list(reminders)
    grouped.update(
        _consolidation_catalog_groups(
            session,
            context,
            requested_text=requested_text,
        )
    )
    return _catalog_from_groups(grouped)


def read_sensitive_catalog(session: Session, context, code: str) -> str:
    from app.services.whatsapp_privilege import PrivilegeContext
    if type(context) is not PrivilegeContext or not context.sensitive or context.proof_id is None:
        raise HTTPException(403, 'Confirme o acesso no painel')
    if code == 'consultar_vinculo':
        person = session.execute(select(Pessoa).where(Pessoa.id == context.pessoa_id,
            Pessoa.igreja_id == context.igreja_id, Pessoa.arquivada_em.is_(None))).scalar_one_or_none()
        if person is None:
            raise HTTPException(404, 'Vínculo indisponível')
        return f'Seu vínculo cadastrado é: {_label(person.tipo)}.'
    if code == 'consultar_celulas' and context.roles & MINISTERIAL_ROLES:
        query = select(Celula).where(Celula.igreja_id == context.igreja_id, Celula.ativo.is_(True))
        if not context.roles & {'admin','pastor'}:
            query = query.where(Celula.id.in_(context.owned_cell_ids))
        cells = session.execute(query.order_by(Celula.nome, Celula.id).limit(10)).scalars().all()
        if not cells:
            return 'Não há célula ativa sob sua responsabilidade cadastrada.'
        return 'Células autorizadas: ' + '; '.join(_label(cell.nome) for cell in cells) + '.'
    raise HTTPException(403, 'Consulta não autorizada')
