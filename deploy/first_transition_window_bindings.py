"""Host bindings of the first-transition window: both ingress entries and the unknown-writer count.

They are the ``ingress``/``writers`` providers of first_transition_orchestrator.assemble and follow
the ObservedHostDriver protocol: each binding carries ``scope`` (the host manifest digest), the
ingress ones an ``entry``, and every method takes ``(scope, *, timeout)``.

* ``NginxMaintenanceIngress`` (entry ``external``): the public HTTPS API server block includes ONE
  glob (``NginxConfig.include_line``; a glob matching nothing is valid nginx). ``block`` writes the
  maintenance snippet there (server-level ``return 503`` with a marker header), runs
  ``nginx -t`` and reloads; ``open`` removes it the same way. ``observe`` reads the snippet AND
  probes the real server block through 127.0.0.1 with the public name: ``blocked`` needs the exact
  snippet and a 503 carrying the marker, ``open`` needs no snippet and no marker; anything else
  refuses. An optional HTTP companion must only redirect to the same HTTPS name; both
  protocols and each declared address family are probed. The one-time include edit of the
  production site is NOT done here.
* ``BridgePortIngress`` (entry ``evolution-backend``): Evolution reaches the backend over the
  shared Docker bridge, and without br_netfilter bridged frames never cross iptables (so a
  DOCKER-USER rule would not see them). The block is therefore an nftables ``bridge`` family
  table dropping TCP to the backend port between ports of THAT bridge; host-to-container traffic
  (published 127.0.0.1 port, ``docker exec`` smoke) is routed, not bridged, and stays untouched.
  ``observe`` accepts only the absent table (open) or exactly this table (blocked).
* ``UnknownWriters``: number of UNDECLARED writing sources, from the host and from PostgreSQL.
  Host: ESTABLISHED TCP to the database endpoint in every network namespace (via
  ``/proc/<pid>/net/tcp*``); a namespace of the declared containers (legacy roles, and the
  candidate backend) is declared, the host namespace is declared only for sockets of this
  process's descendants (the migration child), anything else counts. Database (owner credential,
  which holds pg_read_all_stats): client sessions holding an xid or not idle, other than this
  observer, whose role is neither a Supabase-internal role nor a verified read-only role; any of
  them beyond the declared host connections counts. Behind the Supavisor pooler a session does not
  name its source, so before containment a foreign active session can hide within the legacy
  budget; after containment the budget is zero. ``require_quiet`` (zero writing sessions before
  the DDL marker and every migration) stays the independent database guarantee.

Commands are fixed absolute argv with a minimal environment; their output is parsed and dropped,
never put in exceptions or receipts. Errors are fixed codes. Nothing runs at import or
construction. Tests use fakes and synthetic namespaces only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import fnmatch
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import time
from urllib.parse import urlsplit

from first_transition_host_driver import _absolute
from initial_transition_ops import Refused, require

HEX64 = re.compile('[0-9a-f]{64}')
HOST = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+')
BRIDGE = re.compile(r'br-[0-9a-f]{12}')
TABLE = re.compile(r'[a-z][a-z0-9_]{0,31}')
ROLE = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,62}')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'}
OUTPUT = 64 * 1024

MARKER = 'X-Igreja12-Window'
INCLUDE_DIR = '/etc/nginx/igreja12-window'
SNIPPET_NAME = 'maintenance.conf'
SNIPPET = (
    '# igreja12 first-transition window: public API in maintenance (removed when the window ends)\n'
    'add_header ' + MARKER + ' maintenance always;\n'
    'add_header Retry-After 900 always;\n'
    'default_type application/json;\n'
    "return 503 '{\"detail\":\"maintenance\"}';\n").encode()
PROBE_PATH = '/igreja12-window-probe'

NFT_COMMENT = 'igreja12-window'

# Supabase-managed service roles: their sessions are platform-internal, never an application source.
SUPABASE_INTERNAL = ('pgbouncer', 'supabase_admin', 'supabase_auth_admin', 'supabase_read_only_user',
                     'supabase_realtime_admin', 'supabase_replication_admin', 'supabase_storage_admin')
Q_ACTIVE = ('SELECT usename::text, count(*) FROM pg_stat_activity WHERE datid=(SELECT oid FROM pg_database '
            "WHERE datname=current_database()) AND pid<>pg_backend_pid() AND backend_type='client backend' "
            "AND (backend_xid IS NOT NULL OR state IS DISTINCT FROM 'idle') GROUP BY 1")
Q_STATS = "SELECT pg_has_role(current_user, 'pg_read_all_stats', 'USAGE')"
# A read-only role: no superuser/bypass and no write privilege on any public relation, sequence or schema.
Q_READONLY = ('SELECT r.rolname::text FROM pg_roles r WHERE r.rolname = ANY(%s::text[]) AND NOT r.rolsuper '
              'AND NOT r.rolcreaterole AND NOT r.rolcreatedb AND NOT EXISTS (SELECT 1 FROM pg_class c '
              "WHERE c.relnamespace='public'::regnamespace AND c.relkind IN ('r','p','v','m','f','S') "
              "AND has_table_privilege(r.oid, c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE')) "
              "AND NOT has_schema_privilege(r.oid, 'public', 'CREATE')")


def _bound_scope(scope):
    require(isinstance(scope, str) and HEX64.fullmatch(scope), 'window-binding-scope')
    return scope


def _deadline(timeout):
    require(type(timeout) in (int, float) and 0 < timeout <= 60, 'window-binding-timeout')
    return time.monotonic() + timeout


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('window-binding-timeout')
    return remaining


def _system_run(argv, *, timeout, stdin=None):
    try:
        result = subprocess.run(list(argv), input=stdin, capture_output=True, timeout=timeout, env=dict(ENV),
                                check=False, close_fds=True)
    except subprocess.TimeoutExpired:
        raise TimeoutError('window-binding-timeout') from None
    except OSError:
        raise Refused('window-binding-spawn') from None
    return result.returncode, result.stdout[:OUTPUT + 1]


class _Binding:
    def __init__(self, scope, run, sleep):
        self.scope = _bound_scope(scope)
        self._run_command = run or _system_run
        self._sleep = sleep or time.sleep

    def _check(self, scope):
        require(scope == self.scope, 'window-binding-scope')

    def _run(self, argv, deadline, *, stdin=None, code):
        try:
            rc, out = self._run_command(tuple(argv), timeout=_remaining(deadline), stdin=stdin)
        except TimeoutError:
            raise
        except Exception:
            raise Refused(code) from None
        require(type(rc) is int and type(out) is bytes and len(out) <= OUTPUT, code)
        return rc, out

    def _until(self, state, deadline):
        while True:
            if self.observe(self.scope, timeout=_remaining(deadline)) == state:
                return True
            self._sleep(min(0.5, _remaining(deadline)))


@dataclass(frozen=True)
class NginxConfig:
    nginx_binary: str
    systemctl_binary: str
    curl_binary: str
    site_path: str
    server_name: str
    include_dir: str = INCLUDE_DIR

    def validated(self):
        require(all(_absolute(p) for p in (self.nginx_binary, self.systemctl_binary, self.curl_binary,
                                           self.site_path, self.include_dir)), 'window-nginx-paths')
        require(isinstance(self.server_name, str) and HOST.fullmatch(self.server_name), 'window-nginx-server')
        return self

    @property
    def include_line(self):
        return 'include ' + self.include_dir + '/*.conf;'


SSL_OPTIONS = '/etc/letsencrypt/options-ssl-nginx.conf'


def _nginx_lines(text):
    # Only LF ends a line; only Certbot's literal annotation may trail a directive.
    for raw in text.split('\n'):
        line = raw.strip(' \t\r')
        if line.endswith(' # managed by Certbot'):
            line = line[:-len(' # managed by Certbot')].rstrip(' \t')
        if line and not line.startswith('#'):
            yield line


def _validate_nginx_topology(text, config):
    """One nominal HTTPS proxy, optionally accompanied by a same-host HTTP redirect.

    This is a bounded allowlist, not a general nginx parser. The maintenance include
    precedes the only HTTPS location; HTTP has no route to the backend of its own.
    """
    name = 'server_name ' + config.server_name + ';'
    redirect = 'return 301 https://' + config.server_name + '$request_uri;'
    guard = 'if ($host = ' + config.server_name + ') {'
    guarded_redirect = 'return 301 https://$host$request_uri;'
    tls = {
        'ssl_certificate /etc/letsencrypt/live/' + config.server_name + '/fullchain.pem;',
        'ssl_certificate_key /etc/letsencrypt/live/' + config.server_name + '/privkey.pem;',
        'include ' + SSL_OPTIONS + ';',
        'ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;',
    }
    headers = {
        'proxy_set_header Host $host;', 'proxy_set_header X-Real-IP $remote_addr;',
        'proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;',
        'proxy_set_header X-Forwarded-Proto $scheme;',
    }
    v6_https = {'listen [::]:443 ssl;', 'listen [::]:443 ssl ipv6only=on;'}
    commands = {name, config.include_line, redirect, 'return 404;', 'listen 80;',
                'listen [::]:80;', 'listen 443 ssl;'} | tls | v6_https
    blocks, stack, seen = [], [], set()
    for line in _nginx_lines(text):
        if line == 'server {':
            require(not stack and len(blocks) < 2, 'window-nginx-topology')
            stack, seen = ['server'], set()
        elif line == 'location / {':
            require(stack == ['server'] and config.include_line in seen and 'location' not in seen,
                    'window-nginx-topology')
            stack.append('location')
            seen.add('location')
        elif line == guard:
            require(stack == ['server'] and 'guard' not in seen and 'return 404;' not in seen,
                    'window-nginx-topology')
            stack.append('guard')
            seen.add('guard')
        elif line == '}':
            require(bool(stack), 'window-nginx-topology')
            if stack[-1] == 'guard':
                require('guard-return' in seen, 'window-nginx-topology')
            stack.pop()
            if not stack:
                blocks.append(seen)
        elif stack == ['server'] and line in commands:
            require(line not in seen and (line != config.include_line or 'location' not in seen),
                    'window-nginx-topology')
            seen.add(line)
        elif stack == ['server', 'location'] and line in headers:
            require(line not in seen, 'window-nginx-topology')
            seen.add(line)
        elif stack == ['server', 'location'] and line == 'proxy_pass http://127.0.0.1:8000;':
            require('proxy' not in seen, 'window-nginx-topology')
            seen.add('proxy')
        elif stack == ['server', 'guard'] and line == guarded_redirect:
            require('guard-return' not in seen, 'window-nginx-topology')
            seen.add('guard-return')
        else:
            raise Refused('window-nginx-topology')
    require(not stack and len(blocks) in (1, 2), 'window-nginx-topology')
    https, http = [], []
    for block in blocks:
        if 'listen 443 ssl;' in block:
            required = {name, config.include_line, 'listen 443 ssl;', 'location', 'proxy'}
            require(required <= block <= required | v6_https | tls | headers
                    and len(block & v6_https) <= 1, 'window-nginx-topology')
            certs = {v for v in tls if v.startswith(('ssl_certificate ', 'ssl_certificate_key '))}
            require(not block & certs or certs <= block, 'window-nginx-topology')
            https.append(block)
        else:
            required = {name, 'listen 80;'}
            direct = required | {redirect}
            certbot = required | {'guard', 'guard-return', 'return 404;'}
            require(block - {'listen [::]:80;'} in (direct, certbot), 'window-nginx-topology')
            http.append(block)
    require(len(https) == 1 and len(http) == len(blocks) - 1, 'window-nginx-topology')
    return dict(http_redirect=bool(http), https_ipv6=bool(https[0] & v6_https),
                http_ipv6=bool(http and 'listen [::]:80;' in http[0]),
                ssl_options='include ' + SSL_OPTIONS + ';' in https[0])


def _nginx_fragment(effective, path):
    marker = '# configuration file ' + path + ':\n'
    require(effective.count(marker) == 1, 'window-nginx-topology')
    return effective.split(marker, 1)[1].split('# configuration file ', 1)[0]


def _validate_ssl_options(text):
    # A TLS include must not conceal a return, location, include or executable handler.
    patterns = (
        r'ssl_session_cache shared:[A-Za-z0-9_]+:[0-9]+[mk];',
        r'ssl_session_timeout [0-9]+[mhd];', r'ssl_session_tickets (?:on|off);',
        r'ssl_protocols TLSv1\.2(?: TLSv1\.3)?;', r'ssl_prefer_server_ciphers (?:on|off);',
        r'ssl_ciphers (?:[A-Za-z0-9:+_!-]+|\"[A-Za-z0-9:+_!-]+\"|\'[A-Za-z0-9:+_!-]+\');',
    )
    require(all(any(re.fullmatch(p, line) for p in patterns) for line in _nginx_lines(text)),
            'window-nginx-topology')


def _nginx_without_comments(text):
    # Preserve # within quoted strings so other files cannot hide names/includes.
    result, quote, escaped, comment = [], None, False, False
    for char in text:
        if comment:
            if char == '\n':
                comment = False
                result.append(char)
        elif escaped:
            result.append(char)
            escaped = False
        elif char == '\\':
            result.append(char)
            escaped = True
        elif quote:
            result.append(char)
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            result.append(char)
        elif char == '#':
            # nginx permits # inside an unquoted token; this narrow profile refuses
            # that token instead of dropping later directives as a false comment.
            require(not result or result[-1] in ' \t\r\n;{}', 'window-nginx-topology')
            comment = True
        else:
            result.append(char)
    require(quote is None and not escaped, 'window-nginx-topology')
    return ''.join(result)


def _validate_nginx_include_graph(effective, target):
    """A single root-to-site path, including multiplicity of intermediate includes.

    Only absolute literal/glob includes over the complete -T fragment inventory are
    admitted. Unknown expansions, unreachable fragments and cycles refuse.
    """
    markers = list(re.finditer(r'^# configuration file ([^\r\n]+):\n', effective, re.MULTILINE))
    require(markers and markers[0].start() == 0 and len(markers) <= 128, 'window-nginx-topology')
    paths = [m.group(1) for m in markers]
    require(len(set(paths)) == len(paths) and target in paths, 'window-nginx-topology')
    graph = {}
    for i, marker in enumerate(markers):
        path = paths[i]
        require(path.startswith('/') and re.fullmatch(r'[A-Za-z0-9_./-]+', path)
                and '..' not in Path(path).parts, 'window-nginx-topology')
        body = effective[marker.end():markers[i + 1].start() if i + 1 < len(markers) else len(effective)]
        patterns = re.findall(r'\binclude\s+([^;{}]+);', _nginx_without_comments(body))
        children = []
        for pattern in patterns:
            require(pattern.startswith('/') and re.fullmatch(r'[A-Za-z0-9_./*?\[\]-]+', pattern)
                    and '..' not in Path(pattern).parts, 'window-nginx-topology')
            matches = [p for p in paths if fnmatch.fnmatchcase(p, pattern)]
            require(matches or any(c in pattern for c in '*?['), 'window-nginx-topology')
            children.extend(matches)  # duplicates matter: nginx expands the file again
        graph[path] = children
    require(sum(map(len, graph.values())) <= 512, 'window-nginx-topology')
    visited, calls = set(), 0
    def visit(path, ancestors):
        nonlocal calls
        calls += 1
        require(calls <= 512 and path not in ancestors, 'window-nginx-topology')
        visited.add(path)
        return int(path == target) + sum(visit(p, ancestors | {path}) for p in graph[path])
    require(visit(paths[0], set()) == 1 and visited == set(paths), 'window-nginx-topology')


class NginxMaintenanceIngress(_Binding):
    entry = 'external'

    def __init__(self, config, *, scope, run=None, sleep=None, owner_uid=0):
        super().__init__(scope, run, sleep)
        self.config = config.validated()
        self.snippet = Path(self.config.include_dir) / SNIPPET_NAME
        self.owner_uid = owner_uid

    def _include_present(self):
        try:
            fd = os.open(self.config.site_path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            raise Refused('window-nginx-site') from None
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == self.owner_uid and not info.st_mode & 0o022
                    and info.st_size <= OUTPUT, 'window-nginx-site')
            text = handle.read(OUTPUT + 1).decode('utf-8')
            lines = [line.strip() for line in text.splitlines()]
        require(lines.count(self.config.include_line) == 1, 'window-nginx-include-missing')
        return text

    def _site_alias(self):
        """At most one nominal sites-enabled symlink to the already regular site file."""
        site = Path(self.config.site_path)
        if site.parent != Path('/etc/nginx/sites-available'):
            return None
        enabled = Path('/etc/nginx/sites-enabled') / site.name
        try:
            info = os.lstat(enabled)
        except FileNotFoundError:
            return None
        except OSError:
            raise Refused('window-nginx-topology') from None
        try:
            for parent in (enabled.parent, enabled.parent.parent, Path('/etc'), Path('/')):
                directory = os.lstat(parent)
                require(stat.S_ISDIR(directory.st_mode) and directory.st_uid == self.owner_uid
                        and not directory.st_mode & 0o022, 'window-nginx-topology')
            require(stat.S_ISLNK(info.st_mode) and info.st_uid == self.owner_uid, 'window-nginx-topology')
            target = os.readlink(enabled)
            require(target in (str(site), '../sites-available/' + site.name), 'window-nginx-topology')
            fingerprint = tuple(getattr(info, k) for k in (
                'st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink', 'st_mtime_ns', 'st_ctime_ns'))
            return str(enabled), fingerprint, target
        except OSError:
            raise Refused('window-nginx-topology') from None

    def verify_topology(self, *, timeout=10):
        """Revalidate nominal HTTP/HTTPS routes, file identity and effective dump on every call."""
        deadline = _deadline(timeout)
        text = self._include_present()
        topology = _validate_nginx_topology(text, self.config)
        alias = self._site_alias()
        rc, out = self._run((self.config.nginx_binary, '-T'), deadline, code='window-nginx-topology')
        require(rc == 0 and self._site_alias() == alias, 'window-nginx-topology')
        effective = out.decode('utf-8')
        paths = [self.config.site_path] + ([alias[0]] if alias else [])
        matched = [p for p in paths if '# configuration file ' + p + ':\n' in effective]
        require(len(matched) == 1, 'window-nginx-topology')
        selected = _nginx_fragment(effective, matched[0])
        uncommented = _nginx_without_comments(effective)
        require(selected.strip() == text.strip()
                and sum(self.config.server_name.lower() in [token.strip("\"'").lower() for token in names.split()]
                        for names in re.findall(r'\bserver_name\s+([^;{}]+);', uncommented))
                == 1 + int(topology['http_redirect']), 'window-nginx-topology')
        if topology['http_redirect']:
            _validate_nginx_include_graph(effective, matched[0])
        if topology['ssl_options']:
            _validate_ssl_options(_nginx_fragment(effective, SSL_OPTIONS))
        return topology

    def _directory(self):
        try:
            info = os.lstat(self.config.include_dir)
        except OSError:
            raise Refused('window-nginx-include-dir') from None
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == self.owner_uid and not info.st_mode & 0o022,
                'window-nginx-include-dir')
        require(sorted(os.listdir(self.config.include_dir)) in ([], [SNIPPET_NAME]), 'window-nginx-include-foreign')

    def _snippet_state(self):
        """'absent' or 'exact'; any other content (or a symlink) refuses."""
        self._directory()
        try:
            fd = os.open(self.snippet, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return 'absent'
        except OSError:
            raise Refused('window-nginx-snippet') from None
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == self.owner_uid and not info.st_mode & 0o022,
                    'window-nginx-snippet')
            require(handle.read(len(SNIPPET) + 1) == SNIPPET, 'window-nginx-snippet-foreign')
        return 'exact'

    def _probe(self, deadline, *, scheme='https', address='127.0.0.1'):
        """No curlrc/proxy/redirect following; inspect one response from the nominal listener."""
        name = self.config.server_name
        port = '443' if scheme == 'https' else '80'
        rc, out = self._run((self.config.curl_binary, '-q', '-sS', '--noproxy', '*', '-o', '/dev/null',
                             '-D', '-', '--max-time', '5', '--resolve', name + ':' + port + ':' + address,
                             scheme + '://' + name + PROBE_PATH), deadline, code='window-nginx-probe')
        require(rc == 0, 'window-nginx-probe')
        lines = out.decode('latin-1').split('\r\n')
        match = re.fullmatch(r'HTTP/[0-9.]+ ([0-9]{3})(?: .*)?', lines[0])
        require(match is not None and lines[-2:] == ['', ''] and all(lines[1:-2]), 'window-nginx-probe')
        headers = []
        for line in lines[1:-2]:
            name, sep, value = line.partition(':')
            require(sep and re.fullmatch(r'[A-Za-z0-9!#$%&*+.^_`|~-]+', name), 'window-nginx-probe')
            headers.append((name.lower(), value.strip(' \t')))
        markers = [v for k, v in headers if k == MARKER.lower()]
        locations = [v for k, v in headers if k == 'location']
        require(markers in ([], ['maintenance']) and len(locations) <= 1, 'window-nginx-probe')
        return int(match.group(1)), bool(markers), locations[0] if locations else None

    def observe(self, scope, *, timeout):
        self._check(scope)
        deadline = _deadline(timeout)
        topology = self.verify_topology(timeout=_remaining(deadline))
        snippet = self._snippet_state()
        if topology['http_redirect']:
            for address in ('127.0.0.1', '[::1]') if topology['http_ipv6'] else ('127.0.0.1',):
                status, marker, location = self._probe(deadline, scheme='http', address=address)
                require(status == 301 and not marker
                        and location == 'https://' + self.config.server_name + PROBE_PATH, 'window-nginx-partial')
        states = []
        for address in ('127.0.0.1', '[::1]') if topology['https_ipv6'] else ('127.0.0.1',):
            status, marker, _ = self._probe(deadline, address=address)
            if snippet == 'exact' and marker and status == 503:
                states.append('blocked')
            elif snippet == 'absent' and not marker and status != 503 and not 300 <= status < 400:
                states.append('open')
            else:
                raise Refused('window-nginx-partial')
        require(len(set(states)) == 1, 'window-nginx-partial')
        return states[0]

    def _until(self, state, deadline):
        while True:
            try:
                if self.observe(self.scope, timeout=_remaining(deadline)) == state:
                    return True
            except Refused as exc:
                if str(exc) != 'window-nginx-partial':
                    raise
            self._sleep(min(0.5, _remaining(deadline)))

    def _reload(self, deadline):
        rc, _ = self._run((self.config.nginx_binary, '-t', '-q'), deadline, code='window-nginx-test')
        require(rc == 0, 'window-nginx-test')
        rc, _ = self._run((self.config.systemctl_binary, 'reload', 'nginx.service'), deadline,
                          code='window-nginx-reload')
        require(rc == 0, 'window-nginx-reload')

    def block(self, scope, *, timeout):
        self._check(scope)
        deadline = _deadline(timeout)
        self.verify_topology(timeout=_remaining(deadline))
        if self._snippet_state() == 'absent':
            temp = self.snippet.with_name('.' + SNIPPET_NAME + '.tmp')
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(SNIPPET)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.rename(temp, self.snippet)
            finally:
                if os.path.lexists(temp):
                    os.unlink(temp)
        try:
            self._reload(deadline)
        except Refused:
            # A config nginx rejects is never left behind; the running config was not reloaded.
            if self._snippet_state() == 'exact':
                os.unlink(self.snippet)
            raise
        return self._until('blocked', deadline)

    def open(self, scope, *, timeout):
        self._check(scope)
        deadline = _deadline(timeout)
        self.verify_topology(timeout=_remaining(deadline))
        if self._snippet_state() == 'exact':
            os.unlink(self.snippet)
        self._reload(deadline)
        return self._until('open', deadline)


@dataclass(frozen=True)
class BridgeConfig:
    nft_binary: str
    bridge: str
    port: int = 8000
    table: str = 'igreja12_window'

    def validated(self):
        require(_absolute(self.nft_binary) and isinstance(self.bridge, str) and BRIDGE.fullmatch(self.bridge)
                and type(self.port) is int and 0 < self.port < 65536
                and isinstance(self.table, str) and TABLE.fullmatch(self.table), 'window-bridge-config')
        return self

    def ruleset(self):
        return ('table bridge ' + self.table + ' {\n\tchain forward {\n'
                '\t\ttype filter hook forward priority -200; policy accept;\n'
                f'\t\tmeta ibrname "{self.bridge}" tcp dport {self.port} drop comment "{NFT_COMMENT}"\n'
                '\t}\n}\n').encode()

    def expected(self):
        """The table as ``nft -j`` lists it (handles stripped)."""
        return [dict(table=dict(family='bridge', name=self.table)),
                dict(chain=dict(family='bridge', table=self.table, name='forward', type='filter', hook='forward',
                                prio=-200, policy='accept')),
                dict(rule=dict(family='bridge', table=self.table, chain='forward', comment=NFT_COMMENT, expr=[
                    {'match': {'op': '==', 'left': {'meta': {'key': 'ibrname'}}, 'right': self.bridge}},
                    {'match': {'op': '==', 'left': {'payload': {'protocol': 'tcp', 'field': 'dport'}},
                               'right': self.port}},
                    {'drop': None}]))]


def _nft_items(out, code):
    try:
        data = json.loads(out)
    except ValueError:
        raise Refused(code) from None
    require(isinstance(data, dict) and set(data) == {'nftables'} and isinstance(data['nftables'], list), code)
    items = []
    for item in data['nftables']:
        require(isinstance(item, dict) and len(item) == 1, code)
        if 'metainfo' in item:
            continue
        (kind, value), = item.items()
        require(isinstance(value, dict), code)
        items.append({kind: {k: v for k, v in value.items() if k != 'handle'}})
    return items


class BridgePortIngress(_Binding):
    entry = 'evolution-backend'

    def __init__(self, config, *, scope, run=None, sleep=None):
        super().__init__(scope, run, sleep)
        self.config = config.validated()

    def observe(self, scope, *, timeout):
        self._check(scope)
        deadline = _deadline(timeout)
        nft, table = self.config.nft_binary, self.config.table
        rc, out = self._run((nft, '-j', 'list', 'tables', 'bridge'), deadline, code='window-bridge-list')
        require(rc == 0, 'window-bridge-list')
        names = [i['table'].get('name') for i in _nft_items(out, 'window-bridge-list') if 'table' in i]
        if table not in names:
            return 'open'
        rc, out = self._run((nft, '-j', 'list', 'table', 'bridge', table), deadline, code='window-bridge-list')
        require(rc == 0, 'window-bridge-list')
        require(_nft_items(out, 'window-bridge-list') == self.config.expected(), 'window-bridge-foreign')
        return 'blocked'

    def block(self, scope, *, timeout):
        self._check(scope)
        deadline = _deadline(timeout)
        if self.observe(scope, timeout=_remaining(deadline)) == 'open':
            # One atomic transaction: the table appears complete or not at all.
            rc, _ = self._run((self.config.nft_binary, '-f', '-'), deadline, stdin=self.config.ruleset(),
                              code='window-bridge-apply')
            require(rc == 0, 'window-bridge-apply')
        return self.observe(scope, timeout=_remaining(deadline)) == 'blocked'

    def open(self, scope, *, timeout):
        self._check(scope)
        deadline = _deadline(timeout)
        if self.observe(scope, timeout=_remaining(deadline)) == 'blocked':
            rc, _ = self._run((self.config.nft_binary, 'delete', 'table', 'bridge', self.config.table), deadline,
                              code='window-bridge-apply')
            require(rc == 0, 'window-bridge-apply')
        return self.observe(scope, timeout=_remaining(deadline)) == 'open'


def database_endpoint(url):
    """(addresses, port) of the database URL host; nothing of the URL is kept."""
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port or 5432
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (ValueError, OSError, UnicodeError):
        raise Refused('window-writers-endpoint') from None
    require(parts.scheme in ('postgresql', 'postgres') and infos, 'window-writers-endpoint')
    return frozenset(ipaddress.ip_address(info[4][0]) for info in infos), port


def _tcp_rows(text):
    """(remote address, remote port, inode) of ESTABLISHED sockets of one /proc/<pid>/net/tcp{,6} table."""
    rows = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 10 or fields[3] != '01':
            continue
        address, port = fields[2].split(':')
        raw = bytes.fromhex(address)
        # The kernel prints each 32-bit word in host (little-endian) order.
        raw = b''.join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
        ip = ipaddress.ip_address(raw)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        rows.append((ip, int(port, 16), int(fields[9])))
    return rows


class UnknownWriters(_Binding):
    """``observe`` returns the number of undeclared writing sources (see the module docstring)."""

    def __init__(self, *, scope, connect, endpoint, declared_containers, docker, readonly_roles=(),
                 internal_roles=SUPABASE_INTERNAL, proc='/proc', run=None, own_pid=None):
        super().__init__(scope, run, None)
        require(callable(connect), 'window-writers-connect')
        addresses, port = endpoint
        require(isinstance(addresses, frozenset) and addresses and type(port) is int, 'window-writers-endpoint')
        require(isinstance(declared_containers, tuple) and declared_containers
                and all(isinstance(c, str) and HEX64.fullmatch(c) for c in declared_containers),
                'window-writers-declared')
        binary, endpoint_url, config_dir = docker
        require(all(_absolute(p) for p in (binary, config_dir)) and endpoint_url.startswith('unix:///'),
                'window-writers-docker')
        require(all(isinstance(r, str) and ROLE.fullmatch(r) for r in (*readonly_roles, *internal_roles))
                and not set(readonly_roles) & set(internal_roles), 'window-writers-roles')
        self.connect, self.addresses, self.port = connect, addresses, port
        self.declared = frozenset(declared_containers)
        self.docker = (binary, '--config', config_dir, '--host', endpoint_url)
        self.readonly_roles, self.internal_roles = tuple(readonly_roles), tuple(internal_roles)
        self.proc = Path(proc)
        self.own_pid = own_pid or os.getpid()
        self._candidate_provider = None

    def bind_candidate(self, provider):
        """Assembly-only hook: every observation gets a freshly validated A9 backend ID."""
        require(self._candidate_provider is None and callable(provider), 'window-writers-candidate-binding')
        self._candidate_provider = provider

    def _containers(self, deadline):
        """{namespace inode: set of container IDs} for every running container."""
        rc, out = self._run((*self.docker, 'ps', '-q', '--no-trunc'), deadline, code='window-writers-docker')
        require(rc == 0, 'window-writers-docker')
        ids = out.decode().split()
        require(all(HEX64.fullmatch(i) for i in ids) and len(set(ids)) == len(ids), 'window-writers-docker')
        spaces = {}
        if not ids:
            return spaces
        rc, out = self._run((*self.docker, 'inspect', '--format', '{{json .Id}} {{json .State.Pid}}', *ids),
                            deadline, code='window-writers-docker')
        require(rc == 0, 'window-writers-docker')
        seen = set()
        try:
            rows = [tuple(json.loads(v) for v in line.split(' ')) for line in out.decode().splitlines()]
        except (ValueError, UnicodeError):
            raise Refused('window-writers-docker') from None
        for row in rows:
            require(len(row) == 2, 'window-writers-docker')
            ident, pid = row
            require(isinstance(ident, str) and ident in ids and ident not in seen
                    and type(pid) is int and pid > 0, 'window-writers-docker')
            seen.add(ident)
            spaces.setdefault(self._netns(pid), (pid, set()))[1].add(ident)
        require(seen == set(ids), 'window-writers-docker')
        return spaces

    def _netns(self, pid):
        try:
            return os.stat(self.proc / str(pid) / 'ns' / 'net').st_ino
        except OSError:
            raise Refused('window-writers-proc') from None

    def _connections(self, pid):
        """(endpoint connections, their inodes) seen in the network namespace of ``pid``."""
        found = []
        for table in ('tcp', 'tcp6'):
            try:
                text = (self.proc / str(pid) / 'net' / table).read_text()
            except FileNotFoundError:
                continue
            except OSError:
                raise Refused('window-writers-proc') from None
            found += [inode for ip, port, inode in _tcp_rows(text) if ip in self.addresses and port == self.port]
        return found

    def _descendant_sockets(self):
        """Socket inodes held by descendants of this process (the migration child), not by itself."""
        parents = {}
        for entry in self.proc.iterdir():
            if entry.name.isdigit():
                try:
                    stat_line = (entry / 'stat').read_text()
                    parents[int(entry.name)] = int(stat_line[stat_line.rindex(')') + 2:].split()[1])
                except (OSError, ValueError):
                    continue
        children, frontier = set(), {self.own_pid}
        while frontier:
            frontier = {pid for pid, parent in parents.items() if parent in frontier} - children
            children |= frontier
        inodes = set()
        for pid in children:
            try:
                for fd in (self.proc / str(pid) / 'fd').iterdir():
                    target = os.readlink(fd)
                    if target.startswith('socket:['):
                        inodes.add(int(target[8:-1]))
            except OSError:
                continue
        return inodes

    def _host_side(self, deadline, declared_ids=None):
        """(declared connections, undeclared connections) towards the database endpoint."""
        declared = undeclared = 0
        declared_ids = self.declared if declared_ids is None else declared_ids
        spaces = self._containers(deadline)
        host_ns = self._netns(1)
        for namespace, (pid, ids) in spaces.items():
            if namespace == host_ns:
                continue  # host-network containers are judged with the host namespace below
            connections = len(self._connections(pid))
            if ids <= declared_ids:
                declared += connections
            else:
                undeclared += connections
        own = self._descendant_sockets()
        for inode in self._connections(1):
            if inode in own:
                declared += 1
            else:
                undeclared += 1
        _remaining(deadline)
        return declared, undeclared

    def _database_side(self, deadline):
        """Active client sessions of non-internal, non-read-only roles (this observer excluded)."""
        timeout = _remaining(deadline)
        conn = self.connect(timeout=timeout)
        try:
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            try:
                cur.execute("SELECT set_config('statement_timeout', %s, true)", (f'{max(1, int(timeout * 1000))}ms',))
                cur.fetchall()
                cur.execute(Q_STATS)
                require(cur.fetchall() == [(True,)], 'window-writers-stats-privilege')
                cur.execute(Q_READONLY, (list(self.readonly_roles),))
                readonly = {row[0] for row in cur.fetchall()}
                cur.execute(Q_ACTIVE)
                rows = cur.fetchall()
            finally:
                cur.execute('ROLLBACK')
        finally:
            conn.close()
        require(all(isinstance(r, (list, tuple)) and len(r) == 2 and type(r[1]) is int and r[1] >= 0 for r in rows),
                'window-writers-shape')
        exempt = set(self.internal_roles) | readonly
        return sum(count for role, count in rows if role not in exempt)

    def observe(self, scope, *, timeout):
        self._check(scope)
        deadline = _deadline(timeout)
        backend = None if self._candidate_provider is None else self._candidate_provider(timeout=_remaining(deadline))
        require(backend is None or isinstance(backend, str) and HEX64.fullmatch(backend)
                and backend not in self.declared, 'window-writers-candidate')
        declared_ids = self.declared | ({backend} if backend is not None else set())
        declared, undeclared = self._host_side(deadline, declared_ids)
        active = self._database_side(deadline)
        return undeclared + max(0, active - declared)


BINDINGS_KEYS = frozenset({'scope', 'nginx', 'bridge', 'writers'})
WRITERS_KEYS = frozenset({'declared_containers', 'readonly_roles', 'docker'})


def validate_bindings_config(data, *, config=None):
    """Pure schema/cross-scope validation. No secret, DNS, process or connection is consulted."""
    require(isinstance(data, dict) and set(data) == BINDINGS_KEYS and all(
        isinstance(data[k], dict) for k in ('nginx', 'bridge', 'writers')), 'window-bindings-config')
    writers = data['writers']
    require(set(writers) <= WRITERS_KEYS and {'declared_containers', 'docker'} <= set(writers)
            and isinstance(writers['declared_containers'], list) and isinstance(writers['docker'], list)
            and len(writers['docker']) == 3 and isinstance(writers.get('readonly_roles', []), list),
            'window-bindings-config')
    try:
        nginx = NginxConfig(**data['nginx']).validated()
        bridge = BridgeConfig(**data['bridge']).validated()
    except TypeError:
        raise Refused('window-bindings-config') from None
    scope = _bound_scope(data['scope'])
    ids, roles, docker = writers['declared_containers'], writers.get('readonly_roles', []), writers['docker']
    require(ids and all(isinstance(i, str) and HEX64.fullmatch(i) for i in ids) and len(set(ids)) == len(ids)
            and all(isinstance(r, str) and ROLE.fullmatch(r) for r in roles)
            and not set(roles) & set(SUPABASE_INTERNAL), 'window-bindings-config')
    require(all(isinstance(p, str) for p in docker) and _absolute(docker[0]) and _absolute(docker[2])
            and docker[1].startswith('unix:///'), 'window-bindings-docker')
    if config is not None:
        require(scope == config.manifest.digest, 'window-bindings-scope')
        require(bridge.bridge == 'br-' + config.manifest.network_id[:12] and bridge.port == 8000,
                'window-bindings-bridge')
        require(set(ids) == {i for _, i in config.manifest.service_ids}, 'window-bindings-declarations')
        require(tuple(docker) == config.docker, 'window-bindings-docker')
    return dict(scope=scope, nginx=asdict(nginx), bridge=asdict(bridge),
                writers=dict(declared_containers=sorted(ids), readonly_roles=sorted(roles), docker=list(docker)))


def bindings_from_dict(data, *, secret, connect, run=None, proc='/proc', owner_uid=0, endpoint=None):
    """Real bindings with optional external IO, never an alternative writer implementation."""
    data = validate_bindings_config(data)
    nginx, bridge = NginxConfig(**data['nginx']), BridgeConfig(**data['bridge'])
    writers, scope = data['writers'], data['scope']
    ingress = {'external': NginxMaintenanceIngress(nginx, scope=scope, run=run, owner_uid=owner_uid),
               'evolution-backend': BridgePortIngress(bridge, scope=scope, run=run)}
    unknown = UnknownWriters(scope=scope, connect=connect, endpoint=(endpoint or database_endpoint)(secret()),
                             declared_containers=tuple(writers['declared_containers']),
                             docker=tuple(writers['docker']), readonly_roles=tuple(writers['readonly_roles']),
                             proc=proc, run=run)
    return ingress, unknown
