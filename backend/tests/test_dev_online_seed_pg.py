"""Synthetic DEV seed on active migrations in a disposable loopback database."""
import pytest
from tests.test_whatsapp_integrated_pg import migrated_factory, rls_database_url  # noqa: F401

pytestmark = pytest.mark.rls_integration


def test_synthetic_seed_is_idempotent_and_refuses_unknown_tenants(migrated_factory):
    from app.db.models import Igreja
    from scripts import dev_local
    from scripts.dev_online import _seed_synthetic
    from sqlalchemy import delete, select

    with migrated_factory.begin() as session:
        # Migration fixtures may contain the runner's historical demo tenant.
        # It is never silently relabelled as our seed or overwritten by it.
        if set(session.scalars(select(Igreja.id))):
            with pytest.raises(ValueError, match='complete synthetic dataset'):
                _seed_synthetic(session)
        session.execute(delete(Igreja))  # owned disposable fixture only
    with migrated_factory.begin() as session:
        assert _seed_synthetic(session) is True
        assert _seed_synthetic(session) is False
        assert set(session.scalars(select(Igreja.id))) == {dev_local.IGREJA_ID, dev_local.IGREJA_VIZINHA_ID}
        session.add(Igreja(nome='Outra igreja sintética'))
        session.flush()
        with pytest.raises(ValueError, match='complete synthetic dataset'):
            _seed_synthetic(session)
