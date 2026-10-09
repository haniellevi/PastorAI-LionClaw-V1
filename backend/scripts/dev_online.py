"""Synthetic DEV seed entry, independent of dev_local's loopback-only CLI.

Run only inside the separately authorized DEV deployment/reset executor. This
module never changes a gate, calls Clerk, deletes data or connects by itself.
The caller provides a guarded connection; reset must recreate a disposable
synthetic dataset under the same deployment mutex before calling this seed.
"""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db.models import AgentConfig, AppUser, Igreja, Pessoa, UserRole
from scripts import dev_local

_PRODUCTION_PROJECT = 'pffafnchtxbimpwyaczq'


def validate_target(*, database_url: str, supabase_url: str, approved_project: str, app_env: str,
                    allow_real_sends: bool, brevo_mode: str, asaas_enabled: bool,
                    transport: str) -> None:
    """Positive project binding, rather than accepting every non-PROD host."""
    if (app_env != 'development' or allow_real_sends is not False or brevo_mode != 'off'
        or asaas_enabled is not False or transport != 'simulado'):
        raise ValueError('DEV containment required')
    if not re.fullmatch('[a-z]{20}', approved_project) or approved_project == _PRODUCTION_PROJECT:
        raise ValueError('approved DEV project required')
    service = urlsplit(supabase_url)
    if service.scheme != 'https' or service.hostname != approved_project + '.supabase.co' or service.username or service.password or service.query or service.fragment or service.path not in ('', '/'):
        raise ValueError('Supabase DEV identity mismatch')
    try:
        if service.port not in (None, 443):
            raise ValueError
        database = make_url(database_url)
    except (TypeError, ValueError):
        raise ValueError('invalid DEV routing') from None
    if database.drivername not in {'postgresql', 'postgresql+psycopg2'} or database.database != 'postgres':
        raise ValueError('DEV database identity mismatch')
    if dict(database.query) != {'sslmode': 'verify-full', 'sslrootcert': 'system'} or database.port not in (5432, 6543):
        raise ValueError('unexpected DEV database routing')
    direct = database.host == f'db.{approved_project}.supabase.co' and database.username == 'postgres'
    pooler = (bool(re.fullmatch(r'aws-[0-9]+-[a-z0-9-]+\.pooler\.supabase\.com', database.host or ''))
              and database.username == f'postgres.{approved_project}')
    if not (direct or pooler):
        raise ValueError('DEV database project mismatch')


def seed_synthetic(session: Session, *, target: dict) -> bool:
    """Validate nominal configuration and the bound engine before any seed SQL."""
    validate_target(**target)
    actual = session.get_bind().url.set(drivername='postgresql')
    expected = make_url(target['database_url']).set(drivername='postgresql')
    if actual != expected:
        raise ValueError('session is not bound to the approved DEV database')
    return _seed_synthetic(session)


def _seed_synthetic(session: Session) -> bool:
    """Idempotent seed; refuse a database with any unexpected tenant identity.

    Existing seed data is preserved. This is not a reset implementation, and the
    local CLI still retains its system-identifier receipt and loopback guard.
    Tenant IDs alone do not prove absence of real data. Reuse needs the
    separate owner-authorized resource/absence-of-real-data verification.
    No external account lookup or credentials are copied from production.
    """
    expected = {dev_local.IGREJA_ID, dev_local.IGREJA_VIZINHA_ID}
    existing = set(session.scalars(select(Igreja.id)))
    if existing - expected or (existing and existing != expected):
        raise ValueError('DEV is not an empty or complete synthetic dataset')
    if existing:
        return False
    now = dt.datetime.now(dt.timezone.utc)
    # Local seed assumes migration 0005's pilot rows. A new remote database
    # starts from explicit synthetic roots instead of adopting historical data.
    session.add(Igreja(id=dev_local.IGREJA_ID, nome='Igreja Local (teste)', status='ativa'))
    session.flush()
    session.add(Pessoa(id=dev_local.PASTOR_PESSOA_ID, igreja_id=dev_local.IGREJA_ID,
                       nome='Pastor Sintético', telefone=dev_local.fone(1)))
    session.flush()
    session.add(AppUser(id=dev_local.PASTOR_USER_ID, igreja_id=dev_local.IGREJA_ID,
                        pessoa_id=dev_local.PASTOR_PESSOA_ID, nome='Pastor Sintético',
                        email='pastor@igreja-local.test', status='ativo'))
    session.flush()
    session.add(UserRole(igreja_id=dev_local.IGREJA_ID, user_id=dev_local.PASTOR_USER_ID, papel='pastor'))
    session.add(AgentConfig(igreja_id=dev_local.IGREJA_ID, comportamento='Sintético', ativo=False))
    session.flush()
    from app.routers.platform_admin import _seed_role_permissions
    _seed_role_permissions(session, dev_local.IGREJA_ID)
    dev_local._criar_dados(session, now.date(), now)
    session.flush()
    if set(session.scalars(select(Igreja.id))) != expected:
        raise ValueError('synthetic seed identity mismatch')
    return True
