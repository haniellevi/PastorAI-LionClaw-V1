import datetime as dt
from types import MappingProxyType, SimpleNamespace
from uuid import UUID
import pytest
from app.services.agent_action_proposals import ProposalTarget
from app.services.agent_privilege_catalog import action_allowed, validated_action_arguments
from app.services.whatsapp_agenda import AgendaOccurrence
from app.services.whatsapp_privilege import PrivilegeContext


def ctx(*roles):
    return SimpleNamespace(roles=frozenset(roles))


@pytest.mark.parametrize('role', ['membro', 'operador', 'lider_celula'])
def test_decision_role_does_not_expand_human_permission(role):
    assert not action_allowed(ctx(role), 'registrar_decisao')


@pytest.mark.parametrize('code', ['vincular_celula','avancar_trilha','financeiro','__import__'])
def test_catalog_stays_closed_to_approved_mutating_actions(code):
    assert not action_allowed(ctx('admin'), code)


@pytest.mark.parametrize('role', ['membro', 'operador', 'lider_celula', 'pastor', 'admin'])
def test_agenda_reminder_uses_only_roles_that_can_read_the_agenda(role):
    assert action_allowed(ctx(role), 'configurar_lembrete_agenda')


def test_agenda_reminder_does_not_expand_an_unrelated_role():
    assert not action_allowed(ctx('financeiro'), 'configurar_lembrete_agenda')


def test_presenca_uses_meeting_and_person_never_counter():
    args = {'pessoa_id': str(UUID(int=1)), 'reuniao_id': str(UUID(int=2))}
    assert validated_action_arguments('marcar_presenca', args) == args
    with pytest.raises(ValueError):
        validated_action_arguments('marcar_presenca', dict(args, quantidade=100))


def test_agenda_reminder_is_not_a_legacy_catalog_adapter_action():
    with pytest.raises(ValueError):
        validated_action_arguments(
            'configurar_lembrete_agenda',
            {
                'event_id': str(UUID(int=3)),
                'occurrence_at': '2026-10-02T13:00:00.000000+00:00',
                'term_version': 'lgpd-v2',
            },
        )


def test_decision_cannot_receive_forged_actor_or_tenant():
    args = {'pessoa_id': str(UUID(int=1)), 'vinculo': 'visitante', 'celula_id': None}
    assert validated_action_arguments('registrar_decisao', args) == args
    for key in ['igreja_id','actor_id','papel','origem']:
        with pytest.raises(ValueError):
            validated_action_arguments('registrar_decisao', dict(args, **{key: 'injetado'}))


_TENANT = UUID('00000000-0000-0000-0000-0000000000a1')
_CONVERSATION = UUID('00000000-0000-0000-0000-0000000000c1')
_INBOUND = UUID('00000000-0000-0000-0000-0000000000d1')
_EVENT = UUID('00000000-0000-0000-0000-0000000000e5')
_PERSON = UUID('00000000-0000-0000-0000-0000000000f1')
_USER = UUID('00000000-0000-0000-0000-0000000000b1')
_NOW = dt.datetime(2026, 9, 27, 12, tzinfo=dt.timezone.utc)


def _reminder_context(*roles: str) -> PrivilegeContext:
    return PrivilegeContext(
        igreja_id=_TENANT,
        conversation_id=_CONVERSATION,
        inbound_message_id=_INBOUND,
        pessoa_id=_PERSON,
        app_user_id=_USER,
        roles=frozenset(roles),
        role_snapshot=(),
        owned_cell_ids=(),
        credential_fingerprint='1' * 64,
        phone_fingerprint='2' * 64,
        authorization_fingerprint='3' * 64,
        proof_id=None,
        proof_until=None,
        sensitive=False,
        scope_fingerprint='4' * 64,
        context_fingerprint='5' * 64,
    )


def test_agenda_reminder_requires_explicit_intent_and_a_single_occurrence():
    import app.services.agent_privilege_catalog as catalog

    first = AgendaOccurrence(_EVENT, dt.date(2026, 10, 2), '10:00', 'Culto')
    second = AgendaOccurrence(
        UUID('00000000-0000-0000-0000-0000000000e6'),
        dt.date(2026, 10, 3),
        '10:00',
        'Culto',
    )

    assert catalog._agenda_reminder_targets_from_occurrences(
        (first,), requested_text='Quais eventos temos na agenda?', term_version='lgpd-v2', now=_NOW,
    ) == ()
    assert catalog._agenda_reminder_targets_from_occurrences(
        (first, second), requested_text='Quero um lembrete da agenda.',
        term_version='lgpd-v2', now=_NOW,
    ) == ()

    for requested_text in ('Me lembre do culto em 02/10/2026.', 'Me avise do culto em 02/10/2026.'):
        targets = catalog._agenda_reminder_targets_from_occurrences(
            (first, second),
            requested_text=requested_text,
            term_version='lgpd-v2',
            now=_NOW,
        )
        assert len(targets) == 1
        assert targets[0].arguments['event_id'] == str(_EVENT)

    targets = catalog._agenda_reminder_targets_from_occurrences(
        (first, second),
        requested_text='Quero um lembrete do culto em 02/10/2026.',
        term_version='lgpd-v2',
        now=_NOW,
    )

    assert len(targets) == 1
    target = targets[0]
    assert target.code == 'configurar_lembrete_agenda'
    assert dict(target.arguments) == {
        'event_id': str(_EVENT),
        'occurrence_at': '2026-10-02T13:00:00.000000+00:00',
        'term_version': 'lgpd-v2',
    }
    assert 'Ativar lembretes da Agenda' in target.summary
    assert str(_EVENT) not in target.summary
    assert 'telefone' not in target.summary.casefold()


def test_agenda_reminder_rejects_fabricated_arguments_and_unauthorized_context(monkeypatch):
    import app.services.agent_privilege_catalog as catalog

    args = {
        'event_id': str(_EVENT),
        'occurrence_at': '2026-10-02T13:00:00.000000+00:00',
        'term_version': 'lgpd-v2',
    }
    target = catalog.CatalogTarget(
        'configurar_lembrete_agenda', MappingProxyType(args),
        'Ativar lembretes da Agenda para Culto em 02/10/2026 às 10:00',
    )
    monkeypatch.setattr(catalog, 'agenda_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(catalog, '_agenda_reminder_targets', lambda *_args, **_kwargs: (target,))

    context = _reminder_context('membro')
    proposal_target = ProposalTarget(kind='evento', id=_EVENT)
    assert catalog.agenda_reminder_arguments_authorized(
        SimpleNamespace(), context=context, target=proposal_target, arguments=args,
    )
    assert catalog.agenda_reminder_arguments_authorized(
        SimpleNamespace(), context=context, target=proposal_target, arguments=args,
        summary=(
            'Ativar lembretes da Agenda para Culto em 02/10/2026 às 10:00. '
            'Confirma esta ação? Responda SIM ou NÃO. A proposta vale por 10 minutos.'
        ),
    )
    assert not catalog.agenda_reminder_arguments_authorized(
        SimpleNamespace(), context=context, target=proposal_target, arguments=args,
        summary='Resumo forjado.',
    )
    assert not catalog.agenda_reminder_arguments_authorized(
        SimpleNamespace(), context=context, target=proposal_target,
        arguments=dict(args, term_version='lgpd-v3'),
    )
    assert not catalog.agenda_reminder_arguments_authorized(
        SimpleNamespace(), context=context,
        target=ProposalTarget(kind='evento', id=UUID('00000000-0000-0000-0000-0000000000e6')),
        arguments=args,
    )

    unauthorized = _reminder_context('financeiro')
    monkeypatch.setattr(
        catalog, '_agenda_reminder_targets',
        lambda *_args, **_kwargs: pytest.fail('papel sem agenda não pode consultar alvo'),
    )
    assert not catalog.agenda_reminder_arguments_authorized(
        SimpleNamespace(), context=unauthorized, target=proposal_target, arguments=args,
    )


def test_build_catalog_adds_a_reminder_handle_only_for_a_server_target(monkeypatch):
    import app.services.agent_privilege_catalog as catalog

    target = catalog.CatalogTarget(
        'configurar_lembrete_agenda',
        MappingProxyType({
            'event_id': str(_EVENT),
            'occurrence_at': '2026-10-02T13:00:00.000000+00:00',
            'term_version': 'lgpd-v2',
        }),
        'Ativar lembretes da Agenda para Culto em 02/10/2026 às 10:00',
    )

    class _Result:
        def scalar_one_or_none(self):
            return 'Quero um lembrete do culto.'

    class _Session:
        def execute(self, _statement):
            return _Result()

    monkeypatch.setattr(catalog, 'agenda_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(catalog, '_agenda_reminder_targets', lambda *_args, **_kwargs: (target,))
    catalog_options, targets = catalog.build_catalog(_Session(), _reminder_context('membro'))

    reminder = next(option for option in catalog_options if option.code == 'configurar_lembrete_agenda')
    assert reminder.candidates[0].handle == 'h1'
    assert str(_EVENT) not in reminder.candidates[0].summary
    assert targets[('configurar_lembrete_agenda', 'h1')] == target


def test_build_catalog_keeps_a_plain_agenda_query_out_of_the_reminder_path(monkeypatch):
    import app.services.agent_privilege_catalog as catalog

    class _Result:
        def scalar_one_or_none(self):
            return 'Quais eventos temos na agenda?'

    class _Session:
        def execute(self, _statement):
            return _Result()

    monkeypatch.setattr(catalog, 'agenda_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(
        catalog,
        '_agenda_reminder_targets',
        lambda *_args, **_kwargs: pytest.fail('consulta simples não pode carregar alvos de lembrete'),
    )
    catalog_options, targets = catalog.build_catalog(_Session(), _reminder_context('membro'))

    assert any(option.code == 'consultar_agenda' for option in catalog_options)
    assert ('configurar_lembrete_agenda', 'h1') not in targets
