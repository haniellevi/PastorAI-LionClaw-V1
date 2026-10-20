"""Closed ENVIAR commands and inert production release fence."""
import uuid


def test_disabled_before_dependencies(monkeypatch):
    from app.enviar_whatsapp import policy
    from app.enviar_whatsapp.turn import run_enviar_turn
    tenant = uuid.uuid4()
    monkeypatch.setenv('ENVIAR_WHATSAPP_ENABLED_IGREJA_IDS', str(tenant))
    assert not policy.enabled(tenant)
    def forbidden(*a, **kw):
        raise AssertionError('disabled dependency touched')
    assert run_enviar_turn(forbidden, forbidden, object(), igreja_id=tenant,
        uses_dedicated_agent_session=False, ownership_guard=forbidden,
        evolution_client=forbidden) is None


def test_disabled_church_before_dependencies(monkeypatch):
    from app.enviar_whatsapp import policy
    from app.enviar_whatsapp.turn import run_enviar_turn
    monkeypatch.setattr(policy,'ENVIAR_WHATSAPP_APPROVED_RELEASE_ID','synthetic-only')
    monkeypatch.setenv('ENVIAR_WHATSAPP_ENABLED_IGREJA_IDS',str(uuid.uuid4()))
    def forbidden(*a,**kw): raise AssertionError('disabled touched dependency')
    assert run_enviar_turn(forbidden,forbidden,object(),igreja_id=uuid.uuid4(),
        uses_dedicated_agent_session=False,ownership_guard=forbidden,evolution_client=forbidden) is None


def test_release_alone_and_invalid_allowlist_stay_disabled(monkeypatch):
    from app.enviar_whatsapp import policy
    tenant=uuid.uuid4()
    monkeypatch.setattr(policy,'ENVIAR_WHATSAPP_APPROVED_RELEASE_ID','synthetic-only')
    for raw in ['', 'invalid', f'{tenant},{tenant}', f'{tenant},invalid']:
        monkeypatch.setenv('ENVIAR_WHATSAPP_ENABLED_IGREJA_IDS',raw)
        assert not policy.enabled(tenant)
    monkeypatch.setenv('ENVIAR_WHATSAPP_ENABLED_IGREJA_IDS',str(tenant))
    assert policy.enabled(tenant)
    assert not policy.enabled(str(tenant))


def test_closed_router():
    from app.agent.nodes import route_enviar_intent as route
    assert route('ENVIAR') == ('list',None)
    assert route('ENVIAR pessoa Ána') == ('read','ana')
    assert route('SIM') == ('none',None)
    assert route('SIM',pending=True) == ('confirm',None)
    assert route('ENVIAR nomear Esperança; Ana') == ('nominate',('esperanca','ana'))
    for text in ['ENVIAR aprovar','ENVIAR avaliar apto','ENVIAR validar Reencontro']:
        assert route(text)[0]=='help'


def test_unrelated_enviar_uses_normal_flow():
    from app.agent.nodes import route_enviar_intent as route
    for body in ['Enviar foto da célula', 'enviar mensagem', 'enviar pessoas', 'enviar abertura']:
        assert route(body) == ('none', None)
    for body in ['ENVIAR nomear', 'ENVIAR abrir', 'ENVIAR pessoa', 'ENVIAR solicitações extra']:
        assert route(body) == ('help', None)
