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


def test_migration_fixture_repairs_preexisting_service_role_without_bypass(rls_database_url):
    import psycopg2
    from sqlalchemy.engine import make_url

    url = make_url(rls_database_url).set(drivername="postgresql")
    if url.host not in {"127.0.0.1", "::1"} or url.database != "rls_disposable":
        raise ValueError("role regression requires disposable loopback Postgres")
    with psycopg2.connect(url.render_as_string(hide_password=False)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles "
                           "WHERE rolname='service_role') THEN "
                           "CREATE ROLE service_role NOLOGIN NOBYPASSRLS; "
                           "ELSE ALTER ROLE service_role NOBYPASSRLS; END IF; END $$")
    fixture = migrated_factory.__wrapped__(rls_database_url)
    try:
        factory = next(fixture)
        with factory.kw["bind"].connect() as connection:
            rows = dict(connection.exec_driver_sql(
                "SELECT rolname, rolbypassrls FROM pg_roles "
                "WHERE rolname IN ('anon', 'authenticated', 'service_role')"
            ).all())
        assert rows == {"anon": False, "authenticated": False, "service_role": True}
    finally:
        fixture.close()
