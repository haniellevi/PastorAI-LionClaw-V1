"""Closed agenda grammar: only a delivered proposal can accept literal SIM."""
import pytest
from app.agent.nodes import route_agenda_intent
from app.agenda_whatsapp import catalog
from app.services import whatsapp_agenda
from uuid import uuid4


@pytest.mark.parametrize('answer', ['SIM!', 'SIM.', 'confirmo', 'ＳＩＭ'])
def test_only_literal_sim_confirms(answer):
    assert route_agenda_intent(answer, pending=True)[0] == 'clarify'


def test_closed_commands_and_typed_payload():
    assert route_agenda_intent('AGENDA')[0] == 'none'
    assert route_agenda_intent('AGENDA consultar')[0] == 'list'
    command, args = route_agenda_intent('AGENDA criar Culto; 2026-12-01; 19:00')
    assert command == 'create'
    tool = catalog.EventTool(action=command, payload=dict(titulo=args[0], data=args[1], hora=args[2]))
    assert tool.payload.data.isoformat() == '2026-12-01'
    assert route_agenda_intent('SIM')[0] == 'none'
    assert route_agenda_intent('SIM', pending=True)[0] == 'confirm'
    assert route_agenda_intent('NÃO', pending=True)[0] == 'cancel'
    assert route_agenda_intent('AGENDA importar Google')[0] == 'help'
    assert route_agenda_intent('quero enviar uma foto')[0] == 'none'


@pytest.mark.parametrize('date,hour', [('invalid', '19:00'), ('2026-12-01', '25:00')])
def test_invalid_schedule_rejected(date, hour):
    with pytest.raises(ValueError):
        catalog.EventTool(action='create', payload=dict(titulo='Culto', data=date, hora=hour))


def test_release_remains_inert_with_allowlist_only(monkeypatch):
    tenant = uuid4()
    monkeypatch.setenv('AGENDA_WHATSAPP_ENABLED_IGREJA_IDS', str(tenant))
    assert whatsapp_agenda.AGENDA_WHATSAPP_APPROVED_RELEASE_ID is None
    assert not whatsapp_agenda.agenda_enabled_from_environment(tenant)


@pytest.mark.parametrize('pending', [False, True])
def test_existing_agenda_queries_keep_their_original_route(pending):
    assert route_agenda_intent('agenda próximos 7 dias página 2', pending=pending)[0] == 'none'
    assert route_agenda_intent('agenda rascunhos', pending=pending)[0] == 'none'


@pytest.mark.parametrize('fence', ['release', 'church'])
def test_read_gate_does_not_enable_writes(monkeypatch, fence):
    from app.agenda_whatsapp import policy
    from app.services import whatsapp_privilege
    tenant = uuid4()
    monkeypatch.setattr(whatsapp_privilege, 'PRIVILEGE_APPROVED_RELEASE_ID', 'synthetic')
    monkeypatch.setenv('AGENT_PRIVILEGE_ENABLED_IGREJA_IDS', str(tenant))
    monkeypatch.setattr(whatsapp_agenda, 'AGENDA_WHATSAPP_APPROVED_RELEASE_ID', 'synthetic')
    monkeypatch.setenv('AGENDA_WHATSAPP_ENABLED_IGREJA_IDS', str(tenant))
    assert whatsapp_agenda.agenda_enabled_from_environment(tenant)
    assert not policy.enabled(tenant)
    monkeypatch.setattr(policy, 'AGENDA_WRITE_WHATSAPP_APPROVED_RELEASE_ID', 'synthetic')
    monkeypatch.setenv('AGENDA_WRITE_WHATSAPP_ENABLED_IGREJA_IDS', str(tenant))
    assert policy.enabled(tenant)
    monkeypatch.setattr(whatsapp_agenda, 'AGENDA_WHATSAPP_APPROVED_RELEASE_ID', None)
    monkeypatch.setenv('AGENDA_WHATSAPP_ENABLED_IGREJA_IDS', '')
    assert policy.enabled(tenant)
    if fence == 'release':
        monkeypatch.setattr(policy, 'AGENDA_WRITE_WHATSAPP_APPROVED_RELEASE_ID', None)
    else:
        monkeypatch.setenv('AGENDA_WRITE_WHATSAPP_ENABLED_IGREJA_IDS', '')
    assert not policy.enabled(tenant)


@pytest.mark.parametrize('body', ['ENVIAR', 'CD', 'UV', 'quero iniciar pedido de oração',
    'retomar conversa', 'QUERO SOLICITAR EXCLUSAO DO MEU CONTEUDO PRIVADO', 'SIM por favor'])
def test_pending_does_not_capture_other_commands(body):
    assert route_agenda_intent(body, pending=True)[0] == 'none'
