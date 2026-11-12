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
# Production API site shape (certbot TLS, IPv6, proxy headers, port-80 redirect), sanitized:
# public name and include folder are synthetic; paths are certbot's defaults, no secrets.
CERTBOT_SITE = """server {
    server_name api.example.test;
    INCLUDE

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    listen [::]:443 ssl ipv6only=on; # managed by Certbot
    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/api.example.test/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/api.example.test/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot

}
server {
    if ($host = api.example.test) {
        return 301 https://$host$request_uri;
    } # managed by Certbot


    listen 80;
    listen [::]:80;
    server_name api.example.test;
    return 404; # managed by Certbot


}"""


class Nginx:
    """Fake nginx/systemctl/curl: a reload makes the snippet on disk the live config."""

    def __init__(self, snippet, test_rc=0):
        self.snippet, self.test_rc, self.live, self.calls = snippet, test_rc, False, []
        self.loaded = None  # path nginx -T prints (sites-enabled symlink), default the site itself
        self.extra = ''  # other files of the shared nginx, as ``nginx -T`` prints them

    def __call__(self, argv, *, timeout, stdin=None):
        self.calls.append(argv)
        assert timeout > 0 and stdin is None
        if argv[0].endswith('nginx'):
            if argv[1:] == ('-T',):
                site = self.snippet.parent.parent / 'site'
                return 0, ('# configuration file ' + str(self.loaded or site) + ':\n' + site.read_text()
                           + self.extra).encode()
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


def _nginx(tmp_path, include=True, test_rc=0, site=None, enabled=None):
    folder = tmp_path / 'igreja12-window'
    folder.mkdir(mode=0o755)
    config = wb.NginxConfig(nginx_binary='/usr/sbin/nginx', systemctl_binary='/usr/bin/systemctl',
                            curl_binary='/usr/bin/curl', site_path=str(tmp_path / 'site'),
                            server_name='api.example.test', include_dir=str(folder), enabled_path=enabled)
    line = config.include_line if include else ''
    (tmp_path / 'site').write_text(SITE.format(include=line) if site is None else site.replace('INCLUDE', line))
    os.chmod(tmp_path / 'site', 0o644)
    fake = Nginx(folder / wb.SNIPPET_NAME, test_rc)
    fake.loaded = enabled
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


def test_nginx_certbot_production_shape_round_trips(tmp_path):
    ingress, fake = _nginx(tmp_path, site=CERTBOT_SITE)
    ingress.verify_topology(timeout=5)
    assert ingress.observe(SCOPE, timeout=5) == 'open'
    assert ingress.block(SCOPE, timeout=5) is True
    assert ingress.observe(SCOPE, timeout=5) == 'blocked'
    assert ingress.open(SCOPE, timeout=5) is True
    assert ingress.observe(SCOPE, timeout=5) == 'open'


def test_nginx_certbot_production_shape_without_include_refuses(tmp_path):
    ingress, fake = _nginx(tmp_path, include=False, site=CERTBOT_SITE)
    with pytest.raises(Refused, match='^window-nginx-include-missing$'):
        ingress.verify_topology(timeout=5)
    assert fake.calls == []


OPTIONS = ('# configuration file /etc/letsencrypt/options-ssl-nginx.conf:\n# synthetic certbot options\n'
           'ssl_session_cache shared:le_nginx_SSL:10m;\nssl_protocols TLSv1.2 TLSv1.3;\n')
# Other systems of the same VPS, each with its own server block and certificate.
NEIGHBOURS = ('# configuration file /etc/nginx/sites-enabled/other-a:\nserver {\n    listen 443 ssl;\n'
              '    server_name a.example.test;\n    ssl_certificate /srv/a/fullchain.pem;\n'
              '    location / { proxy_pass http://127.0.0.1:8087; }\n}\n'
              '# configuration file /etc/nginx/sites-enabled/other-b:\nserver {\n    listen 80;\n'
              '    server_name b.example.test;\n    include /etc/nginx/proxy_params;\n    return 404;\n}\n')


def _shared(tmp_path, extra=OPTIONS + NEIGHBOURS):
    ingress, fake = _nginx(tmp_path, site=CERTBOT_SITE)
    fake.extra = '\n' + extra
    return ingress, fake


def test_nginx_certbot_site_beside_other_systems_round_trips_touching_only_its_snippet(tmp_path):
    ingress, fake = _shared(tmp_path)
    assert ingress.observe(SCOPE, timeout=5) == 'open'
    assert ingress.block(SCOPE, timeout=5) is True and ingress.observe(SCOPE, timeout=5) == 'blocked'
    assert ingress.open(SCOPE, timeout=5) is True and ingress.observe(SCOPE, timeout=5) == 'open'
    # The only host-wide effect is the graceful reload; no other file is ever written.
    effects = {c[1:] for c in fake.calls if not c[0].endswith('curl')}
    assert effects == {('-T',), ('-t', '-q'), ('reload', 'nginx.service')}
    assert sorted(os.listdir(tmp_path)) == ['igreja12-window', 'site']


@pytest.mark.parametrize('extra', [
    # another system includes the maintenance folder: its site would also answer 503
    NEIGHBOURS.replace('    return 404;', '    include {dir}/*.conf;\n    return 404;'),
    # a broader glob elsewhere could load the snippet too
    NEIGHBOURS.replace('/etc/nginx/proxy_params', '{dir}/*'),
    NEIGHBOURS.replace('/etc/nginx/proxy_params', '{dir}/maintenance.conf'),
    # quoted or non-normalized forms nginx still resolves to the maintenance folder
    NEIGHBOURS.replace('/etc/nginx/proxy_params', '"{dir}/*.conf"'),
    NEIGHBOURS.replace('/etc/nginx/proxy_params', "'{dir}/*.conf'"),
    NEIGHBOURS.replace('/etc/nginx/proxy_params', '{dir}/../igreja12-window//./*.conf'),
    NEIGHBOURS.replace('/etc/nginx/proxy_params', '{link}/*.conf'),
    # forms that cannot be judged statically refuse
    NEIGHBOURS.replace('/etc/nginx/proxy_params', '/etc/nginx/$site/*.conf'),
    NEIGHBOURS.replace('/etc/nginx/proxy_params', '"/etc/nginx/a\\\\ b/*.conf"'),
])
def test_nginx_snippet_reachable_from_another_system_refuses_before_any_effect(tmp_path, extra):
    ingress, fake = _shared(tmp_path)
    (tmp_path / 'alias').symlink_to(ingress.config.include_dir)  # another name for the same folder
    fake.extra = '\n' + OPTIONS + extra.replace('{dir}', ingress.config.include_dir).replace(
        '{link}', str(tmp_path / 'alias'))
    for operation in ('observe', 'block', 'open'):
        with pytest.raises(Refused, match='^window-nginx-shared$'):
            getattr(ingress, operation)(SCOPE, timeout=5)
    assert all(c[1:] == ('-T',) for c in fake.calls) and not ingress.snippet.exists()


def test_nginx_shared_certbot_options_with_routing_refuses(tmp_path):
    ingress, fake = _shared(tmp_path, OPTIONS + 'return 200;\n' + NEIGHBOURS)
    with pytest.raises(Refused, match='^window-nginx-topology$'):
        ingress.block(SCOPE, timeout=5)
    assert not ingress.snippet.exists() and not any(c[0].endswith('systemctl') for c in fake.calls)


CERTBOT_FAULTS = {
    'second-proxy-pass': ('        proxy_http_version', '        proxy_pass http://127.0.0.1:9000;\n        proxy_http_version'),
    'other-upstream': ('proxy_pass http://127.0.0.1:8000;', 'proxy_pass http://127.0.0.1:9000;'),
    'other-location': ('    listen 443', '    location /admin {\n        proxy_pass http://127.0.0.1:8000;\n    }\n    listen 443'),
    'foreign-include': ('    ssl_dhparam', '    include /synthetic/other.conf;\n    ssl_dhparam'),
    'foreign-include-certbot': ('include /etc/letsencrypt/options-ssl-nginx.conf;', 'include /etc/letsencrypt/other.conf;'),
    'include-after-location': ('    INCLUDE\n', '', '    }\n\n    listen [::]:443', '    }\n    INCLUDE\n    listen [::]:443'),
    'duplicate-header': ('        proxy_set_header Host $host;', '        proxy_set_header Host $host;\n        proxy_set_header Host $host;'),
    'spoofed-header': ('$proxy_add_x_forwarded_for', '$http_x_forwarded_for'),
    'extra-location-line': ('        proxy_http_version 1.1;', '        proxy_http_version 1.1;\n        add_header X-Test 1;'),
    'other-certificate': ('live/api.example.test/fullchain', 'live/other.example.test/fullchain'),
    'certificate-without-key': ('    ssl_certificate_key /etc/letsencrypt/live/api.example.test/privkey.pem; # managed by Certbot\n', ''),
    'certbot-comment-hides-directive': ('    listen 443 ssl; # managed by Certbot', '    listen 443 ssl; # managed by Certbot; return 200;'),
    'certbot-comment-on-foreign-line': ('    ssl_dhparam', '    return 200; # managed by Certbot\n    ssl_dhparam'),
    'trailing-comment': ('    listen 443 ssl; # managed by Certbot', '    listen 443 ssl; # other'),
    'redirect-other-host': ('return 301 https://$host$request_uri;', 'return 301 https://evil.example.test$request_uri;'),
    'redirect-if-other-name': ('if ($host = api.example.test)', 'if ($host = other.example.test)'),
    'redirect-proxy': ('    return 404;', '    location / {\n        proxy_pass http://127.0.0.1:8000;\n    }\n    return 404;'),
    'redirect-include': ('    listen 80;', '    include /synthetic/other.conf;\n    listen 80;'),
    'redirect-other-name': ('    listen [::]:80;\n    server_name api.example.test;', '    listen [::]:80;\n    server_name other.example.test;'),
    'redirect-without-404': ('    return 404; # managed by Certbot\n', ''),
    'third-server': (None, '\nserver {\n    listen 80;\n    server_name api.example.test;\n    return 404;\n}\n'),
    'two-https': (None, '\n' + CERTBOT_SITE.split('}\nserver {')[0].replace('    INCLUDE\n', '') + '}\n'),
}


@pytest.mark.parametrize('fault', sorted(CERTBOT_FAULTS))
def test_nginx_certbot_shape_variations_refuse_before_any_external_io(tmp_path, fault):
    site, edits = CERTBOT_SITE, CERTBOT_FAULTS[fault]
    for old, new in zip(edits[::2], edits[1::2]):
        site = site + new if old is None else site.replace(old, new, 1)
    assert site != CERTBOT_SITE and site.count('INCLUDE') == 1
    ingress, fake = _nginx(tmp_path, site=site)
    with pytest.raises(Refused, match='^window-nginx-topology$'):
        ingress.verify_topology(timeout=5)
    assert fake.calls == [] and not ingress.snippet.exists()

def _enabled_link(tmp_path, target):
    (tmp_path / 'sites-enabled').mkdir()
    link = tmp_path / 'sites-enabled' / 'site'
    link.symlink_to(target)
    return str(link)


def test_nginx_sites_enabled_symlink_to_the_real_site_round_trips(tmp_path):
    ingress, fake = _nginx(tmp_path, site=CERTBOT_SITE, enabled=_enabled_link(tmp_path, tmp_path / 'site'))
    assert ingress.observe(SCOPE, timeout=5) == 'open'
    assert ingress.block(SCOPE, timeout=5) is True
    assert ingress.observe(SCOPE, timeout=5) == 'blocked'
    assert ingress.open(SCOPE, timeout=5) is True


@pytest.mark.parametrize('fault', ['relative-target', 'other-target', 'regular-file', 'missing', 'nginx-t-real-path'])
def test_nginx_sites_enabled_must_be_the_exact_symlink_nginx_loads(tmp_path, fault):
    enabled = str(tmp_path / 'sites-enabled' / 'site')
    if fault == 'relative-target':
        enabled = _enabled_link(tmp_path, '../site')
    elif fault == 'other-target':
        (tmp_path / 'other').write_text('')
        enabled = _enabled_link(tmp_path, tmp_path / 'other')
    elif fault == 'regular-file':
        (tmp_path / 'sites-enabled').mkdir()
        Path(enabled).write_text('')
    elif fault == 'nginx-t-real-path':
        enabled = _enabled_link(tmp_path, tmp_path / 'site')
    ingress, fake = _nginx(tmp_path, site=CERTBOT_SITE, enabled=enabled)
    if fault == 'nginx-t-real-path':
        fake.loaded = None  # nginx -T names the real file, not the declared enabled entry
        code = '^window-nginx-topology$'
    else:
        code = '^window-nginx-site$'
    with pytest.raises(Refused, match=code):
        ingress.verify_topology(timeout=5)
    assert not ingress.snippet.exists()
    if fault != 'nginx-t-real-path':
        assert fake.calls == []


def test_nginx_enabled_path_is_validated():
    base = dict(nginx_binary='/usr/sbin/nginx', systemctl_binary='/usr/bin/systemctl', curl_binary='/usr/bin/curl',
                site_path='/etc/nginx/sites-available/api', server_name='api.example.test')
    for enabled in ('sites-enabled/api', '/etc/nginx/sites-available/api'):
        with pytest.raises(Refused, match='^window-nginx-paths$'):
            wb.NginxConfig(**base, enabled_path=enabled).validated()
    assert wb.NginxConfig(**base, enabled_path='/etc/nginx/sites-enabled/api').validated().loaded_path == \
        '/etc/nginx/sites-enabled/api'


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
@pytest.mark.parametrize('site', [None, CERTBOT_SITE])
def test_effective_nginx_duplicate_server_alias_refuses(tmp_path, names, site):
    ingress, fake = _nginx(tmp_path, site=site)
    def run(argv, **kwargs):
        rc, data = fake(argv, **kwargs)
        if argv[1:] == ('-T',):
            data += ('# configuration file /other/site:\nserver {\nserver_name ' + names + ';\n}\n').encode()
        return rc, data
    ingress._run_command = run
    with pytest.raises(wb.Refused, match='^window-nginx-topology$'):
        ingress.verify_topology()
    assert not ingress.snippet.exists()


def test_writers_declare_a10_candidate_tuple_and_refuse_bad_provider_answers(tmp_path):
    third = '3' * 64
    binding, _ = _writers(tmp_path, {'postgres': 2},
                          {LEGACY: [(DB, 5432, '01', 11)], FOREIGN: [(DB, 5432, '01', 21)], third: []})
    binding.bind_candidate(lambda timeout: (FOREIGN, third))  # A10: IDs with a start receipt
    assert binding.observe(SCOPE, timeout=5) == 0
    for answer in ((FOREIGN, FOREIGN), (LEGACY,), ['x'], (FOREIGN,) * 5, ('z' * 64,)):
        other, _ = _writers(tmp_path / str(len(str(answer))) / answer[0][:1], {'postgres': 1},
                            {LEGACY: [(DB, 5432, '01', 11)]})
        other.bind_candidate(lambda timeout, answer=answer: answer)
        with pytest.raises(Refused, match='^window-writers-candidate$'):
            other.observe(SCOPE, timeout=5)
