from uuid import uuid4
import pytest
from pydantic import ValidationError


def test_release_closed_before_session_or_provider(monkeypatch):
    from app.conhecimento_whatsapp import policy
    from app.conhecimento_whatsapp.turn import run_conhecimento_turn
    t=uuid4(); monkeypatch.setenv('CONHECIMENTO_WHATSAPP_ENABLED_IGREJA_IDS',str(t))
    assert policy.CONHECIMENTO_WHATSAPP_APPROVED_RELEASE_ID is None
    def forbidden(): raise AssertionError('Gate fechado deve sair antes da sessão')
    assert run_conhecimento_turn(forbidden,forbidden,None,igreja_id=t,
        uses_dedicated_agent_session=False,ownership_guard=None,evolution_client=None) is None


def test_typed_catalog_and_real_router():
    from app.conhecimento_whatsapp.catalog import SearchTool
    from app.agent.nodes import route_conhecimento_intent
    assert route_conhecimento_intent('CONHECIMENTO buscar orientação')==('search','orientação')
    assert route_conhecimento_intent('não consulte conhecimento')==('none',None)
    with pytest.raises(ValidationError): SearchTool(consulta='x',igreja_id=str(uuid4()))
    with pytest.raises(ValidationError): SearchTool(consulta='\x00')


@pytest.mark.parametrize('allowlist',['','invalid','other','duplicate'])
def test_church_allowlist_denies_invalid_or_unapproved(monkeypatch,allowlist):
    from app.conhecimento_whatsapp import policy
    t=uuid4(); other=uuid4()
    monkeypatch.setattr(policy,'CONHECIMENTO_WHATSAPP_APPROVED_RELEASE_ID','synthetic')
    raw={'':'','invalid':'invalid','other':str(other),'duplicate':f'{t},{t}'}[allowlist]
    monkeypatch.setenv('CONHECIMENTO_WHATSAPP_ENABLED_IGREJA_IDS',raw)
    assert not policy.enabled(t)
