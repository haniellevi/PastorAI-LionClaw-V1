"""Closed UV commands and inert production release fence."""
import uuid


def test_disabled_before_dependencies(monkeypatch):
    from app.uv_whatsapp import policy
    from app.uv_whatsapp.turn import run_uv_turn
    tenant = uuid.uuid4()
    monkeypatch.setenv('UV_WHATSAPP_ENABLED_IGREJA_IDS', str(tenant))
    assert not policy.enabled(tenant)
    def forbidden(*a, **kw):
        raise AssertionError('disabled dependency touched')
    assert run_uv_turn(forbidden, forbidden, object(), igreja_id=tenant,
        uses_dedicated_agent_session=False, ownership_guard=forbidden,
        evolution_client=forbidden) is None


def test_closed_router():
    from app.agent.nodes import route_uv_intent
    assert route_uv_intent('UV') == ('list', None)
    assert route_uv_intent('UV turma Esperança') == ('read', 'Esperança')
    assert route_uv_intent('SIM') == ('none', None)
    assert route_uv_intent('SIM', pending=True) == ('confirm', None)
    assert route_uv_intent('sim!', pending=True) == ('clarify', None)
    assert route_uv_intent('Quero oração', pending=True) == ('none', None)
    assert route_uv_intent('UV concluir Ana')[0] == 'help'
    assert route_uv_intent('UV presença Esperança; aula 1; Ana; presente') == (
        'attendance', ('esperanca', 1, 'ana', True, 'regular'))
    assert route_uv_intent('UV presença Esperança; aula 1; Ana; reposição')[1][-2:] == (True, 'reposicao')
    assert route_uv_intent('UV presença Esperança; Encontro; Ana; presente')[0] == 'help'

def test_disabled_church_before_dependencies(monkeypatch):
    from app.uv_whatsapp import policy
    from app.uv_whatsapp.turn import run_uv_turn
    monkeypatch.setattr(policy,'UV_WHATSAPP_APPROVED_RELEASE_ID','synthetic-only')
    monkeypatch.setenv('UV_WHATSAPP_ENABLED_IGREJA_IDS',str(uuid.uuid4()))
    def forbidden(*a,**kw): raise AssertionError('disabled touched dependency')
    assert run_uv_turn(forbidden,forbidden,object(),igreja_id=uuid.uuid4(),
        uses_dedicated_agent_session=False,ownership_guard=forbidden,evolution_client=forbidden) is None


def test_release_alone_and_invalid_allowlist_stay_disabled(monkeypatch):
    from app.uv_whatsapp import policy
    tenant=uuid.uuid4()
    monkeypatch.setattr(policy,'UV_WHATSAPP_APPROVED_RELEASE_ID','synthetic-only')
    for raw in ['', 'invalid', f'{tenant},{tenant}', f'{tenant},invalid']:
        monkeypatch.setenv('UV_WHATSAPP_ENABLED_IGREJA_IDS',raw)
        assert not policy.enabled(tenant)
    monkeypatch.setenv('UV_WHATSAPP_ENABLED_IGREJA_IDS',str(tenant))
    assert policy.enabled(tenant)
    assert not policy.enabled(str(tenant))
