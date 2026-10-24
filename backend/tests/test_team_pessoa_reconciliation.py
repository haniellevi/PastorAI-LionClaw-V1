"""Reconciliação nominal de vínculo duplicado: contratos sem banco."""
import io
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from app.services import team_pessoa
from app.services.team_pessoa import DuplicateLinkReconciliation, ReconciliationRefused
from scripts import reconcile_team_pessoa

BACKEND = Path(__file__).resolve().parents[1]
SHA = '354a83d891fe7295164d980a175dacdd2feba69e'


FIELDS = ('operation_id', 'igreja_id', 'pessoa_id', 'keep_user_id', 'target_user_id',
          'church_admin_id', 'operator_id')


def _request(**changes):
    values = {field: uuid4() for field in FIELDS}
    values.update(release_sha=SHA, confirmation=None)
    values.update(changes)
    request = DuplicateLinkReconciliation(**values)
    if 'confirmation' not in changes:
        request = replace(request, confirmation=team_pessoa.confirmation_token(request))
    return request


class _NoDatabase:
    def __getattr__(self, name):
        raise AssertionError('a validação de entrada não deve consultar o banco')


def _refused(request, *, apply=True, lock_timeout_ms=5000):
    with pytest.raises(ReconciliationRefused) as exc:
        team_pessoa.reconcile_duplicate_link(_NoDatabase(), request, apply=apply,
                                             lock_timeout_ms=lock_timeout_ms)
    assert str(exc.value) == team_pessoa.REFUSALS[exc.value.code]
    return exc.value.code


def test_input_refusals_happen_before_database():
    same = uuid4()
    assert _refused(_request(keep_user_id=same, target_user_id=same), apply=False) == 'contas_iguais'
    assert _refused(_request(release_sha=SHA.upper()), apply=False) == 'sha_invalido'
    assert _refused(_request(release_sha=SHA[:7]), apply=False) == 'sha_invalido'


@pytest.mark.parametrize('value', [0, -1, 30001, 10**9, True, 1.5, '5000'])
def test_lock_timeout_outside_range_refused_before_database(value):
    assert _refused(_request(), apply=False, lock_timeout_ms=value) == 'lock_timeout_invalido'
    assert _refused(_request(), lock_timeout_ms=value) == 'lock_timeout_invalido'


@pytest.mark.parametrize('value', [1, 30000])
def test_lock_timeout_range_limits_accepted(value):
    team_pessoa.validate_request(_request(), apply=True, lock_timeout_ms=value)


def test_confirmation_must_be_exact_preview_token_bound_to_every_field():
    request = _request()
    token = team_pessoa.confirmation_token(request)
    assert token == f'DESVINCULAR:{request.payload_sha256()}'
    team_pessoa.validate_request(request, apply=True, lock_timeout_ms=5000)
    for wrong in (None, '', token + ' ', ' ' + token, token.lower().replace('desvincular', 'x'),
                  'DESVINCULAR:' + '0' * 64, request.payload_sha256()):
        assert _refused(replace(request, confirmation=wrong)) == 'confirmacao_invalida'
    changes = {field: uuid4() for field in FIELDS} | {'release_sha': '0' * 40}
    for field, value in changes.items():
        other = replace(request, **{field: value})
        assert team_pessoa.confirmation_token(other) != token
        assert _refused(other) == 'confirmacao_invalida'
    # A própria confirmação não participa do payload.
    assert replace(request, confirmation='outra').payload_sha256() == request.payload_sha256()


def _argv():
    argv = []
    for flag in ('--igreja', '--pessoa', '--manter', '--corrigir', '--admin-igreja', '--operador', '--operacao'):
        argv += [flag, str(uuid4())]
    return argv + ['--release-sha', SHA]


def test_cli_requires_dedicated_environment_variable(monkeypatch, capsys):
    monkeypatch.delenv(reconcile_team_pessoa.DATABASE_URL_ENV, raising=False)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://synthetic-should-not-be-used')
    monkeypatch.setattr(reconcile_team_pessoa, 'create_engine',
                        lambda *_a, **_k: pytest.fail('não deve conectar sem a variável dedicada'))
    assert reconcile_team_pessoa.run(_argv()) == 2
    out, err = capsys.readouterr()
    assert out == '' and reconcile_team_pessoa.DATABASE_URL_ENV in err
    assert 'synthetic-should-not-be-used' not in err


def test_cli_never_echoes_driver_errors(monkeypatch, capsys):
    secret_dsn = 'postgresql://operador:senha-sintetica@host-sintetico/banco'
    monkeypatch.setenv(reconcile_team_pessoa.DATABASE_URL_ENV, secret_dsn)

    class Engine:
        def connect(self):
            raise OperationalError(f'could not connect to {secret_dsn}', {}, Exception(secret_dsn))

        def dispose(self):
            pass

    monkeypatch.setattr(reconcile_team_pessoa, 'create_engine', lambda *_a, **_k: Engine())
    argv = _argv()
    assert reconcile_team_pessoa.run(argv) == 1
    out, err = capsys.readouterr()
    assert 'RECONCILIACAO_RECUSADA=falha_banco' in err and 'Traceback' not in err
    for private in ('senha-sintetica', 'host-sintetico', 'operador:', *argv[1::2]):
        assert private not in out + err


MARKER = 'SEGREDO-MARCADOR-SINTETICO'


@pytest.mark.parametrize('dsn', [
    f'mysql://usuario:{MARKER}@host/banco',
    f'sqlite:///{MARKER}.db',
    f'postgresql://usuario:{MARKER}@host:porta-invalida/banco',
    f'postgresql://usuario:{MARKER}@host',
    f'isto não é uma url {MARKER}',
    f'postgresql+asyncpg://usuario:{MARKER}@host/banco',
])
def test_cli_refuses_invalid_dsn_without_echo(monkeypatch, capsys, dsn):
    monkeypatch.setenv(reconcile_team_pessoa.DATABASE_URL_ENV, dsn)
    assert reconcile_team_pessoa.run(_argv()) == 2
    out, err = capsys.readouterr()
    assert out == '' and 'RECONCILIACAO_RECUSADA=conexao_invalida' in err
    assert MARKER not in out + err and 'Traceback' not in err


def test_cli_sanitizes_driver_parser_value_error(monkeypatch, capsys):
    monkeypatch.setenv(reconcile_team_pessoa.DATABASE_URL_ENV, 'postgresql://usuario@host/banco')

    def fail(*_args, **_kwargs):
        raise ValueError(f'invalid dsn: {MARKER}')

    monkeypatch.setattr(reconcile_team_pessoa, 'create_engine', fail)
    assert reconcile_team_pessoa.run(_argv()) == 2
    out, err = capsys.readouterr()
    assert MARKER not in out + err and 'Traceback' not in err


@pytest.mark.parametrize('value', ['0', '-5', '30001'])
def test_cli_refuses_lock_timeout_before_connecting(monkeypatch, capsys, value):
    monkeypatch.setenv(reconcile_team_pessoa.DATABASE_URL_ENV, 'postgresql://usuario@host/banco')
    monkeypatch.setattr(reconcile_team_pessoa, 'create_engine',
                        lambda *_a, **_k: pytest.fail('não deve conectar com lock_timeout inválido'))
    assert reconcile_team_pessoa.run(_argv() + ['--lock-timeout-ms', value]) == 1
    assert 'RECONCILIACAO_RECUSADA=lock_timeout_invalido' in capsys.readouterr().err


def test_cli_refuses_wrong_confirmation_before_connecting(monkeypatch, capsys):
    monkeypatch.setenv(reconcile_team_pessoa.DATABASE_URL_ENV, 'postgresql://usuario@host/banco')
    monkeypatch.setattr(reconcile_team_pessoa, 'create_engine',
                        lambda *_a, **_k: pytest.fail('não deve conectar com confirmação errada'))
    stdin = io.StringIO('DESVINCULAR:' + '0' * 64 + '\n')
    assert reconcile_team_pessoa.run(_argv() + ['--aplicar'], stdin=stdin) == 1
    assert 'RECONCILIACAO_RECUSADA=confirmacao_invalida' in capsys.readouterr().err


def test_service_and_cli_do_not_load_routers_or_application_settings():
    probe = ('import json, sys; import app.services.team_pessoa; import scripts.reconcile_team_pessoa; '
             'print(json.dumps(sorted(m for m in sys.modules if m.startswith("app."))))')
    result = subprocess.run([sys.executable, '-c', probe], cwd=BACKEND, capture_output=True, text=True,
                            env={'PATH': '/usr/bin:/bin', 'PYTHONPATH': str(BACKEND)})
    assert result.returncode == 0, result.stderr
    modules = json.loads(result.stdout)
    assert not [m for m in modules if m.startswith('app.routers') or m.startswith('app.agent')]
    assert 'app.config' not in modules and 'app.deps' not in modules and 'app.db.session' not in modules
