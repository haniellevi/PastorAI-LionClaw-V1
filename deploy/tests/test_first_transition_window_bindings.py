"""Window host bindings with fakes only: nginx maintenance, nft bridge block and unknown writers."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import first_transition_window_bindings as wb
from initial_transition_ops import Refused
from test_first_transition_adapter_pg import database, plan  # noqa: F401  (shared fixtures)

SCOPE = 'a' * 64
UID = os.getuid()
SITE = """server {{
    server_name api.example.test;
    {include}
    location / {{ proxy_pass http://127.0.0.1:8000; }}
    listen 443 ssl;
}}
"""


class Nginx:
    """Fake nginx/systemctl/curl: a reload makes the snippet on disk the live config."""

    def __init__(self, snippet, test_rc=0):
        self.snippet, self.test_rc, self.live, self.calls = snippet, test_rc, False, []

    def __call__(self, argv, *, timeout, stdin=None):
        self.calls.append(argv)
        assert timeout > 0 and stdin is None
        if argv[0].endswith('nginx'):
            return self.test_rc, b''
        if argv[0].endswith('systemctl'):
            assert argv[1:] == ('reload', 'nginx.service')
            self.live = self.snippet.exists() and self.snippet.read_bytes() == wb.SNIPPET
            return 0, b''
        assert '--resolve' in argv and argv[-1] == 'https://api.example.test' + wb.PROBE_PATH
        if self.live:
            return 0, b'HTTP/1.1 503 Service Temporarily Unavailable\r\nX-Igreja12-Window: maintenance\r\n\r\n'
        return 0, b'HTTP/1.1 404 Not Found\r\ncontent-type: application/json\r\n\r\n'


def _nginx(tmp_path, include=True, test_rc=0):
    folder = tmp_path / 'igreja12-window'
    folder.mkdir(mode=0o755)
    config = wb.NginxConfig(nginx_binary='/usr/sbin/nginx', systemctl_binary='/usr/bin/systemctl',
                            curl_binary='/usr/bin/curl', site_path=str(tmp_path / 'site'),
                            server_name='api.example.test', include_dir=str(folder))
    (tmp_path / 'site').write_text(SITE.format(include=config.include_line if include else ''))
    os.chmod(tmp_path / 'site', 0o644)
    fake = Nginx(folder / wb.SNIPPET_NAME, test_rc)
    return wb.NginxMaintenanceIngress(config, scope=SCOPE, run=fake, sleep=lambda _: None, owner_uid=UID), fake


def test_nginx_block_and_open_round_trip_through_the_live_probe(tmp_path):
    ingress, fake = _nginx(tmp_path)
    assert (ingress.entry, ingress.scope) == ('external', SCOPE)
    assert ingress.observe(SCOPE, timeout=5) == 'open'
    assert ingress.block(SCOPE, timeout=5) is True
    snippet = ingress.snippet
    assert snippet.read_bytes() == wb.SNIPPET and stat.S_IMODE(os.lstat(snippet).st_mode) == 0o644
    assert ingress.observe(SCOPE, timeout=5) == 'blocked'
    assert ingress.block(SCOPE, timeout=5) is True  # idempotent
    assert ingress.open(SCOPE, timeout=5) is True
    assert not snippet.exists() and ingress.observe(SCOPE, timeout=5) == 'open'
    assert sum(1 for c in fake.calls if c[0].endswith('nginx')) == 3


def test_nginx_refuses_without_the_one_time_include(tmp_path):
    ingress, fake = _nginx(tmp_path, include=False)
    for call in (ingress.observe, ingress.block, ingress.open):
        with pytest.raises(Refused, match='window-nginx-include-missing'):
            call(SCOPE, timeout=5)
    assert not ingress.snippet.exists() and fake.calls == []


def test_nginx_rejected_config_is_removed_and_never_reloaded(tmp_path):
    ingress, fake = _nginx(tmp_path, test_rc=1)
    with pytest.raises(Refused, match='window-nginx-test'):
        ingress.block(SCOPE, timeout=5)
    assert not ingress.snippet.exists() and not any(c[0].endswith('systemctl') for c in fake.calls)


def test_nginx_partial_or_foreign_states_refuse(tmp_path):
    ingress, fake = _nginx(tmp_path)
    ingress.snippet.write_bytes(wb.SNIPPET)  # on disk but not reloaded: neither blocked nor open
    os.chmod(ingress.snippet, 0o644)
    with pytest.raises(Refused, match='window-nginx-partial'):
        ingress.observe(SCOPE, timeout=5)
    ingress.snippet.write_bytes(b'return 200;\n')
    with pytest.raises(Refused, match='window-nginx-snippet-foreign'):
        ingress.observe(SCOPE, timeout=5)
    ingress.snippet.unlink()
    (ingress.snippet.parent / 'other.conf').write_text('')
    with pytest.raises(Refused, match='window-nginx-include-foreign'):
        ingress.block(SCOPE, timeout=5)
    with pytest.raises(Refused, match='window-binding-scope'):
        ingress.observe('b' * 64, timeout=5)


class Nft:
    """Fake nft holding one ruleset; lists it in the exact JSON shape of nft 1.0.9."""

    def __init__(self, config):
        self.config, self.table, self.calls = config, None, []

    def __call__(self, argv, *, timeout, stdin=None):
        self.calls.append(argv)
        meta = {'metainfo': {'version': '1.0.9', 'json_schema_version': 1}}
        if argv[1:] == ('-j', 'list', 'tables', 'bridge'):
            tables = [{'table': {'family': 'bridge', 'name': self.config.table, 'handle': 3}}] if self.table else []
            return 0, json.dumps({'nftables': [meta, *tables]}).encode()
        if argv[1:] == ('-j', 'list', 'table', 'bridge', self.config.table):
            items = [{k: {**v, 'handle': 7}} for item in self.table for k, v in item.items()]
            return 0, json.dumps({'nftables': [meta, *items]}).encode()
        if argv[1:] == ('-f', '-'):
            assert stdin == self.config.ruleset() and self.table is None
            self.table = self.config.expected()
            return 0, b''
        assert argv[1:] == ('delete', 'table', 'bridge', self.config.table)
        self.table = None
        return 0, b''


def test_bridge_block_is_one_exact_table_and_open_removes_it():
    config = wb.BridgeConfig(nft_binary='/usr/sbin/nft', bridge='br-3f9e89014eac')
    fake = Nft(config)
    ingress = wb.BridgePortIngress(config, scope=SCOPE, run=fake)
    assert (ingress.entry, ingress.scope) == ('evolution-backend', SCOPE)
    assert ingress.observe(SCOPE, timeout=5) == 'open'
    assert ingress.block(SCOPE, timeout=5) is True and ingress.observe(SCOPE, timeout=5) == 'blocked'
    assert ingress.block(SCOPE, timeout=5) is True
    assert sum(1 for c in fake.calls if c[1:] == ('-f', '-')) == 1
    assert ingress.open(SCOPE, timeout=5) is True and ingress.observe(SCOPE, timeout=5) == 'open'
    fake.table = [*config.expected()[:2]]  # chain without the drop rule
    with pytest.raises(Refused, match='window-bridge-foreign'):
        ingress.observe(SCOPE, timeout=5)


def test_bridge_config_rejects_other_names():
    for bridge in ('docker0', 'br-3f9e', 'br-3f9e89014eac;'):
        with pytest.raises(Refused, match='window-bridge-config'):
            wb.BridgeConfig(nft_binary='/usr/sbin/nft', bridge=bridge).validated()


def test_bridge_rule_blocks_only_the_backend_port_between_bridge_ports(tmp_path):
    """Real nft + kernel bridge inside an unprivileged user/net namespace (no br_netfilter)."""
    unshare, nft = shutil.which('unshare'), shutil.which('nft') or '/usr/sbin/nft'
    if not unshare or not os.path.exists(nft) or subprocess.run(
            [unshare, '-rn', nft, 'list', 'tables'], capture_output=True, check=False).returncode != 0:
        pytest.skip('requires unprivileged user namespaces and nft')
    script = Path(__file__).with_name('first_transition_bridge_netns.py')
    result = subprocess.run([unshare, '-rn', sys.executable, '-I', str(script), nft], capture_output=True,
                            text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {
        'before': [True, True], 'blocked': [False, True], 'reopened': [True, True]}


# --- unknown writers ---

def _tcp(rows):
    """/proc/net/tcp text for (ipv4, port, state, inode) rows."""
    lines = ['  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode']
    for n, (ip, port, state, inode) in enumerate(rows):
        remote = ''.join(f'{int(b):02X}' for b in reversed(ip.split('.'))) + f':{port:04X}'
        lines.append(f'{n:4}: 0100007F:9C40 {remote} {state} 00000000:00000000 00:00000000 00000000 0 0 {inode}')
    return '\n'.join(lines) + '\n'


class Proc:
    """Synthetic /proc: namespaces, tcp tables, process tree and socket fds."""

    def __init__(self, root):
        self.root = root

    def process(self, pid, ppid, netns, tcp='', sockets=()):
        base = self.root / str(pid)
        (base / 'ns').mkdir(parents=True)
        (base / 'net').mkdir()
        (base / 'fd').mkdir()
        target = self.root / 'netns' / str(netns)
        target.parent.mkdir(exist_ok=True)
        target.touch(exist_ok=True)
        os.symlink(target, base / 'ns' / 'net')
        (base / 'stat').write_text(f'{pid} (proc x) S {ppid} 0 0\n')
        (base / 'net' / 'tcp').write_text(tcp or _tcp([]))
        for n, inode in enumerate(sockets):
            os.symlink(f'socket:[{inode}]', base / 'fd' / str(n))


class Docker:
    def __init__(self, containers):
        self.containers = containers  # id -> pid

    def __call__(self, argv, *, timeout, stdin=None):
        assert argv[1:5] == ('--config', '/srv/cli', '--host', 'unix:///var/run/docker.sock')
        if argv[5:] == ('ps', '-q', '--no-trunc'):
            return 0, '\n'.join(self.containers).encode()
        assert argv[5:8] == ('inspect', '--format', '{{json .Id}} {{json .State.Pid}}')
        return 0, '\n'.join(f'"{i}" {self.containers[i]}' for i in argv[8:]).encode()


class Cursor:
    def __init__(self, active, stats=True, readonly=('devin_readonly',)):
        self.active, self.stats, self.readonly, self.result, self.executed = active, stats, readonly, [], []

    def execute(self, query, params=None):
        self.executed.append(query)
        if query == wb.Q_STATS:
            self.result = [(self.stats,)]
        elif query == wb.Q_READONLY:
            self.result = [(r,) for r in params[0] if r in self.readonly]
        elif query == wb.Q_ACTIVE:
            self.result = list(self.active.items())
        else:
            self.result = [('',)]

    def fetchall(self):
        return self.result


class Conn:
    def __init__(self, cursor):
        self.c, self.autocommit, self.closed = cursor, False, False

    def cursor(self):
        return self.c

    def close(self):
        self.closed = True


DB = '10.20.30.40'
LEGACY, FOREIGN = '1' * 64, '2' * 64


def _writers(tmp_path, active, containers, *, host_rows=(), own_sockets=(), stats=True, readonly=('devin_readonly',)):
    proc = Proc(tmp_path / 'proc')
    proc.process(1, 0, 'host', _tcp(host_rows))
    proc.process(500, 1, 'host')  # this observer
    proc.process(501, 500, 'host', sockets=own_sockets)  # its migration child
    pids = {}
    for n, (ident, rows) in enumerate(containers.items()):
        pid = 1000 + n
        proc.process(pid, 1, ident, _tcp(rows))
        pids[ident] = pid
    cursor = Cursor(active, stats, readonly)
    binding = wb.UnknownWriters(
        scope=SCOPE, connect=lambda timeout: Conn(cursor), endpoint=(frozenset({wb.ipaddress.ip_address(DB)}), 5432),
        declared_containers=(LEGACY,), docker=('/usr/bin/docker', 'unix:///var/run/docker.sock', '/srv/cli'),
        readonly_roles=('devin_readonly',), proc=str(tmp_path / 'proc'), run=Docker(pids), own_pid=500)
    return binding, cursor


def test_writers_zero_when_active_sessions_match_declared_connections(tmp_path):
    binding, cursor = _writers(tmp_path, {'postgres': 2, 'supabase_admin': 3, 'devin_readonly': 1},
                               {LEGACY: [(DB, 5432, '01', 11), (DB, 5432, '01', 12), (DB, 6543, '01', 13)]})
    assert binding.observe(SCOPE, timeout=5) == 0
    assert 'BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY' in cursor.executed
    assert cursor.executed[-1] == 'ROLLBACK'


def test_writers_count_foreign_containers_host_processes_and_unexplained_sessions(tmp_path):
    binding, _ = _writers(tmp_path, {'postgres': 1},
                          {LEGACY: [(DB, 5432, '01', 11)], FOREIGN: [(DB, 5432, '01', 21), (DB, 5432, '06', 22)]},
                          host_rows=[(DB, 5432, '01', 31), (DB, 5432, '01', 32)], own_sockets=(31,))
    # foreign container: 1 established (TIME_WAIT ignored); host socket 32 not ours: 1.
    assert binding.observe(SCOPE, timeout=5) == 2
    binding, _ = _writers(tmp_path / 'b', {'postgres': 3, 'authenticator': 1}, {LEGACY: [(DB, 5432, '01', 11)]})
    # after containment budget is 1 legacy connection: 4 active non-internal sessions -> 3 unknown.
    assert binding.observe(SCOPE, timeout=5) == 3


def test_writers_refuse_without_stats_privilege_and_unverified_readonly_counts(tmp_path):
    binding, _ = _writers(tmp_path, {}, {LEGACY: []}, stats=False)
    with pytest.raises(Refused, match='window-writers-stats-privilege'):
        binding.observe(SCOPE, timeout=5)
    binding, _ = _writers(tmp_path / 'b', {'devin_readonly': 1}, {LEGACY: []}, readonly=())
    assert binding.observe(SCOPE, timeout=5) == 1


def test_writers_parse_real_ipv6_mapped_rows():
    text = ('  sl  local_address                         remote_address                        st ... inode\n'
            '   0: 0000000000000000FFFF00000100007F:9C40 0000000000000000FFFF0000281E140A:1538 01 '
            '00000000:00000000 00:00000000 00000000 0 0 77 1\n')
    assert wb._tcp_rows(text) == [(wb.ipaddress.ip_address(DB), 5432, 77)]


def test_writer_queries_run_on_real_postgres(database):  # noqa: F811
    """Opt-in (owned synthetic first_transition_test): the observer itself is never counted."""
    import psycopg2
    url, _ = database
    role = 'ft_window_readonly_probe'
    admin = psycopg2.connect(url)
    admin.autocommit = True
    cur = admin.cursor()
    cur.execute(f'DROP ROLE IF EXISTS {role}')
    cur.execute(f'CREATE ROLE {role} NOLOGIN')
    busy = psycopg2.connect(url)
    try:
        busy.cursor().execute('SELECT txid_current()')  # an open transaction holding an xid
        binding = wb.UnknownWriters(
            scope=SCOPE, connect=lambda timeout: psycopg2.connect(url, connect_timeout=5),
            endpoint=(frozenset({wb.ipaddress.ip_address('127.0.0.1')}), 1),
            declared_containers=(LEGACY,), docker=('/usr/bin/docker', 'unix:///var/run/docker.sock', '/srv/cli'),
            readonly_roles=(role, 'postgres'))
        active = binding._database_side(wb._deadline(10))
        assert active == 1  # the busy session; postgres is superuser, so never verified read-only
        cur.execute(wb.Q_READONLY, ([role, 'postgres'],))
        assert cur.fetchall() == [(role,)]
    finally:
        busy.close()
        cur.execute(f'DROP ROLE {role}')
        admin.close()
