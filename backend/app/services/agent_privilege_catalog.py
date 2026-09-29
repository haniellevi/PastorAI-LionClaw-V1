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
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Celula, CelulaMembro, CelulaReuniao, Message, Pessoa
from app.db.rls_observability import require_tenant_scope
from app.db.tenant_session import TenantScopeError
from app.deps import CurrentUser
from app.domain.agent_authz import MINISTERIAL_ROLES, CONSOLIDATION_TOOL_ROLES
from app.domain.consolidation import VALID_VINCULOS
from app.services.ministerial_actions import (
    can_mark_for_other, confirm_meeting_attendance, register_decision,
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

ACTIONS = frozenset({'registrar_decisao', 'marcar_presenca'})
PROPOSAL_ACTIONS = ACTIONS | frozenset({'configurar_lembrete_agenda'})
_PERSON_ACTIONS = ACTIONS
_REMINDER_REQUEST = re.compile(
    r'\b(?:lembrete(?:s)?|lembre[- ]?me|avise[- ]?me|me[ -](?:lembre|avise))\b'
)
_SAFE_HOUR = re.compile(r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
_TERM_CHARS = frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:/-')
_CONFIRMATION_SUFFIX = '. Confirma esta ação? Responda SIM ou NÃO. A proposta vale por 10 minutos.'


@dataclass(frozen=True)
class CatalogTarget:
    code: str
    arguments: Mapping[str, Any]
    summary: str
    sensitive: bool = False


def action_allowed(context, code: str) -> bool:
    if code == 'registrar_decisao':
        return bool(context.roles & CONSOLIDATION_TOOL_ROLES)
    if code == 'marcar_presenca':
        return bool(context.roles & MINISTERIAL_ROLES)
    if code == 'configurar_lembrete_agenda':
        return agenda_read_allowed(context)
    return False


def validated_action_arguments(code: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
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


def execute_catalog_action(session: Session, context, code: str, arguments: Mapping[str, Any]) -> str:
    from app.services.whatsapp_privilege import PrivilegeContext
    if (
        type(context) is not PrivilegeContext
        or code not in ACTIONS
        or not action_allowed(context, code)
    ):
        raise HTTPException(403, 'Ação não autorizada')
    args = validated_action_arguments(code, arguments)
    person_id = uuid.UUID(args['pessoa_id'])
    person = session.execute(select(Pessoa).where(Pessoa.id == person_id,
        Pessoa.igreja_id == context.igreja_id, Pessoa.arquivada_em.is_(None))).scalar_one_or_none()
    if person is None:
        raise HTTPException(404, 'Pessoa não encontrada')
    if code == 'registrar_decisao':
        row = register_decision(session, _user(context), pessoa_id=person_id,
            vinculo=args['vinculo'], origem='whatsapp',
            celula_id=uuid.UUID(args['celula_id']) if args['celula_id'] else None)
    else:
        if person_id == context.pessoa_id:
            raise HTTPException(403, 'Esta ação confirma presença de terceiro')
        row = confirm_meeting_attendance(session, _user(context),
            reuniao_id=uuid.UUID(args['reuniao_id']), pessoa_id=person_id)
    return str(row.id)


def build_catalog(session: Session, context):
    """Bounded authorized candidates. Every selected handle is revalidated later.

    Operational actions expose only the name needed to select their target;
    phone numbers, addresses, pastoral text and financial data are never projected.
    """
    from app.services.agent_privilege_routing import CandidateOption, ToolOption
    from app.services.semantic_routing import RouteChoice

    tenant = context.igreja_id
    grouped: dict[str, list[CatalogTarget]] = {}
    # Detect collisions before candidate limits: a homonym outside the first
    # page is still ambiguous. Only these server-side counts see other names.
    requested_text = session.execute(select(Message.texto).where(
        Message.igreja_id == tenant, Message.conversation_id == context.conversation_id,
        Message.id == context.inbound_message_id, Message.direcao == 'in',
    )).scalar_one_or_none() or ''
    roster = session.execute(select(Pessoa.id, Pessoa.nome).where(
        Pessoa.igreja_id == tenant, Pessoa.arquivada_em.is_(None))).all() if any(
            action_allowed(context, action) for action in _PERSON_ACTIONS) else []
    person_names = Counter(_label_key(name) for _, name in roster)
    # Only a name explicitly present in this anchored request can enter a D
    # prompt. Unrelated roster entries and history never become model input.
    requested_ids = [person_id for person_id, name in roster
        if person_names[_label_key(name)] == 1 and _mentioned_name(requested_text, name)]
    cell_names = Counter(_label_key(name) for name in session.execute(
        select(Celula.nome).where(Celula.igreja_id == tenant,
            Celula.ativo.is_(True))).scalars()) if requested_ids else Counter()
    if requested_ids and action_allowed(context, 'registrar_decisao'):
        people = session.execute(select(Pessoa).where(Pessoa.igreja_id == tenant,
            Pessoa.id.in_(requested_ids),
            Pessoa.arquivada_em.is_(None)).order_by(Pessoa.nome, Pessoa.id).limit(8)).scalars().all()
        targets = []
        for person in people:
            if not _label_key(person.nome) or person_names[_label_key(person.nome)] != 1:
                continue
            name = _label(person.nome)
            targets.append(CatalogTarget('registrar_decisao', MappingProxyType({
                'pessoa_id': str(person.id), 'vinculo': 'visitante', 'celula_id': None,
            }), f'Registrar decisão de {name}, vínculo visitante'))
            cell = session.execute(select(Celula).join(CelulaMembro,
                (CelulaMembro.celula_id == Celula.id) & (CelulaMembro.igreja_id == Celula.igreja_id))
                .where(Celula.igreja_id == tenant, Celula.ativo.is_(True),
                    CelulaMembro.pessoa_id == person.id, CelulaMembro.ativo.is_(True))
                .limit(1)).scalar_one_or_none()
            if cell is not None and cell_names[_label_key(cell.nome)] == 1:
                targets.append(CatalogTarget('registrar_decisao', MappingProxyType({
                    'pessoa_id': str(person.id), 'vinculo': 'celula', 'celula_id': str(cell.id),
                }), f'Registrar decisão de {name}, vínculo célula {_label(cell.nome)}'))
        grouped['registrar_decisao'] = targets[:16]
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
    descriptions = {
        'registrar_decisao': 'Registrar decisão de fé de uma pessoa, após confirmação explícita',
        'marcar_presenca': 'Confirmar presença prevista de terceiro em reunião de célula, após confirmação explícita',
        'consultar_vinculo': 'Consultar meu próprio vínculo cadastrado, com confirmação no painel',
        'consultar_celulas': 'Consultar dados das células autorizadas, com confirmação no painel',
        'consultar_agenda': 'Consultar agenda autorizada da igreja sem dados de pessoas',
        'configurar_lembrete_agenda': 'Ativar lembretes da Agenda para uma ocorrência, após confirmação explícita',
    }
    catalog = []
    mapping = {}
    for code, targets in grouped.items():
        summaries = Counter(' '.join(unicodedata.normalize('NFKD', target.summary).casefold().split())
                            for target in targets)
        targets = [target for target in targets if summaries[
            ' '.join(unicodedata.normalize('NFKD', target.summary).casefold().split())] == 1]
        if not targets:
            continue
        if code == 'consultar_agenda':
            target = targets[0]
            if (
                len(targets) != 1
                or target.code != code
                or dict(target.arguments)
            ):
                continue
            catalog.append(ToolOption(code, RouteChoice.RESTRITA, descriptions[code], ()))
            mapping[(code, None)] = target
            continue
        options = []
        for n, target in enumerate(targets, start=1):
            handle = f'h{n}'
            options.append(CandidateOption(handle, target.summary))
            mapping[(code, handle)] = target
        catalog.append(ToolOption(code, RouteChoice.RESTRITA, descriptions[code], tuple(options)))
    return tuple(catalog), MappingProxyType(mapping)


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
