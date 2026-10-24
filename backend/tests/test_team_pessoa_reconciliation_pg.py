"""Reconciliação nominal de vínculo duplicado: PostgreSQL local e dados sintéticos.

O schema é o baseline real de PROD lido em 24/10: as migrations ativas até
20261014, menos as quatro antigas pendentes, aplicadas uma a uma pelo
aplicador oficial (78 nomes no ledger). O último teste aplica as 46 pendentes,
inclusive ``20261025_100000_team_pessoa.sql``, sobre os dados reconciliados.
"""
import io
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services import team_pessoa
from app.services.team_pessoa import DuplicateLinkReconciliation, ReconciliationRefused
from scripts import migrate, reconcile_team_pessoa
from tests.conftest_rls import assert_disposable_database
from tests.test_uv_turmas_pg import rls_database_url, scoped  # noqa: F401

pytestmark = pytest.mark.rls_integration
TEAM_MIGRATION = '20261025_100000_team_pessoa.sql'
BASELINE_DATE = '20261014'
OLD_PENDING = frozenset({
    '20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql',
    '20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql',
    '20260925_183811_preserve_platform_admins_on_tenant_deletion.sql',
    '20260926_120446_platform_jev_settings.sql',
})
SHA = '354a83d891fe7295164d980a175dacdd2feba69e'
TRIGGER = 'synthetic_reconcile_audit_failure'
RUNNER = Path(__file__).resolve().parents[1] / 'scripts/migrate.py'


def _baseline_files():
    # migration_files() já exclui as pausadas (OPERATIONAL_AUTHORIZATION=BLOCKED).
    return [name for name in migrate.migration_files()
            if name[:8] <= BASELINE_DATE and name not in OLD_PENDING]


def _migration_env(url):
    return dict(os.environ, MIGRATION_DATABASE_URL=url.replace('postgresql+psycopg2:', 'postgresql:'))


def _apply_migration(env, filename):
    body = (migrate.MIGRATIONS_DIR / filename).read_text()
    concurrent = any('index concurrently' in line.lower() for line in body.splitlines()
                     if not line.lstrip().startswith('--'))
    command = [sys.executable, str(RUNNER), 'apply', filename, '--yes']
    if concurrent:
        command.append('--no-transaction')
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 0, f'{filename}: {result.stderr}'


def _clean(c):
    c.exec_driver_sql(f'drop trigger if exists {TRIGGER} on platform_audit_log')
    c.exec_driver_sql('delete from platform_audit_log; delete from igrejas')


@pytest.fixture(scope='module')
def baseline(rls_database_url):  # noqa: F811
    assert_disposable_database(rls_database_url)
    engine = create_engine(rls_database_url)
    # Mesmo bootstrap sintético do Supabase de test_uv_turmas_pg.
    with engine.begin() as c:
        c.exec_driver_sql('drop schema public cascade; create schema public')
        for role, bypass in (('anon', False), ('authenticated', False), ('service_role', True)):
            c.exec_driver_sql(f"""do $$ begin
                if not exists(select 1 from pg_roles where rolname='{role}') then
                    create role {role} nologin {'bypassrls' if bypass else 'nobypassrls'};
                end if; end $$""")
            c.exec_driver_sql(f"alter role {role} {'bypassrls' if bypass else 'nobypassrls'}")
        c.exec_driver_sql('grant usage on schema public to anon, authenticated, service_role')
        for obj in ('tables', 'sequences', 'functions'):
            c.exec_driver_sql(f'alter default privileges in schema public grant all on {obj} to anon, authenticated')
            c.exec_driver_sql(f'alter default privileges in schema public grant all on {obj} to service_role')
        c.exec_driver_sql('create table public.schema_migrations(name text primary key)')
    files = _baseline_files()
    assert len(files) == 78
    env = _migration_env(rls_database_url)
    for filename in files:
        _apply_migration(env, filename)
    with engine.connect() as c:
        assert set(c.execute(text('select name from schema_migrations')).scalars()) == set(files)
        assert c.scalar(text("select to_regclass('public.team_pessoa_eventos')")) is None
        assert c.scalar(text("select to_regclass('public.app_users_pessoa_unica_por_igreja')")) is None
        assert c.scalar(text("select to_regclass('public.auth_sessions')")) is None
    yield engine
    engine.dispose()


def _user(c, *, tenant, pessoa=None, role='membro', clerk=True, status='ativo'):
    user = uuid4()
    c.execute(text("""insert into app_users(id,igreja_id,status,nome,email,pessoa_id,clerk_user_id)
        values(:u,:t,:s,'Conta sintética',:e,:p,:c)"""), dict(
            u=user, t=tenant, s=status, e=f'{user}@example.test', p=pessoa,
            c=f'clerk_{user.hex}' if clerk else None))
    c.execute(text('insert into user_roles(igreja_id,user_id,papel) values(:t,:u,:r)'),
              dict(t=tenant, u=user, r=role))
    return user


def _person(c, tenant):
    person = uuid4()
    c.execute(text("insert into pessoas(id,igreja_id,nome,telefone) values(:p,:t,'Pessoa sintética',:f)"),
              dict(p=person, t=tenant, f='55' + str(person.int)[:11]))
    return person


def _active_cell(c, tenant, leader):
    columns = set(c.execute(text("select column_name from information_schema.columns "
                                 "where table_schema='public' and table_name='celulas'")).scalars())
    extra = ('cobertura_espiritual',) if 'cobertura_espiritual' in columns else ()
    names = ','.join(('igreja_id', 'nome', 'lider_id', 'ativo') + extra)
    values = ",:t,'Célula sintética',:p,true" + (",'Teste sintético'" if extra else '')
    c.execute(text(f'insert into celulas({names}) values({values[1:]})'), dict(t=tenant, p=leader))


def _grant_platform(c, user):
    c.execute(text("insert into platform_admins(app_user_id,email) values(:u,'platform@example.test')"),
              dict(u=user))


@pytest.fixture
def world(baseline):
    legacy = baseline
    with legacy.begin() as c:
        _clean(c)
        t, other = uuid4(), uuid4()
        for tenant in (t, other):
            c.execute(text("insert into igrejas(id,nome) values(:t,'Igreja sintética')"), dict(t=tenant))
        p = _person(c, t)
        v = dict(t=t, other=other, p=p)
        v['admin'] = _user(c, tenant=t, pessoa=_person(c, t), role='admin')
        v['keep'] = _user(c, tenant=t, pessoa=p, role='pastor')
        v['target'] = _user(c, tenant=t, pessoa=p, role='operador')
        v['operator'] = _user(c, tenant=other, pessoa=_person(c, other), role='admin')
        _grant_platform(c, v['operator'])
        c.execute(text('update igrejas set dono_id=:u where id=:t'), dict(u=v['admin'], t=t))
    v['db'] = legacy
    return v


def _request(v, **changes):
    values = dict(operation_id=v.setdefault('op', uuid4()), igreja_id=v['t'], pessoa_id=v['p'],
                  keep_user_id=v['keep'], target_user_id=v['target'],
                  church_admin_id=v['admin'], operator_id=v['operator'],
                  release_sha=SHA, confirmation=None)
    values.update(changes)
    request = DuplicateLinkReconciliation(**values)
    if 'confirmation' not in changes:
        request = replace(request, confirmation=team_pessoa.confirmation_token(request))
    return request


def _argv(request):
    return ['--igreja', str(request.igreja_id), '--pessoa', str(request.pessoa_id),
            '--manter', str(request.keep_user_id), '--corrigir', str(request.target_user_id),
            '--admin-igreja', str(request.church_admin_id), '--operador', str(request.operator_id),
            '--operacao', str(request.operation_id), '--release-sha', request.release_sha]


@pytest.fixture
def cli(monkeypatch, capsys, rls_database_url):  # noqa: F811
    monkeypatch.setenv(reconcile_team_pessoa.DATABASE_URL_ENV, rls_database_url)

    def run(request, *, apply=False, confirmation=None, extra=()):
        argv = _argv(request) + (['--aplicar'] if apply else []) + list(extra)
        line = request.confirmation if confirmation is None else confirmation
        code = reconcile_team_pessoa.run(argv, stdin=io.StringIO((line or '') + '\n'))
        out, err = capsys.readouterr()
        return code, out, err
    return run


def _state(v):
    with v['db'].connect() as c:
        return dict(
            users=c.execute(text('select id,igreja_id,pessoa_id,status,clerk_user_id from app_users order by id')).all(),
            roles=c.execute(text('select igreja_id,user_id,papel from user_roles order by user_id,papel')).all(),
            owners=c.execute(text('select id,dono_id from igrejas order by id')).all(),
            audit=c.scalar(text('select count(*) from platform_audit_log')),
        )


def _assert_sanitized(v, *outputs):
    for output in outputs:
        for key in ('t', 'other', 'p', 'admin', 'keep', 'target', 'operator', 'op'):
            assert str(v[key]) not in output
        assert 'example.test' not in output and 'sintética' not in output
        assert 'postgresql' not in output and 'Traceback' not in output


def test_preview_is_read_only_and_sanitized(world, cli):
    v = world
    before = _state(v)
    code, out, err = cli(_request(v))
    assert code == 0, err
    assert out.splitlines() == [
        'RESULTADO=PREVIA_OK grupo_linhas_antes=2 grupo_linhas_depois=1 '
        'admins_ativos_antes=1 admins_ativos_depois=1 linhas_alteradas=0',
        f'CONFIRMACAO={team_pessoa.confirmation_token(_request(v))}',
    ]
    assert _state(v) == before
    _assert_sanitized(v, out, err)


def _preview_token(cli, request):
    code, out, err = cli(request)
    assert code == 0, err
    return out.splitlines()[-1].removeprefix('CONFIRMACAO=')


def test_apply_unlinks_only_target_with_atomic_audit_and_idempotency(world, cli):
    v = world
    before = _state(v)
    token = _preview_token(cli, _request(v))
    code, out, err = cli(_request(v), apply=True, confirmation=token)
    assert code == 0, err
    assert out.startswith('RESULTADO=APLICADA grupo_linhas_antes=2 grupo_linhas_depois=1')
    _assert_sanitized(v, out, err)
    after = _state(v)
    expected_users = [row if row[0] != v['target'] else (row[0], row[1], None, row[3], row[4])
                      for row in before['users']]
    assert after['users'] == expected_users
    assert after['roles'] == before['roles'] and after['owners'] == before['owners']
    with v['db'].connect() as c:
        row = c.execute(text('select actor_id,actor_email,acao,alvo_tipo,alvo_id,alvo_nome,detalhe from platform_audit_log')).one()
        assert c.scalar(text('select count(*) from (select igreja_id,pessoa_id from app_users '
                             'where pessoa_id is not null group by 1,2 having count(*)>1) d')) == 0
    actor, email, acao, alvo_tipo, alvo, nome, detalhe = row
    assert (actor, email, acao, alvo_tipo, alvo, nome) == (
        v['operator'], None, team_pessoa.RECONCILE_ACTION, 'app_user', v['target'], None)
    assert detalhe['operation_id'] == str(v['op']) and detalhe['release_sha'] == SHA
    assert detalhe['conta_mantida'] == str(v['keep']) and detalhe['admin_igreja'] == str(v['admin'])
    assert detalhe['payload_sha256'] == _request(v).payload_sha256()
    assert set(detalhe) == {'operation_id', 'payload_sha256', 'operacao', 'igreja_id', 'pessoa_id',
                            'conta_mantida', 'conta_corrigida', 'admin_igreja', 'release_sha'}

    code, out, err = cli(_request(v), apply=True)
    assert code == 0 and out.startswith('RESULTADO=JA_APLICADA'), err
    code, out, err = cli(_request(v, release_sha='0' * 40), apply=True)
    assert code == 1 and 'RECONCILIACAO_RECUSADA=operacao_reutilizada' in err
    assert _state(v)['audit'] == 1


def test_operator_may_be_the_church_admin_with_both_current_roles(world, cli):
    v = world
    with v['db'].begin() as c:
        _grant_platform(c, v['admin'])
    request = _request(v, operator_id=v['admin'])
    code, out, err = cli(request, apply=True)
    assert code == 0 and out.startswith('RESULTADO=APLICADA'), err
    with v['db'].connect() as c:
        assert c.scalar(text('select actor_id from platform_audit_log')) == v['admin']


@pytest.mark.parametrize('revocation,expected', [
    ('platform_membership', 'operador_invalido'),
    ('operator_status', 'operador_invalido'),
    ('admin_role', 'admin_igreja_invalido'),
    ('admin_status', 'admin_igreja_invalido'),
])
def test_replay_revalidates_current_authorization(world, cli, revocation, expected):
    v = world
    code, _, err = cli(_request(v), apply=True)
    assert code == 0, err
    with v['db'].begin() as c:
        if revocation == 'platform_membership':
            c.execute(text('delete from platform_admins where app_user_id=:u'), dict(u=v['operator']))
        elif revocation == 'operator_status':
            c.execute(text("update app_users set status='revogado' where id=:u"), dict(u=v['operator']))
        elif revocation == 'admin_role':
            c.execute(text("delete from user_roles where user_id=:u and papel='admin'"), dict(u=v['admin']))
        else:
            c.execute(text("update app_users set status='revogado' where id=:u"), dict(u=v['admin']))
    for apply in (False, True):
        code, out, err = cli(_request(v), apply=apply)
        assert code == 1 and f'RECONCILIACAO_RECUSADA={expected}' in err and out == ''
    assert _state(v)['audit'] == 1


@pytest.mark.parametrize('case,expected', [
    ('manter_revogada', 'conta_mantida_invalida'),
    ('manter_convidada', 'conta_mantida_invalida'),
    ('manter_sem_clerk', 'conta_mantida_invalida'),
    ('confirmacao_errada', 'confirmacao_invalida'),
    ('confirmacao_de_outro_payload', 'confirmacao_invalida'),
    ('sem_admin', 'admin_igreja_invalido'),
    ('admin_revogado', 'admin_igreja_invalido'),
    ('admin_outra_igreja', 'admin_igreja_invalido'),
    ('sem_platform', 'operador_invalido'),
    ('platform_revogado', 'operador_invalido'),
    ('platform_sem_clerk', 'operador_invalido'),
    ('outra_igreja', 'pessoa_nao_encontrada'),
    ('conta_outra_igreja', 'grupo_divergente'),
    ('grupo_maior', 'grupo_divergente'),
    ('grupo_resolvido', 'grupo_resolvido'),
    ('lider', 'lideranca_ativa'),
    ('mesma_conta', 'contas_iguais'),
    ('sha', 'sha_invalido'),
    ('sem_confirmacao', 'confirmacao_invalida'),
])
def test_refusals_change_nothing(world, cli, case, expected):
    v = world
    changes, confirmation = {}, None
    with v['db'].begin() as c:
        if case.startswith('manter_'):
            column, value = {'manter_revogada': ('status', 'revogado'),
                             'manter_convidada': ('status', 'convidado'),
                             'manter_sem_clerk': ('clerk_user_id', None)}[case]
            c.execute(text(f'update app_users set {column}=:v where id=:u'), dict(v=value, u=v['keep']))
        elif case == 'confirmacao_errada':
            confirmation = 'DESVINCULAR:' + '0' * 64
        elif case == 'confirmacao_de_outro_payload':
            confirmation = team_pessoa.confirmation_token(_request(v, operation_id=uuid4()))
        elif case == 'sem_admin':
            changes['church_admin_id'] = v['keep']
        elif case == 'admin_revogado':
            c.execute(text("update app_users set status='revogado' where id=:u"), dict(u=v['admin']))
        elif case == 'admin_outra_igreja':
            changes['church_admin_id'] = v['operator']
        elif case == 'sem_platform':
            changes['operator_id'] = v['admin']
        elif case == 'platform_revogado':
            c.execute(text("update app_users set status='revogado' where id=:u"), dict(u=v['operator']))
        elif case == 'platform_sem_clerk':
            c.execute(text('update app_users set clerk_user_id=null where id=:u'), dict(u=v['operator']))
        elif case == 'outra_igreja':
            changes['igreja_id'] = v['other']
        elif case == 'conta_outra_igreja':
            other_person = _person(c, v['other'])
            changes['keep_user_id'] = _user(c, tenant=v['other'], pessoa=other_person)
        elif case == 'grupo_maior':
            _user(c, tenant=v['t'], pessoa=v['p'])
        elif case == 'grupo_resolvido':
            c.execute(text('update app_users set pessoa_id=null where id=:u'), dict(u=v['target']))
        elif case == 'lider':
            _active_cell(c, v['t'], v['p'])
        elif case == 'mesma_conta':
            changes['keep_user_id'] = v['target']
        elif case == 'sha':
            changes['release_sha'] = SHA[:12]
        elif case == 'sem_confirmacao':
            confirmation = '   '
    before = _state(v)
    for apply in (False, True):
        if case.startswith(('confirmacao', 'sem_confirmacao')) and not apply:
            continue
        code, out, err = cli(_request(v, **changes), apply=apply, confirmation=confirmation)
        assert code == 1, (out, err)
        assert f'RECONCILIACAO_RECUSADA={expected}' in err
        assert out == ''
        _assert_sanitized(v, err)
        assert _state(v) == before


def test_role_without_bypassrls_refused(world):
    v = world
    with scoped(v['db'], v['t']) as db:
        with pytest.raises(ReconciliationRefused) as exc:
            team_pessoa.reconcile_duplicate_link(db, _request(v), apply=False)
    assert exc.value.code == 'role_sem_bypassrls'


@pytest.mark.parametrize('ddl,expected', [
    ('alter table platform_audit_log rename to platform_audit_log_ausente', 'auditoria_ausente'),
    ('alter table platform_audit_log rename column detalhe to detalhe_ausente', 'auditoria_ausente'),
    ('alter table igrejas rename column dono_id to dono_ausente', 'schema_incompativel'),
])
def test_incompatible_schema_refused_without_creating_tables(world, ddl, expected):
    v = world
    with Session(v['db']) as db:
        db.execute(text(ddl))  # DDL transacional: desfeita pelo rollback abaixo.
        tables_before = db.scalar(text("select count(*) from pg_tables where schemaname='public'"))
        with pytest.raises(ReconciliationRefused) as exc:
            team_pessoa.reconcile_duplicate_link(db, _request(v), apply=True)
        assert exc.value.code == expected
        assert db.scalar(text("select count(*) from pg_tables where schemaname='public'")) == tables_before
        assert db.scalar(text('select pessoa_id from app_users where id=:u'), dict(u=v['target'])) == v['p']
        db.rollback()
    assert _state(v)['audit'] == 0


def test_audit_failure_rolls_back_unlink(world, cli):
    v = world
    with v['db'].begin() as c:
        c.exec_driver_sql("""create or replace function synthetic_reconcile_audit_failure() returns trigger
            language plpgsql as $$ begin raise exception 'falha sintética'; end $$""")
        c.exec_driver_sql(f"""create trigger {TRIGGER} before insert on platform_audit_log
            for each row execute function synthetic_reconcile_audit_failure()""")
    before = _state(v)
    code, out, err = cli(_request(v), apply=True)
    assert code == 1 and 'RECONCILIACAO_RECUSADA=falha_banco' in err
    assert 'falha sintética' not in err and out == ''
    assert _state(v) == before


def test_lock_held_by_old_caller_times_out_without_change(world, cli):
    v = world
    before = _state(v)
    with v['db'].connect() as holder:
        holder.begin()
        holder.execute(text('select id from pessoas where id=:p for update'), dict(p=v['p']))
        code, out, err = cli(_request(v), apply=True, extra=['--lock-timeout-ms', '300'])
        holder.rollback()
    assert code == 1 and 'RECONCILIACAO_RECUSADA=lock_indisponivel' in err
    assert _state(v) == before


def _wait_for_lock_waiter(db, deadline=5):
    limit = time.monotonic() + deadline
    with db.connect() as c:
        while not c.scalar(text('select count(*) from pg_locks where not granted')):
            assert time.monotonic() < limit, 'a reconciliação não aguardou a trava'
            time.sleep(0.01)


def _apply_in_session(v, request):
    with Session(v['db']) as db:
        try:
            result = team_pessoa.reconcile_duplicate_link(db, request, apply=True, lock_timeout_ms=10000)
            db.commit()
            return result.code
        except ReconciliationRefused as exc:
            db.rollback()
            return exc.code


def test_revalidates_group_after_waiting_for_concurrent_fix(world):
    v = world
    with v['db'].connect() as holder, ThreadPoolExecutor(max_workers=1) as pool:
        holder.begin()
        holder.execute(text('select id from pessoas where id=:p for update'), dict(p=v['p']))
        holder.execute(text('update app_users set pessoa_id=null where id=:u'), dict(u=v['target']))
        pending = pool.submit(_apply_in_session, v, _request(v))
        _wait_for_lock_waiter(v['db'])
        holder.commit()
        assert pending.result(timeout=15) == 'grupo_resolvido'
    assert _state(v)['audit'] == 0


@pytest.mark.parametrize('revocation,expected', [
    ('platform_membership', 'operador_invalido'),
    ('admin_role', 'admin_igreja_invalido'),
])
@pytest.mark.parametrize('outcome', ['commit', 'rollback'])
def test_concurrent_authorization_revocation_waits_then_decides(world, revocation, expected, outcome):
    """A operação espera a revogação em curso; só aplica se ela for desfeita."""
    v = world
    before = _state(v)
    with v['db'].connect() as holder, ThreadPoolExecutor(max_workers=1) as pool:
        holder.begin()
        if revocation == 'platform_membership':
            holder.execute(text('delete from platform_admins where app_user_id=:u'), dict(u=v['operator']))
        else:
            holder.execute(text("delete from user_roles where user_id=:u and papel='admin'"), dict(u=v['admin']))
        pending = pool.submit(_apply_in_session, v, _request(v))
        _wait_for_lock_waiter(v['db'])
        assert not pending.done()
        if outcome == 'commit':
            holder.commit()
        else:
            holder.rollback()
        result = pending.result(timeout=15)
    after = _state(v)
    if outcome == 'commit':
        assert result == expected
        assert after['users'] == before['users'] and after['audit'] == 0
    else:
        assert result == 'APLICADA'
        assert after['audit'] == 1


def test_same_operation_concurrently_applies_once(world):
    v = world
    request = _request(v)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(lambda _: _apply_in_session(v, request), range(2)))
    assert results == ['APLICADA', 'JA_APLICADA']
    with v['db'].connect() as c:
        assert c.scalar(text('select count(*) from platform_audit_log')) == 1
        assert c.execute(text('select id from app_users where pessoa_id=:p'), dict(p=v['p'])).scalars().all() == [v['keep']]


def test_zz_reconciled_baseline_accepts_pending_batch_with_team_migration(world, cli, rls_database_url):  # noqa: F811
    """Último do módulo: altera o schema do baseline para o SHA inteiro."""
    v = world
    code, out, err = cli(_request(v), apply=True)
    assert code == 0 and out.startswith('RESULTADO=APLICADA'), err
    baseline = set(_baseline_files())
    pending = [name for name in migrate.migration_files() if name not in baseline]
    assert len(pending) == 46 and OLD_PENDING <= set(pending) and TEAM_MIGRATION in pending
    env = _migration_env(rls_database_url)
    for filename in pending:
        _apply_migration(env, filename)
    with v['db'].connect() as c:
        assert c.scalar(text("select to_regclass('public.app_users_pessoa_unica_por_igreja')")) is not None
        assert c.scalar(text("select to_regclass('public.team_pessoa_eventos')")) is not None
        assert c.scalar(text('select count(*) from schema_migrations')) == len(migrate.migration_files())
        assert c.execute(text('select id from app_users where pessoa_id=:p'), dict(p=v['p'])).scalars().all() == [v['keep']]
        assert c.scalar(text('select count(*) from team_pessoa_eventos')) == 0
