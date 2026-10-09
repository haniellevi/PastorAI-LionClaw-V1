"""F4 catalogue proof on the exact active migrations, never a live database."""
import importlib.util
from pathlib import Path

import pytest

from tests.test_whatsapp_integrated_pg import migrated_factory, rls_database_url  # noqa: F401
from scripts.migrate import migration_files

pytestmark = pytest.mark.rls_integration
_path = Path(__file__).resolve().parents[2] / 'deploy/schema_compatibility.py'
_spec = importlib.util.spec_from_file_location('release_schema_compatibility', _path)
_schema = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_schema)


def test_additive_catalogue_supports_previous_version_but_rejects_drift(migrated_factory):
    engine = migrated_factory.kw['bind']
    previous_names = migration_files()
    candidate_names = previous_names + ['20261009_190000_synthetic_additive.sql']
    with engine.connect() as connection:
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        previous = _schema.capture_catalog(connection)
        connection.rollback()
        # Rehearse a nominal additive migration and an actual backfill. All
        # source data and schema remain inside this disposable test database.
        with connection.begin():
            connection.exec_driver_sql("INSERT INTO public.igrejas (nome) VALUES ('Sintética para backfill')")
            connection.exec_driver_sql('ALTER TABLE public.igrejas ADD COLUMN synthetic_release_revision integer')
            connection.exec_driver_sql('UPDATE public.igrejas SET synthetic_release_revision=1')
            connection.exec_driver_sql('INSERT INTO public.schema_migrations (name) VALUES (%s)', (candidate_names[-1],))
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        candidate = _schema.capture_catalog(connection)
        applied = [r[0] for r in connection.exec_driver_sql('SELECT name FROM public.schema_migrations')]
        connection.rollback()
        def verify(live, names=applied, expected=candidate):
            _schema.verify_additive_compatibility(previous=previous, candidate=expected, live=live,
                previous_migrations=previous_names, candidate_migrations=candidate_names, applied_migrations=names)
        verify(candidate)
        with pytest.raises(_schema.SchemaCompatibilityError, match='manifest mismatch'):
            verify(candidate, applied + ['20261009_200000_unreviewed.sql'])
        for mutation in (
            'ALTER TABLE public.igrejas DISABLE ROW LEVEL SECURITY',
            'REVOKE SELECT ON public.pessoas FROM authenticated',
            "CREATE POLICY synthetic_unsafe_policy ON public.pessoas FOR SELECT TO authenticated USING (true)",
            'GRANT DELETE ON public.consolidation_whatsapp_activation TO authenticated',
            'ALTER TABLE public.pessoas DROP COLUMN nome CASCADE',
            "CREATE OR REPLACE FUNCTION public.current_igreja_id() RETURNS uuid LANGUAGE sql STABLE AS $$SELECT NULL::uuid$$",
        ):
            transaction = connection.begin()
            try:
                connection.exec_driver_sql(mutation)
                changed = _schema.capture_catalog(connection)
                with pytest.raises(_schema.SchemaCompatibilityError, match='catalogue drift'):
                    verify(changed)
                # Relabelling an incompatible catalogue as the candidate still
                # cannot prove compatibility with the previous package.
                with pytest.raises(_schema.SchemaCompatibilityError, match='previous schema contract changed'):
                    verify(changed, expected=changed)
            finally:
                transaction.rollback()
        # Interrupted/failing SQL is transactional; no partial column or ledger
        # entry survives, so the known additive candidate remains recoverable.
        with pytest.raises(Exception):
            with connection.begin():
                connection.exec_driver_sql('ALTER TABLE public.igrejas ADD COLUMN synthetic_failed integer')
                connection.exec_driver_sql('SELECT 1/0')
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        verify(_schema.capture_catalog(connection))
        assert set(connection.exec_driver_sql('SELECT synthetic_release_revision FROM public.igrejas').scalars()) == {1}
        connection.rollback()

