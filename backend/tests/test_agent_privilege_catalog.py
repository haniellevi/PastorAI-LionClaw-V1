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


def test_consolidation_reminder_optin_is_self_targeted_and_requires_explicit_request(
    monkeypatch,
):
    import app.services.agent_privilege_catalog as catalog

    class _Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class _Session:
        def __init__(self, inbound_text):
            self.inbound_text = inbound_text

        def execute(self, _statement):
            return _Result(self.inbound_text)

    context = _reminder_context('lider_consol')
    monkeypatch.setattr(catalog, 'consolidation_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(catalog, '_current_term_version', lambda: 'lgpd-v2')

    assert catalog._consolidation_reminder_target(
        context, requested_text='Quero ativar lembretes de consolidação.'
    ) == catalog.CatalogTarget(
        'configurar_lembrete_consolidacao',
        MappingProxyType({'pessoa_id': str(_PERSON), 'term_version': 'lgpd-v2'}),
        'Ativar lembretes de pendências de consolidação',
    )
    assert catalog._consolidation_reminder_target(
        context, requested_text='Quais pendências de consolidação existem?'
    ) is None
    assert catalog._consolidation_reminder_target(
        _reminder_context('membro'),
        requested_text='Quero ativar lembretes de consolidação.',
    ) is None

    args = {'pessoa_id': str(_PERSON), 'term_version': 'lgpd-v2'}
    assert not catalog.consolidation_reminder_arguments_authorized(
        _Session('Quais pendências de consolidação existem?'),
        context=context,
        target=ProposalTarget(kind='pessoa', id=_PERSON),
        arguments=args,
    )
    assert catalog.consolidation_reminder_arguments_authorized(
        _Session('Quero ativar lembretes de consolidação.'),
        context=context,
        target=ProposalTarget(kind='pessoa', id=_PERSON),
        arguments=args,
        summary=(
            'Ativar lembretes de pendências de consolidação. Confirma esta ação? '
            'Responda SIM ou NÃO. A proposta vale por 10 minutos.'
        ),
    )
    assert not catalog.consolidation_reminder_arguments_authorized(
        _Session('Quero ativar lembretes de consolidação.'),
        context=context,
        target=ProposalTarget(kind='pessoa', id=UUID(int=99)),
        arguments=args,
    )


def test_build_catalog_exposes_consolidation_pending_query_without_a_handle(monkeypatch):
    import app.services.agent_privilege_catalog as catalog

    class _Result:
        def scalar_one_or_none(self):
            return 'Quais pendências de consolidação existem?'

        def all(self):
            return []

        def scalars(self):
            return self

    class _Session:
        def execute(self, _statement):
            return _Result()

    monkeypatch.setattr(catalog, 'consolidation_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(catalog, 'agenda_enabled_from_environment', lambda _tenant: False)
    monkeypatch.setattr(
        catalog,
        'action_allowed',
        lambda _context, code: code == 'consultar_pendencias_consolidacao',
    )

    options, targets = catalog.build_catalog(_Session(), _reminder_context('lider_consol'))

    pending = next(option for option in options if option.code == 'consultar_pendencias_consolidacao')
    assert pending.candidates == ()
    assert targets[('consultar_pendencias_consolidacao', None)].code == (
        'consultar_pendencias_consolidacao'
    )


def _pending_item(
    item_id: UUID,
    *,
    consolidacao_id: UUID,
    responsavel_id: UUID | None,
    task_type: str = 'fonovisita',
    revision: int = 0,
):
    from app.services.consolidation_privileged import PendingConsolidationItem

    return PendingConsolidationItem(
        work_queue_item_id=item_id,
        consolidacao_id=consolidacao_id,
        pessoa_id=UUID('00000000-0000-0000-0000-0000000000d1'),
        responsavel_id=responsavel_id,
        assignment_revision=revision,
        task_type=task_type,
        due_at=None if task_type == 'fonovisita' else _NOW,
    )


@pytest.mark.parametrize('role', ['lider_consol', 'pastor', 'lider_g12', 'lider_celula'])
def test_fonovisita_uses_the_existing_human_resolver_capability(role):
    assert action_allowed(ctx(role), 'marcar_fonovisita_feita')


@pytest.mark.parametrize('role', ['membro', 'financeiro'])
def test_fonovisita_does_not_expand_an_unrelated_role(role):
    assert not action_allowed(ctx(role), 'marcar_fonovisita_feita')


@pytest.mark.parametrize('role', ['lider_celula', 'lider_g12'])
def test_own_consolidation_query_and_optin_use_the_human_resolver_capability(role):
    assert action_allowed(ctx(role), 'consultar_pendencias_consolidacao')
    assert action_allowed(ctx(role), 'configurar_lembrete_consolidacao')


@pytest.mark.parametrize('role', ['lider_consol', 'pastor'])
def test_consolidation_assignment_remains_coordination_only(role):
    assert action_allowed(ctx(role), 'atribuir_consolidacao')


@pytest.mark.parametrize('role', ['lider_celula', 'lider_g12', 'financeiro'])
def test_consolidation_assignment_does_not_open_for_resolver_roles(role):
    assert not action_allowed(ctx(role), 'atribuir_consolidacao')


def test_fonovisita_target_is_current_responsible_only_and_uses_a_stable_opaque_code():
    import app.services.agent_privilege_catalog as catalog

    own_consolidacao = UUID('00000000-0000-0000-0000-0000000000c3')
    own_item = _pending_item(
        UUID('12345678-90ab-cdef-0000-000000000001'),
        consolidacao_id=own_consolidacao,
        responsavel_id=_USER,
        revision=4,
    )
    other_item = _pending_item(
        UUID('abcdef12-3456-7890-0000-000000000002'),
        consolidacao_id=UUID('00000000-0000-0000-0000-0000000000c4'),
        responsavel_id=UUID('00000000-0000-0000-0000-0000000000b2'),
    )

    target = catalog._fonovisita_target_from_items(
        _reminder_context('lider_consol'),
        (own_item, other_item),
        requested_text='Marcar fonovisita feita P-1234567890.',
    )

    assert target is not None
    assert target.code == 'marcar_fonovisita_feita'
    assert dict(target.arguments) == {
        'work_queue_item_id': str(own_item.work_queue_item_id),
        'consolidacao_id': str(own_consolidacao),
        'assignment_revision': 4,
    }
    assert target.summary == 'Confirmar fonovisita pendente P-1234567890'
    assert str(own_item.work_queue_item_id) not in target.summary
    assert catalog._fonovisita_target_from_items(
        _reminder_context('lider_consol'),
        (own_item, other_item),
        requested_text='Marcar fonovisita feita.',
    ) == target
    second_own = _pending_item(
        UUID('98765432-10ab-cdef-0000-000000000003'),
        consolidacao_id=UUID('00000000-0000-0000-0000-0000000000c5'),
        responsavel_id=_USER,
    )
    assert catalog._fonovisita_target_from_items(
        _reminder_context('lider_consol'),
        (own_item, second_own),
        requested_text='Marcar fonovisita feita.',
    ) is None


def test_assignment_target_requires_one_stable_pending_code_and_a_unique_eligible_user():
    import app.services.agent_privilege_catalog as catalog

    consolidacao_id = UUID('00000000-0000-0000-0000-0000000000c3')
    item = _pending_item(
        UUID('12345678-90ab-cdef-0000-000000000001'),
        consolidacao_id=consolidacao_id,
        responsavel_id=None,
        task_type='conectar_celula',
        revision=5,
    )
    third = UUID('00000000-0000-0000-0000-0000000000b2')
    users = {_USER: 'Ana Líder', third: 'Maria Silva'}

    target = catalog._assignment_target_from_items(
        _reminder_context('pastor'),
        (item,),
        requested_text='Atribuir P-1234567890 para Maria Silva.',
        eligible_users=users,
    )

    assert target is not None
    assert target.code == 'atribuir_consolidacao'
    assert dict(target.arguments) == {
        'consolidacao_id': str(consolidacao_id),
        'responsavel_id': str(third),
        'assignment_revision': 5,
    }
    assert target.summary == (
        'Atribuir consolidação da pendência P-1234567890 ao responsável indicado'
    )
    assert 'Maria' not in target.summary
    assert catalog._assignment_target_from_items(
        _reminder_context('pastor'),
        (item,),
        requested_text='Atribuir P-1234567890 para Maria Silva.',
        eligible_users={_USER: 'Ana Líder'},
    ) is None
    assert catalog._assignment_target_from_items(
        _reminder_context('pastor'),
        (item,),
        requested_text='Atribuir P-1234567890 para Ana Líder.',
        eligible_users={_USER: 'Ana Líder', third: 'Ana Líder'},
    ) is None


def test_assignment_target_allows_only_an_eligible_self_shortcut():
    import app.services.agent_privilege_catalog as catalog

    item = _pending_item(
        UUID('12345678-90ab-cdef-0000-000000000001'),
        consolidacao_id=UUID('00000000-0000-0000-0000-0000000000c3'),
        responsavel_id=None,
    )
    context = _reminder_context('lider_consol')

    target = catalog._assignment_target_from_items(
        context,
        (item,),
        requested_text='Atribuir P-1234567890 para mim.',
        eligible_users={_USER: 'Ana Líder'},
    )

    assert target is not None
    assert target.arguments['responsavel_id'] == str(_USER)
    assert catalog._assignment_target_from_items(
        context,
        (item,),
        requested_text='Atribuir P-1234567890 para mim.',
        eligible_users={},
    ) is None


def test_consolidation_router_projection_is_opaque_and_skips_the_person_roster(monkeypatch):
    import app.services.agent_privilege_catalog as catalog

    context = _reminder_context('pastor')
    assignment = catalog.CatalogTarget(
        'atribuir_consolidacao',
        MappingProxyType({
            'consolidacao_id': str(UUID('00000000-0000-0000-0000-0000000000c3')),
            'responsavel_id': str(_USER),
            'assignment_revision': 4,
        }),
        'Atribuir consolidação da pendência P-1234567890 ao responsável indicado',
    )

    class _Result:
        def scalar_one_or_none(self):
            return 'Atribuir P-1234567890 para Ma\u0301ria Łucía.'

    class _Session:
        def __init__(self):
            self.statements = []

        def execute(self, statement):
            self.statements.append(str(statement))
            return _Result()

    session = _Session()
    monkeypatch.setattr(catalog, 'consolidation_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(
        catalog,
        'action_allowed',
        lambda _context, code: code in {
            'consultar_pendencias_consolidacao',
            'atribuir_consolidacao',
        },
    )
    monkeypatch.setattr(catalog, '_consolidation_reminder_target', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(catalog, '_consolidation_fonovisita_targets', lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        catalog,
        '_eligible_consolidation_users',
        lambda *_args, **_kwargs: {_USER: 'Mária Łucía'},
    )
    monkeypatch.setattr(
        catalog,
        '_consolidation_assignment_targets',
        lambda *_args, **_kwargs: (assignment,),
    )

    projected = catalog.consolidation_routing_projection(session, context)
    options, targets = catalog.build_consolidation_catalog(session, context)

    assert projected is not None
    assert projected.text == (
        'Solicitação de atribuição de consolidação. '
        'Códigos opacos informados: P-1234567890.'
    )
    assert projected.required_codes == ('atribuir_consolidacao',)
    assert not projected.handoff_only
    assert {option.code for option in options} == {
        'consultar_pendencias_consolidacao',
        'atribuir_consolidacao',
    }
    assert targets[('atribuir_consolidacao', 'h1')] == assignment
    rendered = repr((projected, options, targets)).casefold()
    assert 'maria' not in rendered
    assert 'lucia' not in rendered
    assert not any(' from pessoas' in statement.casefold() for statement in session.statements)


@pytest.mark.parametrize(
    'inbound_text',
    (
        'Quais pendências de Maria Silva?',
        'Quais pendências de consolidação? hoje planejo desaparecer para sempre.',
    ),
)
def test_consolidation_router_marks_recognized_residual_as_handoff_without_exposing_it(
    monkeypatch,
    inbound_text,
):
    import app.services.agent_privilege_catalog as catalog

    class _Result:
        def scalar_one_or_none(self):
            return inbound_text

    class _Session:
        def execute(self, _statement):
            return _Result()

    monkeypatch.setattr(catalog, 'consolidation_enabled_from_environment', lambda _tenant: True)

    projected = catalog.consolidation_routing_projection(
        _Session(),
        _reminder_context('pastor'),
    )

    assert projected is not None
    assert projected.handoff_only
    assert projected.required_codes == ()
    assert inbound_text.casefold() not in projected.text.casefold()
    assert 'maria' not in projected.text.casefold()
    assert 'desaparecer' not in projected.text.casefold()


@pytest.mark.parametrize(
    'inbound_text',
    (
        'Confirmar fonovisita feita P-1234567890.',
        'Quais pendências de consolidação existem?',
        'Quais pendências de consolidação? hoje planejo desaparecer para sempre.',
    ),
)
def test_recognized_v3_request_without_responsible_capability_is_handoff(monkeypatch, inbound_text):
    import app.services.agent_privilege_catalog as catalog

    class _Result:
        def scalar_one_or_none(self):
            return inbound_text

    class _Session:
        def execute(self, _statement):
            return _Result()

    monkeypatch.setattr(catalog, 'consolidation_enabled_from_environment', lambda _tenant: True)

    projected = catalog.consolidation_routing_projection(
        _Session(),
        _reminder_context('membro'),
    )

    assert projected is not None
    assert projected.handoff_only
    assert projected.required_codes == ()
    assert inbound_text.casefold() not in projected.text.casefold()


def test_consolidation_router_keeps_only_a_uniquely_resolved_assignment_target(monkeypatch):
    import app.services.agent_privilege_catalog as catalog

    class _Result:
        def scalar_one_or_none(self):
            return 'Atribuir P-1234567890 para Mária Łucía.'

    class _Session:
        def execute(self, _statement):
            return _Result()

    monkeypatch.setattr(catalog, 'consolidation_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(
        catalog,
        '_eligible_consolidation_users',
        lambda *_args, **_kwargs: {_USER: 'Mária Łucía'},
    )

    projected = catalog.consolidation_routing_projection(
        _Session(),
        _reminder_context('pastor'),
    )

    assert projected is not None
    assert not projected.handoff_only
    assert projected.text == (
        'Solicitação de atribuição de consolidação. '
        'Códigos opacos informados: P-1234567890.'
    )
    assert projected.required_codes == ('atribuir_consolidacao',)


def test_build_catalog_exposes_only_server_revalidated_consolidation_mutations(monkeypatch):
    import app.services.agent_privilege_catalog as catalog

    fono = catalog.CatalogTarget(
        'marcar_fonovisita_feita',
        MappingProxyType({
            'work_queue_item_id': str(UUID('12345678-90ab-cdef-0000-000000000001')),
            'consolidacao_id': str(UUID('00000000-0000-0000-0000-0000000000c3')),
            'assignment_revision': 4,
        }),
        'Confirmar fonovisita pendente P-1234567890',
    )
    assignment = catalog.CatalogTarget(
        'atribuir_consolidacao',
        MappingProxyType({
            'consolidacao_id': str(UUID('00000000-0000-0000-0000-0000000000c3')),
            'responsavel_id': str(_USER),
            'assignment_revision': 4,
        }),
        'Atribuir consolidação da pendência P-1234567890 ao responsável indicado',
    )

    class _Result:
        def scalar_one_or_none(self):
            return 'Atribuir P-1234567890 para mim e confirmar fonovisita.'

    class _Session:
        def execute(self, _statement):
            return _Result()

    monkeypatch.setattr(catalog, 'consolidation_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(catalog, 'agenda_enabled_from_environment', lambda _tenant: False)
    monkeypatch.setattr(catalog, '_consolidation_reminder_target', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        catalog,
        'action_allowed',
        lambda _context, code: code in {'marcar_fonovisita_feita', 'atribuir_consolidacao'},
    )
    monkeypatch.setattr(catalog, '_consolidation_fonovisita_targets', lambda *_args, **_kwargs: (fono,))
    monkeypatch.setattr(catalog, '_consolidation_assignment_targets', lambda *_args, **_kwargs: (assignment,))

    options, targets = catalog.build_catalog(_Session(), _reminder_context('pastor'))

    mutation_options = {
        option.code
        for option in options
        if option.code in {'marcar_fonovisita_feita', 'atribuir_consolidacao'}
    }
    assert mutation_options == {'marcar_fonovisita_feita', 'atribuir_consolidacao'}
    assert targets[('marcar_fonovisita_feita', 'h1')] == fono
    assert targets[('atribuir_consolidacao', 'h1')] == assignment
    assert all('Maria' not in candidate.summary for option in options for candidate in option.candidates)


@pytest.mark.parametrize(
    ('authorizer', 'target_kind', 'target_id', 'arguments', 'summary'),
    (
        (
            'fonovisita_arguments_authorized',
            'pendencia_consolidacao',
            UUID('00000000-0000-0000-0000-0000000000e5'),
            {
                'work_queue_item_id': '00000000-0000-0000-0000-0000000000e5',
                'consolidacao_id': '00000000-0000-0000-0000-0000000000c3',
                'assignment_revision': 4,
            },
            'Confirmar fonovisita pendente P-0000000000',
        ),
        (
            'assignment_arguments_authorized',
            'consolidacao',
            UUID('00000000-0000-0000-0000-0000000000c3'),
            {
                'consolidacao_id': '00000000-0000-0000-0000-0000000000c3',
                'responsavel_id': str(_USER),
                'assignment_revision': 4,
            },
            'Atribuir consolidação da pendência P-0000000000 ao responsável indicado',
        ),
    ),
)
def test_consolidation_proposal_authorizer_requires_the_current_server_target(
    monkeypatch,
    authorizer,
    target_kind,
    target_id,
    arguments,
    summary,
):
    import app.services.agent_privilege_catalog as catalog

    code = (
        'marcar_fonovisita_feita'
        if authorizer == 'fonovisita_arguments_authorized'
        else 'atribuir_consolidacao'
    )
    candidate = catalog.CatalogTarget(code, MappingProxyType(arguments), summary)
    targets_name = (
        '_consolidation_fonovisita_targets'
        if authorizer == 'fonovisita_arguments_authorized'
        else '_consolidation_assignment_targets'
    )
    monkeypatch.setattr(catalog, targets_name, lambda *_args, **_kwargs: (candidate,))
    proposal_target = ProposalTarget(kind=target_kind, id=target_id)
    confirmed_summary = f'{summary}. Confirma esta ação? Responda SIM ou NÃO. A proposta vale por 10 minutos.'

    assert getattr(catalog, authorizer)(
        SimpleNamespace(),
        context=_reminder_context('pastor'),
        target=proposal_target,
        arguments=arguments,
        summary=confirmed_summary,
    )
    assert not getattr(catalog, authorizer)(
        SimpleNamespace(),
        context=_reminder_context('pastor'),
        target=proposal_target,
        arguments=dict(arguments, assignment_revision=5),
        summary=confirmed_summary,
    )
    assert not getattr(catalog, authorizer)(
        SimpleNamespace(),
        context=_reminder_context('pastor'),
        target=proposal_target,
        arguments=arguments,
        summary='Resumo adulterado.',
    )
