"""Pending protocols must leave other closed commands to their real routers."""
import pytest
from app.agent import nodes
from app.services.private_resume import RESUME_COMMAND
from app.services.private_erasure_requests import COMMAND as ERASURE_COMMAND
from app.services.whatsapp_agenda import parse_agenda_query

PENDING_ROUTERS = [nodes.route_cd_intent, nodes.route_uv_intent,
                   nodes.route_enviar_intent, nodes.route_prayer_intent,
                   nodes.route_cell_suggest_intent]
COMMANDS = [
    ('CD', nodes.route_cd_intent, ('list', None)),
    ('UV', nodes.route_uv_intent, ('list', None)),
    ('ENVIAR', nodes.route_enviar_intent, ('list', None)),
    ('quero iniciar pedido de oração', nodes.route_prayer_intent, 'start'),
    ('CONHECIMENTO buscar culto', nodes.route_conhecimento_intent, ('search', 'culto')),
    (ERASURE_COMMAND, nodes.route_private_erasure_intent, True),
    ('agenda', parse_agenda_query, parse_agenda_query('agenda')),
]


def action(result):
    return result[0] if isinstance(result, tuple) else result


@pytest.mark.parametrize('pending_router,text,target,expected', [
    (pending_router, text, target, expected)
    for pending_router in PENDING_ROUTERS
    for text, target, expected in COMMANDS
    if pending_router is not target
])
def test_other_closed_commands_pass_pending_protocol(pending_router, text, target, expected):
    assert action(pending_router(text, pending=True)) == 'none'
    assert target(text) == expected


@pytest.mark.parametrize('pending_router', PENDING_ROUTERS)
def test_private_resume_passes_pending_protocol(pending_router):
    assert action(pending_router(RESUME_COMMAND, pending=True)) == 'none'
    if pending_router is nodes.route_prayer_intent:
        from app.prayer.catalog import classify

        assert classify(RESUME_COMMAND, pending=True) == 'none'


@pytest.mark.parametrize('router', PENDING_ROUTERS[:4])
@pytest.mark.parametrize('text,expected', [('SIM', 'confirm'), (' sim ', 'confirm'),
                                         ('sim!', 'clarify'), ('confirmo', 'clarify')])
def test_confirmation_stays_with_pending_protocol(router, text, expected):
    assert action(router(text, pending=True)) == expected
    assert action(router(text, pending=False)) == 'none'


@pytest.mark.parametrize('router', PENDING_ROUTERS[:4])
@pytest.mark.parametrize('text', ['texto livre', 'talvez', 'sim, pode fazer', ''])
def test_pending_proposal_does_not_capture_arbitrary_text(router, text):
    assert action(router(text, pending=True)) == 'none'


def test_cell_suggestion_leaves_confirmo_to_pending_confirmation():
    assert nodes.route_cell_suggest_intent('confirmo', pending=True) == ('none', None)


@pytest.mark.parametrize('text', [
    'talvez com todos', 'com todos', 'só meu líder',
    'pastores ou meu líder', 'somente a equipe pastoral',
])
def test_invalid_prayer_audience_stays_with_real_catalog_and_router(text):
    from app.prayer.catalog import classify

    assert classify(text, pending=True) == 'clarify'
    assert nodes.route_prayer_intent(text, pending=True) == 'clarify'
    assert classify(text, pending=False) == 'none'
    assert nodes.route_prayer_intent(text, pending=False) == 'none'


@pytest.mark.parametrize('text,target,expected', [
    command for command in COMMANDS if command[1] is not nodes.route_prayer_intent
] + [
    ('CONHECIMENTO buscar pastores', nodes.route_conhecimento_intent,
     ('search', 'pastores')),
])
def test_pending_prayer_catalog_leaves_other_commands_to_real_router(text, target, expected):
    from app.prayer.catalog import classify

    assert classify(text, pending=True) == 'none'
    assert nodes.route_prayer_intent(text, pending=True) == 'none'
    assert target(text) == expected
