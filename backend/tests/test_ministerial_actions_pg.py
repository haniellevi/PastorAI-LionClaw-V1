"""PG17 proof that a domain collision preserves an outer confirmation unit."""
import pytest
from tests.conftest_rls import rls_database_url
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.db.models import Pessoa, Decision
from app.services.ministerial_actions import register_decision
from tests.test_consolidacao_open_unique_concurrency import (
    engine_fx, _factory, _seed_church, _consol_user,
    _IGREJA_A, _PESSOA_A, _PESSOA_A2, _APPUSER_A,
)

pytestmark = pytest.mark.rls_integration


def test_decision_collision_preserves_outer_confirmation_transaction(engine_fx):
    factory = _factory(engine_fx)
    _seed_church(factory, igreja_id=_IGREJA_A, pessoa_id=_PESSOA_A,
                 app_user_id=_APPUSER_A, extra_pessoas=(_PESSOA_A2,))
    user = _consol_user(_IGREJA_A, _APPUSER_A)
    with factory() as session:
        register_decision(session, user, pessoa_id=_PESSOA_A, vinculo='visitante')
        session.commit()
    with factory() as session:
        outer = session.get(Pessoa, _PESSOA_A2)
        outer.nome = 'Synthetic outer transaction survived'
        with pytest.raises(IntegrityError) as exc:
            register_decision(session, user, pessoa_id=_PESSOA_A, vinculo='visitante')
        assert exc.value.orig.pgcode == '23505'
        # No rollback of the enclosing confirmation, and no second domain effect.
        assert session.is_active
        session.commit()
    with factory() as session:
        assert session.get(Pessoa, _PESSOA_A2).nome == 'Synthetic outer transaction survived'
        assert len(session.execute(select(Decision).where(Decision.pessoa_id == _PESSOA_A)).scalars().all()) == 1
