"""Run the installed backup entrypoint against fake IO and owned temporary paths."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


BACKUP = Path(__file__).resolve().parents[2] / 'backup-production.sh'
NAMES = ('pastorai_evolution', 'pastorai_evo_postgres', 'pastorai_redis')
IDS = tuple(c * 64 for c in 'abc')

FAKE_DOCKER = """\
import json
import os
from pathlib import Path
import sys

state = Path(os.environ['FAKE_SUPPORT_STATE'])
mode = os.environ['FAKE_SUPPORT_MODE']
data = json.loads(state.read_text())
verb, *args = sys.argv[1:]
if verb == 'inspect':
    name = args[-1]
    ident, status = data[name]
    print(f"/{name} {ident} {status} {str(status == 'paused').lower()}")
elif verb in ('pause', 'unpause'):
    ident, = args
    with state.with_suffix('.calls').open('a') as log:
        log.write(f'{verb} {ident}\\n')
    name, = [name for name, (saved, _) in data.items() if saved == ident]
    if verb == 'unpause' and mode == 'cleanup-error' and name == 'pastorai_evolution':
        sys.exit(18)
    if verb == 'pause' and name == 'pastorai_evo_postgres':
        if mode == 'replaced':
            data['pastorai_evolution'] = ['d' * 64, 'paused']
            state.write_text(json.dumps(data))
        if mode == 'lost-ack':
            data[name][1] = 'paused'
            state.write_text(json.dumps(data))
        if mode in ('partial', 'replaced', 'lost-ack'):
            sys.exit(19)
    data[name][1] = 'paused' if verb == 'pause' else 'running'
    state.write_text(json.dumps(data))
elif verb == 'run' and mode == 'volume-error' and 'alpine:3.20' in args:
    sys.exit(17)
elif verb == 'run' or verb == 'exec':
    print('synthetic')
elif verb != 'pull':
    sys.exit(90)
"""


@pytest.mark.skipif(not hasattr(os, 'geteuid') or os.geteuid() != 0, reason='requires isolated Linux root')
@pytest.mark.parametrize(('mode', 'paused_after', 'attempted', 'released'), [
    ('success', (), (0, 1, 2), (0, 1, 2)),
    ('partial', (), (0, 1), (0,)),
    ('prepaused', (1,), (), ()),
    ('replaced', (0,), (0, 1), ()),
    ('lost-ack', (1,), (0, 1), (0,)),
    ('volume-error', (), (0, 1, 2), (0, 1, 2)),
    ('cleanup-error', (0,), (0, 1, 2), (0, 1, 2, 0)),
])
def test_backup_pause_ownership(tmp_path, mode, paused_after, attempted, released):
    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    for name, body in {
        'docker': f'#!{sys.executable}\n' + FAKE_DOCKER,
        'curl': '#!/bin/sh\nprintf synthetic\n',
        'python3': f'#!/bin/sh\nif [ "$1" = - ]; then exec cat >/dev/null; fi\nexec "{sys.executable}" "$@"\n',
    }.items():
        script = fake_bin / name
        script.write_text(body)
        script.chmod(0o700)
    helper = tmp_path / 'synthetic-helper.py'
    helper.write_text("""\
from pathlib import Path
import sys
if sys.argv[1] == 'prepare-run':
    root = Path(sys.argv[2])
    root.mkdir(exist_ok=True)
    if sys.argv[3] != '--root-only':
        (root / sys.argv[3]).mkdir()
""")
    helper.chmod(0o700)
    checksum = tmp_path / 'synthetic-helper.sha256'
    checksum.write_text(hashlib.sha256(helper.read_bytes()).hexdigest() + '\n')
    checksum.chmod(0o600)
    config = tmp_path / 'synthetic-config'
    config.write_text('synthetic fixture\n')
    state = tmp_path / 'support.json'
    state.write_text(json.dumps({
        name: [ident, 'paused' if mode == 'prepaused' and i == 1 else 'running']
        for i, (name, ident) in enumerate(zip(NAMES, IDS))
    }))
    calls = state.with_suffix('.calls')
    calls.touch()
    manifest = tmp_path / 'manifest.json'
    result = subprocess.run(
        ['/usr/bin/bash', str(BACKUP)], capture_output=True, text=True, timeout=25,
        env=dict(
            PATH=str(fake_bin) + ':/usr/bin:/bin', LC_ALL='C',
            PASTORAI_BACKUP_ROOT=str(tmp_path / 'backups'), PASTORAI_ENV_FILE=str(config),
            PASTORAI_COMPOSE_FILE=str(config), PASTORAI_BACKUP_HELPER=str(helper),
            PASTORAI_BACKUP_HELPER_SHA256=str(checksum), PASTORAI_BACKUP_LOCK_FILE=str(tmp_path / 'lock'),
            PASTORAI_BACKUP_MONITOR_MANIFEST=str(manifest),
            FAKE_SUPPORT_MODE=mode, FAKE_SUPPORT_STATE=str(state),
        ),
    )
    assert (result.returncode == 0) == (mode == 'success'), result.stderr
    assert ('BACKUP_OK ' in result.stdout) == manifest.exists() == (mode == 'success')
    assert calls.read_text().splitlines() == [
        *(f'pause {IDS[i]}' for i in attempted), *(f'unpause {IDS[i]}' for i in released),
    ]
    remaining = json.loads(state.read_text())
    assert tuple(i for i, name in enumerate(NAMES) if remaining[name][1] == 'paused') == paused_after
    assert [line for line in result.stdout.splitlines() if line.startswith('BACKUP_PAUSE_RELEASED ')] == [
        f'BACKUP_PAUSE_RELEASED name={NAMES[i]} id={IDS[i]}' for i in dict.fromkeys(released)
        if i not in paused_after
    ]
    if mode in ('replaced', 'lost-ack', 'prepaused', 'cleanup-error'):
        assert 'BACKUP_SUPPORT_CLEANUP_FAILED' in result.stderr
