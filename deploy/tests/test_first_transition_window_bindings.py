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
    location / {{
        proxy_pass http://127.0.0.1:8000;
    }}
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
            if argv[1:] == ('-T',):
                site = self.snippet.parent.parent / 'site'
                return 0, ('# configuration file ' + str(site) + ':\n' + site.read_text()).encode()
            assert argv[1:] == ('-t', '-q')
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
    assert sum(1 for c in fake.calls if c[1:] == ('-t', '-q')) == 3


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


@pytest.mark.parametrize('fault', [
    'probe-only', 'late-include', 'inline-server', 'extra-server', 'extra-include',
    'grpc', 'uwsgi', 'fastcgi', 'scgi', 'memcached', 'multi-command', 'inline-location',
    'unbalanced-open', 'unbalanced-close', 'if', 'rewrite', 'return', 'unknown', 'unicode-newline',
])
def test_nginx_non_nominal_topology_refuses_before_any_external_io(tmp_path, fault):
    ingress, fake = _nginx(tmp_path)
    path = Path(ingress.config.site_path)
    text = path.read_text()
    include = '    ' + ingress.config.include_line + '\n'
    if fault == 'probe-only':
        text = text.replace(include, '').replace('    location / {',
            '    location = ' + wb.PROBE_PATH + ' {\n' + include + '    }\n    location / {')
    elif fault == 'late-include':
        text = text.replace(include, '').replace('    listen', include + '    listen')
    elif fault == 'inline-server':
        text += 'server { listen 443 ssl; }\n'
    elif fault == 'extra-server':
        text += 'server {\n    listen 443 ssl;\n}\n'
    elif fault == 'extra-include':
        text = text.replace(include, include + '    include /synthetic/other.conf;\n')
    elif fault in ('grpc', 'uwsgi', 'fastcgi', 'scgi', 'memcached'):
        text = text.replace('        proxy_pass', '        ' + fault + '_pass 127.0.0.1:9000;\n        proxy_pass')
    elif fault == 'multi-command':
        text = text.replace('    listen 443 ssl;', '    listen 443 ssl; return 200;')
    elif fault == 'inline-location':
        text = text.replace('    location / {\n        proxy_pass http://127.0.0.1:8000;\n    }',
                            '    location / { proxy_pass http://127.0.0.1:8000; }')
    elif fault == 'unbalanced-open':
        text += '{\n'
    elif fault == 'unbalanced-close':
        text += '}\n'
    elif fault == 'unicode-newline':
        text = '# comment\u2028' + text.replace('\n', '\u2028')
    else:
        line = {'if': 'if ($request_method = GET) {', 'rewrite': 'rewrite ^ /other;',
                'return': 'return 200;', 'unknown': 'access_by_lua_block {'}[fault]
        text = text.replace(include, include + '    ' + line + '\n')
    path.write_text(text)
    for operation in (ingress.verify_topology, lambda **kw: ingress.observe(SCOPE, **kw),
                      lambda **kw: ingress.block(SCOPE, **kw), lambda **kw: ingress.open(SCOPE, **kw)):
        with pytest.raises(Refused, match='^window-nginx-topology$'):
            operation(timeout=5)
    assert fake.calls == [] and not ingress.snippet.exists()


@pytest.mark.parametrize('operation', ['observe', 'block', 'open'])
def test_nginx_topology_is_fresh_after_readiness(tmp_path, operation):
    ingress, fake = _nginx(tmp_path)
    ingress.verify_topology(timeout=5)
    # An existing maintenance snippet must not be removed or reloaded after drift either.
    ingress.snippet.write_bytes(wb.SNIPPET)
    ingress.snippet.chmod(0o644)
    fake.live = True
    path = Path(ingress.config.site_path)
    path.write_text(path.read_text().replace('    location / {', '    include /synthetic/drift.conf;\n    location / {'))
    before = list(fake.calls)
    with pytest.raises(Refused, match='^window-nginx-topology$'):
        getattr(ingress, operation)(SCOPE, timeout=5)
    assert fake.calls == before and ingress.snippet.read_bytes() == wb.SNIPPET and fake.live


def test_nginx_nominal_comments_and_blank_lines_pass(tmp_path):
    ingress, fake = _nginx(tmp_path)
    path = Path(ingress.config.site_path)
    path.write_text('# synthetic server { return 200; }\n\n' + path.read_text())
    ingress.verify_topology(timeout=5)
    assert fake.calls == [(ingress.config.nginx_binary, '-T')]


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


def test_window_preflight_metadata_queries_on_owned_postgres(database):  # noqa: F811
    """Opt-in for the coordinator's PG17 harness, with the same owned disposable fixture."""
    from first_transition_database import psycopg2_connector
    from first_transition_window import _source_version
    url, _ = database
    assert _source_version(psycopg2_connector(lambda: url), 'postgres') == 17


@pytest.mark.parametrize('names', ['alias.example.test api.example.test', 'api.example.test alias.example.test',
                                 'API.EXAMPLE.TEST alias.example.test', '"api.example.test" alias.example.test',
                                 "'API.EXAMPLE.TEST' alias.example.test"])
def test_effective_nginx_duplicate_server_alias_refuses(tmp_path, names):
    ingress, fake = _nginx(tmp_path)
    def run(argv, **kwargs):
        rc, data = fake(argv, **kwargs)
        if argv[1:] == ('-T',):
            data += ('# configuration file /other/site:\nserver {\nserver_name ' + names + ';\n}\n').encode()
        return rc, data
    ingress._run_command = run
    with pytest.raises(wb.Refused, match='^window-nginx-topology$'):
        ingress.verify_topology()
    assert not ingress.snippet.exists()


TLS_OPTIONS = '''ssl_session_cache shared:le_nginx_SSL:10m;
ssl_session_timeout 1440m;
ssl_session_tickets off;
ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers off;
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
'''


class DualNginx(Nginx):
    def __init__(self, snippet):
        super().__init__(snippet)
        self.http_response = None
        self.https_response = None
        self.extra_effective = ''
        self.options = TLS_OPTIONS

    def __call__(self, argv, **kwargs):
        if argv[0].endswith('curl') and argv[-1].startswith('http://'):
            self.calls.append(argv)
            return 0, self.http_response or (
                b'HTTP/1.1 301 Moved Permanently\r\nLocation: https://api.example.test'
                + wb.PROBE_PATH.encode() + b'\r\n\r\n')
        if argv[0].endswith('curl') and self.https_response is not None:
            self.calls.append(argv)
            return 0, self.https_response
        rc, data = super().__call__(argv, **kwargs)
        if argv[1:] == ('-T',):
            site = self.snippet.parent.parent / 'site'
            data = ('# configuration file /synthetic/nginx.conf:\ninclude ' + str(site) + ';\n').encode() + data
            data += ('# configuration file /etc/letsencrypt/options-ssl-nginx.conf:\n' + self.options
                     + self.extra_effective).encode()
        return rc, data


def _dual_nginx(tmp_path, certbot=False, http_first=False):
    ingress, _ = _nginx(tmp_path)
    name = ingress.config.server_name
    https = SITE.format(include=ingress.config.include_line).replace('    listen 443 ssl;', '''    listen [::]:443 ssl ipv6only=on; # managed by Certbot
    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/''' + name + '''/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/''' + name + '''/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;''').replace(
        '        proxy_pass', '        proxy_set_header Host $host;\n        proxy_set_header X-Forwarded-Proto $scheme;\n        proxy_pass')
    redirect = ('    if ($host = ' + name + ') {\n        return 301 https://$host$request_uri;\n    }\n'
                if certbot else '')
    http = ('server {\n' + redirect + '    listen 80;\n    listen [::]:80;\n    server_name ' + name + ';\n'
            + ('    return 404;\n' if certbot else '    return 301 https://' + name + '$request_uri;\n') + '}\n')
    Path(ingress.config.site_path).write_text(http + https if http_first else https + http)
    fake = DualNginx(ingress.snippet)
    ingress._run_command = fake
    return ingress, fake


@pytest.mark.parametrize('certbot', [False, True])
@pytest.mark.parametrize('http_first', [False, True])
def test_nginx_dual_protocol_round_trip_probes_each_family(tmp_path, certbot, http_first):
    ingress, fake = _dual_nginx(tmp_path, certbot, http_first)
    assert ingress.observe(SCOPE, timeout=5) == 'open'
    assert ingress.block(SCOPE, timeout=5) is True
    assert ingress.observe(SCOPE, timeout=5) == 'blocked'
    assert ingress.open(SCOPE, timeout=5) is True
    calls = [c for c in fake.calls if c[0].endswith('curl')]
    for scheme, port in [('http', 80), ('https', 443)]:
        for address in ['127.0.0.1', '[::1]']:
            assert any(c[-1] == scheme + '://api.example.test' + wb.PROBE_PATH
                       and 'api.example.test:' + str(port) + ':' + address in c for c in calls)
    assert all(c[1] == '-q' and '--noproxy' in c and '-L' not in c for c in calls)


@pytest.mark.parametrize('fault', ['http-proxy', 'foreign-redirect', 'unguarded-host', 'late-404',
                                  'third-server', 'https-return', 'ssl-routing', 'duplicate-effective'])
def test_nginx_dual_protocol_refuses_bypass_before_reload(tmp_path, fault):
    ingress, fake = _dual_nginx(tmp_path, certbot=True)
    path = Path(ingress.config.site_path)
    text = path.read_text()
    if fault == 'http-proxy':
        text = text.replace('    return 404;', '    location / {\n        proxy_pass http://127.0.0.1:8000;\n    }')
    elif fault == 'foreign-redirect':
        text = text.replace('https://$host$request_uri', 'https://foreign.example.test$request_uri')
    elif fault == 'unguarded-host':
        text = text.replace('    if ($host = api.example.test) {\n        return 301 https://$host$request_uri;\n    }',
                            '    return 301 https://$host$request_uri;')
    elif fault == 'late-404':
        text = text.replace('    if ($host', '    return 404;\n    if ($host').replace('    return 404;\n}', '}')
    elif fault == 'third-server':
        text += SITE.format(include='')
    elif fault == 'https-return':
        text = text.replace('    location / {', '    return 200;\n    location / {', 1)
    elif fault == 'ssl-routing':
        fake.options += 'return 200;\n'
    elif fault == 'duplicate-effective':
        fake.extra_effective = '# configuration file /other/site:\nserver {\nserver_name api.example.test;\n}\n'
    path.write_text(text)
    with pytest.raises(Refused, match='^window-nginx-topology$'):
        ingress.block(SCOPE, timeout=5)
    assert not ingress.snippet.exists() and not any(c[0].endswith('systemctl') for c in fake.calls)


@pytest.mark.parametrize('response', [
    b'HTTP/1.1 200 OK\r\n\r\n',
    b'HTTP/1.1 301 Moved\r\nLocation: https://foreign.example.test/\r\n\r\n',
    b'HTTP/1.1 301 Moved\r\nLocation: https://api.example.test/igreja12-window-probe\r\nLocation: https://api.example.test/igreja12-window-probe\r\n\r\n',
])
def test_nginx_http_probe_must_redirect_to_exact_https_path(tmp_path, response):
    ingress, fake = _dual_nginx(tmp_path)
    fake.http_response = response
    with pytest.raises(Refused, match='^window-nginx-(probe|partial)$'):
        ingress.observe(SCOPE, timeout=5)


def test_nginx_duplicate_or_foreign_maintenance_marker_refuses(tmp_path):
    ingress, fake = _dual_nginx(tmp_path)
    for marker in [b'other', b'maintenance\r\nX-Igreja12-Window: maintenance']:
        fake.https_response = b'HTTP/1.1 503 Unavailable\r\nX-Igreja12-Window: ' + marker + b'\r\n\r\n'
        with pytest.raises(Refused, match='^window-nginx-probe$'):
            ingress.observe(SCOPE, timeout=5)


@pytest.mark.parametrize('fault', [None, 'foreign-target', 'link-drift', 'duplicate-reference'])
def test_nginx_enabled_alias_is_one_nominal_stable_link(tmp_path, monkeypatch, fault):
    from dataclasses import replace
    from types import SimpleNamespace
    ingress, _ = _dual_nginx(tmp_path)
    text = Path(ingress.config.site_path).read_text()
    ingress.config = replace(ingress.config, site_path='/etc/nginx/sites-available/api')
    ingress._include_present = lambda: text
    enabled = '/etc/nginx/sites-enabled/api'
    effective = ('# configuration file /etc/nginx/nginx.conf:\ninclude /etc/nginx/sites-enabled/*;\n'
                 + '# configuration file ' + enabled + ':\n' + text
                 + '# configuration file /etc/letsencrypt/options-ssl-nginx.conf:\n' + TLS_OPTIONS)
    if fault == 'duplicate-reference':
        effective = 'include ' + enabled + ';\n' + effective
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return 0, effective.encode()
    ingress._run_command = run
    alias_reads = 0
    def lstat(path):
        nonlocal alias_reads
        if str(path) != enabled:
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=UID)
        alias_reads += 1
        return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=UID, st_gid=UID,
                               st_dev=1, st_ino=123, st_nlink=1, st_mtime_ns=1,
                               st_ctime_ns=alias_reads if fault == 'link-drift' else 1)
    with monkeypatch.context() as patch:
        patch.setattr(wb.os, 'lstat', lstat)
        patch.setattr(wb.os, 'readlink', lambda _: '../sites-available/' + ('other' if fault == 'foreign-target' else 'api'))
        if fault is None:
            assert ingress.verify_topology()['http_redirect'] is True
        else:
            with pytest.raises(Refused, match='^window-nginx-topology$'):
                ingress.verify_topology()
    assert all(c == ('/usr/sbin/nginx', '-T') for c in calls)
    assert not ingress.snippet.exists()


@pytest.mark.parametrize('operation', ['block', 'open'])
def test_nginx_reload_waits_for_old_workers_but_not_topology_errors(tmp_path, operation):
    ingress, fake = _dual_nginx(tmp_path)
    if operation == 'open':
        ingress.block(SCOPE, timeout=5)
    original_run, sleeps = fake.__call__, []
    target = operation == 'block'
    def run(argv, **kwargs):
        old = fake.live
        result = original_run(argv, **kwargs)
        if argv[0].endswith('systemctl'):
            fake.live = old  # reload returns before old workers leave
        return result
    def sleep(_):
        sleeps.append(True)
        if len(sleeps) == 2:
            fake.live = target
    ingress._run_command, ingress._sleep = run, sleep
    assert getattr(ingress, operation)(SCOPE, timeout=5) is True
    assert len(sleeps) == 2 and fake.live == target
    def refuse(**kwargs):
        raise Refused('window-nginx-topology')
    ingress.verify_topology = refuse
    with pytest.raises(Refused, match='^window-nginx-topology$'):
        ingress._until('open', wb._deadline(5))
    assert len(sleeps) == 2


def test_nginx_certbot_cipher_quotes_and_hidden_routing_refuse(tmp_path):
    ingress, fake = _dual_nginx(tmp_path, certbot=True)
    fake.options = fake.options.replace('ssl_ciphers ', 'ssl_ciphers "').replace('SHA256;','SHA256";')
    assert ingress.observe(SCOPE, timeout=5) == 'open'
    fake.options += 'return 200;\n'
    with pytest.raises(Refused, match='^window-nginx-topology$'):
        ingress.verify_topology()


@pytest.mark.parametrize('fault', ['duplicate-wrapper', 'overlapping-wrapper', 'cycle'])
def test_nginx_indirect_include_multiplicity_and_cycles_refuse(tmp_path, fault):
    ingress, fake = _dual_nginx(tmp_path)
    original = fake.__call__
    def run(argv, **kwargs):
        rc, data = original(argv, **kwargs)
        if argv[1:] == ('-T',):
            site = ingress.config.site_path
            refs = ('include /wrapped/api.conf;\n' * 2 if fault == 'duplicate-wrapper'
                    else 'include /wrapped/*.conf;\ninclude /wrapped/api.conf;\n' if fault == 'overlapping-wrapper'
                    else 'include /wrapped/api.conf;\n')
            data = data.replace(('include ' + site + ';\n').encode(), refs.encode(), 1)
            wrapper = ('# configuration file /wrapped/api.conf:\ninclude ' + site + ';\n'
                       + ('include /synthetic/nginx.conf;\n' if fault == 'cycle' else ''))
            data += wrapper.encode()
        return rc, data
    ingress._run_command = run
    with pytest.raises(Refused, match='^window-nginx-topology$'):
        ingress.block(SCOPE, timeout=5)
    assert not ingress.snippet.exists() and not any(c[0].endswith('systemctl') for c in fake.calls)


def test_nginx_transitional_polling_keeps_its_deadline(tmp_path):
    ingress, _ = _dual_nginx(tmp_path)
    def transitional(scope, *, timeout):
        raise Refused('window-nginx-partial')
    ingress.observe = transitional
    with pytest.raises(TimeoutError, match='^window-binding-timeout$'):
        ingress._until('blocked', wb._deadline(0.01))



def test_nginx_unquoted_hash_cannot_hide_a_second_include(tmp_path):
    ingress, fake = _dual_nginx(tmp_path)
    original = fake.__call__
    def run(argv, **kwargs):
        rc, data = original(argv, **kwargs)
        if argv[1:] == ('-T',):
            root = b'# configuration file /synthetic/nginx.conf:\n'
            hidden = ('error_log /synthetic/name#part; include ' + ingress.config.site_path + ';\n').encode()
            data = data.replace(root, root + hidden, 1)
        return rc, data
    ingress._run_command = run
    with pytest.raises(Refused, match='^window-nginx-topology$'):
        ingress.block(SCOPE, timeout=5)
    assert not ingress.snippet.exists() and not any(c[0].endswith('systemctl') for c in fake.calls)
