"""Closed agenda grammar: only a delivered proposal can accept literal SIM."""
import pytest
from app.agent.nodes import route_agenda_intent
from app.agenda_whatsapp import catalog
from app.services import whatsapp_agenda
from uuid import uuid4


@pytest.mark.parametrize('answer', ['SIM!', 'SIM.', 'confirmo', 'SIM por favor', 'ＳＩＭ'])
def test_only_literal_sim_confirms(answer):
    assert route_agenda_intent(answer, pending=True)[0] == 'clarify'


def test_closed_commands_and_typed_payload():
    assert route_agenda_intent('AGENDA')[0] == 'list'
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


def test_existing_agenda_queries_keep_their_original_route():
    assert route_agenda_intent('agenda próximos 7 dias página 2')[0] == 'none'
    assert route_agenda_intent('agenda rascunhos')[0] == 'none'
