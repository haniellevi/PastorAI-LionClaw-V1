"""Controller source connections never inherit libpq routing/authentication defaults."""
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_database as database
import first_transition_window as window
from test_first_transition_window_entry import entry, pinned  # noqa: F401
from test_first_transition_orchestrator import no_real_processes_or_network  # noqa: F401


@pytest.fixture(autouse=True)
def clean_test_libpq_environment(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith('PG'):
            monkeypatch.delenv(name)


@pytest.mark.parametrize('name', ['PGHOSTADDR', 'PGSERVICE', 'PGPORT'])
def test_source_factory_refuses_before_secret_or_connect(monkeypatch, name):
    sentinel = 'SENTINEL-INHERITED-LIBPQ-PRIVATE'
    monkeypatch.setenv(name, sentinel)
    before, calls = dict(os.environ), []
    def secret():
        calls.append('secret')
        return 'postgresql://synthetic:fictional@invalid.example/app'
    def connect(*args, **kwargs):
        calls.append('connect')
        raise AssertionError('connection must never be reached')
    factory = database.psycopg2_connector(secret, connect=connect)
    with pytest.raises(database.Refused, match='^database-libpq-environment$') as error:
        factory(timeout=1)
    assert calls == [] and dict(os.environ) == before
    assert sentinel not in str(error.value)


@pytest.mark.parametrize('mode', ['run', 'check', 'check-bindings', 'rehearse-backup'])
def test_entry_refuses_inherited_libpq_before_any_io(entry, monkeypatch, mode):
    digests = entry.prepare()
    sentinel = 'SENTINEL-INHERITED-LIBPQ-PRIVATE'
    monkeypatch.setenv('PGHOSTADDR', sentinel)
    if mode == 'run':
        code, lines = entry.execute(digests)
    else:
        output = []
        code = window.main(entry.args(mode), out=output.append, io=entry.io)
        lines = [json.loads(line) for line in output]
    assert code == 2 and lines == [{'refused': 'database-libpq-environment'}]
    assert entry.calls == [] and entry.connections == [] and entry.assembly.popen_calls == []
    assert not (Path(entry.raw['state_dir']) / 'journal').exists()
    assert sentinel not in json.dumps(lines)
    assert os.environ['PGHOSTADDR'] == sentinel


def test_prepare_stays_pure_with_unrelated_ambient_libpq(entry, monkeypatch):
    monkeypatch.setenv('PGHOSTADDR', 'SENTINEL-INHERITED-LIBPQ-PRIVATE')
    prepared = entry.prepare()
    assert prepared['production_ready'] is False
    assert entry.calls == [] and entry.connections == [] and entry.assembly.popen_calls == []
