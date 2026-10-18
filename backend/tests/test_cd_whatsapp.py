"""Closed CD commands and inert production release fence."""
import uuid


def test_disabled_before_dependencies(monkeypatch):
    from app.cd_whatsapp import policy
    from app.cd_whatsapp.turn import run_cd_turn
    tenant = uuid.uuid4()
    monkeypatch.setenv('CD_WHATSAPP_ENABLED_IGREJA_IDS', str(tenant))
    assert not policy.enabled(tenant)
    def forbidden(*a, **kw):
        raise AssertionError('disabled dependency touched')
    assert run_cd_turn(forbidden, forbidden, object(), igreja_id=tenant,
        uses_dedicated_agent_session=False, ownership_guard=forbidden,
        evolution_client=forbidden) is None


def test_closed_router():
    from app.agent.nodes import route_cd_intent
    assert route_cd_intent('CD') == ('list', None)
    assert route_cd_intent('CD turma Esperança') == ('read', 'esperanca')
    assert route_cd_intent('SIM') == ('none', None)
    assert route_cd_intent('SIM', pending=True) == ('confirm', None)
    assert route_cd_intent('sim!', pending=True) == ('clarify', None)
    assert route_cd_intent('Quero oração', pending=True) == ('none', None)
    assert route_cd_intent('CD concluir Ana')[0] == 'help'
    assert route_cd_intent('CD presença Esperança; aula 1; Ana; presente') == (
        'attendance', ('esperanca', 1, 'ana', True, 'regular'))
    assert route_cd_intent('CD presença Esperança; aula 1; Ana; reposição')[1][-2:] == (True, 'reposicao')
    assert route_cd_intent('CD presença Esperança; certificado; Ana; presente')[0] == 'help'

def test_disabled_church_before_dependencies(monkeypatch):
    from app.cd_whatsapp import policy
    from app.cd_whatsapp.turn import run_cd_turn
    monkeypatch.setattr(policy,'CD_WHATSAPP_APPROVED_RELEASE_ID','synthetic-only')
    monkeypatch.setenv('CD_WHATSAPP_ENABLED_IGREJA_IDS',str(uuid.uuid4()))
    def forbidden(*a,**kw): raise AssertionError('disabled touched dependency')
    assert run_cd_turn(forbidden,forbidden,object(),igreja_id=uuid.uuid4(),
        uses_dedicated_agent_session=False,ownership_guard=forbidden,evolution_client=forbidden) is None


def test_release_alone_and_invalid_allowlist_stay_disabled(monkeypatch):
    from app.cd_whatsapp import policy
    tenant=uuid.uuid4()
    monkeypatch.setattr(policy,'CD_WHATSAPP_APPROVED_RELEASE_ID','synthetic-only')
    for raw in ['', 'invalid', f'{tenant},{tenant}', f'{tenant},invalid']:
        monkeypatch.setenv('CD_WHATSAPP_ENABLED_IGREJA_IDS',raw)
        assert not policy.enabled(tenant)
    monkeypatch.setenv('CD_WHATSAPP_ENABLED_IGREJA_IDS',str(tenant))
    assert policy.enabled(tenant)
    assert not policy.enabled(str(tenant))


def test_read_normalizes_spaces_and_accents():
    from app.agent.nodes import route_cd_intent
    assert route_cd_intent('  CD   túrma   Esperança  Viva ') == ('read', 'esperanca viva')


def test_saved_names_normalize_spaces_and_accents():
    from app.cd_whatsapp.service import choose
    item = dict(nome='  Ána   Clara  ')
    assert choose([item], 'ana clara') is item


def test_correction_refusal_uses_code(monkeypatch):
    from app.cd_whatsapp.catalog import execute
    from app.services.formation_errors import AttendanceChanged
    from app.services import cd
    from fastapi import HTTPException
    import pytest
    def changed(*a, **kw):
        raise AttendanceChanged(detail='Mensagem independente')
    monkeypatch.setattr(cd, 'attendance', changed)
    proposal = dict(id=str(uuid.uuid4()), turma_id=str(uuid.uuid4()),
        matricula_id=str(uuid.uuid4()), aula_id=str(uuid.uuid4()),
        presente=True, modalidade='regular', anterior_id=None)
    with pytest.raises(HTTPException, match='nova proposta'):
        execute(None, None, proposal)


def test_lesson_numbers_up_to_one_hundred():
    from app.cd_whatsapp.catalog import route
    for number in (1, 10, 11, 99, 100):
        assert route(f'CD presença Turma; aula {number}; Aluno; presente') == (
            'attendance', ('turma', number, 'aluno', True, 'regular'))
    for number in (0, 101, 1000):
        assert route(f'CD presença Turma; aula {number}; Aluno; presente')[0] == 'help'
