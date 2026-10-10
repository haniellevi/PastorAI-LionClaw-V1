"""Container-side synthetic DEV operations. Exceptions expose static codes only.

Executed from the reviewed control bundle; product code and active SQL come
from the immutable backend image. Never bootstrap roles in an online project.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from schema_compatibility import capture_catalog, verify_additive_compatibility


def fingerprint(receipt):
    return hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def target():
    from scripts.dev_online import validate_target
    from app.config import get_settings
    s = get_settings()
    if os.environ.get('RELEASE_PROFILE') == 'rehearsal':
        url = make_url(s.database_url)
        if (url.host != 'postgres' or url.database != 'rls_disposable' or url.username != 'postgres'
            or url.port not in (None, 5432) or url.query or s.app_env != 'development'
            or s.allow_real_sends or s.brevo_send_mode != 'off' or s.asaas_billing_enabled
            or s.whatsapp_transporte != 'simulado'):
            raise ValueError('disposable target refused')
    else:
        validate_target(database_url=s.database_url, supabase_url=s.supabase_url,
                        approved_project=os.environ['DEV_APPROVED_PROJECT'], app_env=s.app_env,
                        allow_real_sends=s.allow_real_sends, brevo_mode=s.brevo_send_mode,
                        asaas_enabled=s.asaas_billing_enabled, transport=s.whatsapp_transporte)
    return create_engine(s.database_url)


def receipt(engine):
    with engine.connect() as c:
        c.exec_driver_sql('SET TRANSACTION READ ONLY')
        return {'catalog': capture_catalog(c), 'migrations': sorted(c.exec_driver_sql(
            'SELECT name FROM public.schema_migrations').scalars())}


def bootstrap(engine):
    if os.environ.get('RELEASE_PROFILE') != 'rehearsal':
        raise ValueError('online bootstrap refused')
    with engine.begin() as c:
        if c.exec_driver_sql("SELECT to_regclass('public.schema_migrations')").scalar():
            raise ValueError('bootstrap requires empty disposable database')
        for role, bypass in (('anon', False), ('authenticated', False), ('service_role', True)):
            c.exec_driver_sql(f"CREATE ROLE {role} NOLOGIN {'BYPASSRLS' if bypass else 'NOBYPASSRLS'}")
        for kind in ('TABLES', 'SEQUENCES', 'FUNCTIONS'):
            c.exec_driver_sql(f'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON {kind} TO anon, authenticated, service_role')
        c.exec_driver_sql('CREATE TABLE public.schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())')


def migrate(engine):
    from scripts import migrate as runner
    with engine.connect() as c:
        applied = set(c.exec_driver_sql('SELECT name FROM public.schema_migrations').scalars())
    files = runner.migration_files()
    if applied - set(files):
        raise ValueError('unknown migration ledger')
    for name in runner.pending(files, applied):
        body = (runner.MIGRATIONS_DIR / name).read_text()
        # Nontransactional DDL cannot be advertised as automatically recovered.
        concurrent = any('index concurrently' in line.lower() for line in body.splitlines() if not line.lstrip().startswith('--'))
        reset_empty=(os.environ.get('DEV_RESET_EMPTY_SCHEMA')=='true' and
                     os.environ.get('DEV_RESET_APPROVED_PROJECT')==os.environ.get('DEV_APPROVED_PROJECT') and
                     bool(os.environ.get('DEV_APPROVED_PROJECT')))
        if concurrent and os.environ.get('RELEASE_PROFILE') != 'rehearsal' and not reset_empty:
            raise ValueError('nontransactional migration requires separate operation')
        pooled = engine.raw_connection()
        connection = pooled.driver_connection
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                runner.cmd_apply(connection, name, transactional=not concurrent)
        finally:
            connection.autocommit = False
            pooled.close()


def verify(engine, previous, candidate):
    live = receipt(engine)
    verify_additive_compatibility(previous=previous['catalog'], candidate=candidate['catalog'],
        live=live['catalog'], previous_migrations=previous['migrations'],
        candidate_migrations=candidate['migrations'], applied_migrations=live['migrations'])


def seed(engine):
    from scripts.dev_online import _seed_synthetic, seed_synthetic
    from scripts import dev_local
    from app.db.models import Igreja
    from sqlalchemy import delete
    from app.config import get_settings
    with Session(engine) as session, session.begin():
        reset_approved=os.environ.get('DEV_RESET_APPROVED_PROJECT')==os.environ.get('DEV_APPROVED_PROJECT') and bool(os.environ.get('DEV_APPROVED_PROJECT'))
        if os.environ.get('RELEASE_PROFILE') == 'rehearsal':
            # Only a new, controller-owned disposable stack may clear historical
            # demo roots. Online data is never adopted or deleted by this entry.
            if os.environ.get('REHEARSAL_FRESH_DATABASE') == 'true':
                session.execute(delete(Igreja))
            _seed_synthetic(session)
        else:
            if reset_approved:
                session.execute(delete(Igreja))
            s = get_settings()
            seed_synthetic(session, target=dict(database_url=s.database_url, supabase_url=s.supabase_url,
                approved_project=os.environ['DEV_APPROVED_PROJECT'], app_env=s.app_env,
                allow_real_sends=s.allow_real_sends, brevo_mode=s.brevo_send_mode,
                asaas_enabled=s.asaas_billing_enabled, transport=s.whatsapp_transporte))
        tenants = session.scalars(text('SELECT id FROM public.igrejas')).all()
        if set(map(str, tenants)) != {str(dev_local.IGREJA_ID), str(dev_local.IGREJA_VIZINHA_ID)}:
            raise ValueError('two synthetic churches required')


def reset(engine):
    approved=os.environ.get('DEV_RESET_APPROVED_PROJECT')
    if not approved or approved!=os.environ.get('DEV_APPROVED_PROJECT'):
        raise ValueError('nominal synthetic reset confirmation required')
    from scripts import dev_local
    with engine.begin() as c:
        tenants=set(map(str,c.exec_driver_sql('SELECT id FROM public.igrejas').scalars()))
        if tenants!={str(dev_local.IGREJA_ID),str(dev_local.IGREJA_VIZINHA_ID)}:
            raise ValueError('reset target is not the complete synthetic seed')
        c.exec_driver_sql('DROP SCHEMA public CASCADE')
        c.exec_driver_sql('CREATE SCHEMA public AUTHORIZATION postgres')
        for kind in ('TABLES','SEQUENCES','FUNCTIONS'):
            c.exec_driver_sql(f'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON {kind} TO anon, authenticated, service_role')
        c.exec_driver_sql('CREATE TABLE public.schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())')


def main():
    action = sys.argv[1]
    engine = target()
    try:
        if action == 'verify-target':
            pass
        elif action == 'bootstrap':
            bootstrap(engine)
        elif action == 'migrate':
            migrate(engine)
        elif action == 'seed':
            seed(engine)
        elif action == 'reset':
            reset(engine)
        elif action == 'capture':
            print(json.dumps(receipt(engine), sort_keys=True))
        elif action == 'verify':
            verify(engine, json.loads(Path(sys.argv[2]).read_text()), json.loads(Path(sys.argv[3]).read_text()))
        else:
            raise ValueError('unknown database operation')
    finally:
        engine.dispose()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Error type and code location only, never SQL, configuration or PII.
        import traceback
        frame=traceback.extract_tb(error.__traceback__)[-1]
        print(f'synthetic database operation refused: {type(error).__name__} at {frame.name}:{frame.lineno}', file=sys.stderr)
        sys.exit(1)
