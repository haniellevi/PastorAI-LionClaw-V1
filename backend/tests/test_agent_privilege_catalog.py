from types import SimpleNamespace
from uuid import UUID
import pytest
from app.services.agent_privilege_catalog import action_allowed, validated_action_arguments


def ctx(*roles):
    return SimpleNamespace(roles=frozenset(roles))


@pytest.mark.parametrize('role', ['membro', 'operador', 'lider_celula'])
def test_decision_role_does_not_expand_human_permission(role):
    assert not action_allowed(ctx(role), 'registrar_decisao')


@pytest.mark.parametrize('code', ['vincular_celula','avancar_trilha','financeiro','__import__'])
def test_catalog_has_exactly_two_mutating_actions(code):
    assert not action_allowed(ctx('admin'), code)


def test_presenca_uses_meeting_and_person_never_counter():
    args = {'pessoa_id': str(UUID(int=1)), 'reuniao_id': str(UUID(int=2))}
    assert validated_action_arguments('marcar_presenca', args) == args
    with pytest.raises(ValueError):
        validated_action_arguments('marcar_presenca', dict(args, quantidade=100))


def test_decision_cannot_receive_forged_actor_or_tenant():
    args = {'pessoa_id': str(UUID(int=1)), 'vinculo': 'visitante', 'celula_id': None}
    assert validated_action_arguments('registrar_decisao', args) == args
    for key in ['igreja_id','actor_id','papel','origem']:
        with pytest.raises(ValueError):
            validated_action_arguments('registrar_decisao', dict(args, **{key: 'injetado'}))
