"""Cooperative nonblocking HTTPS GET, no DNS, threads, retry or file reader.

Endpoint numeric addresses and a verified SSLContext must be prepared BEFORE the
holder starts. Constructor validates only; it never connects/calls checkpoint.
Each TLS/socket wait polls <=0.1s and checkpoints on the calling main thread.
First address only, no failover. Only Content-Length framing is supported;
chunked/Transfer-Encoding, redirects/interim responses and duplicate headers are
refused. Application header recv is one byte: it does not prefetch body bytes.
OpenSSL necessarily has internal TLS record buffering, not controlled by Python.
Body recv is <=min(requested n, remaining Content-Length); framed end returns
empty without an extra TLS read. It does not prove TLS EOF/no trailing wire data.
Close does no blocking TLS unwrap. This transport alone attests no window/A8.
Checkpoint/guard/Pulse callbacks and native OpenSSL CPU are not preempted here;
their real latency remains an external obligation. Header recv1 checkpoints can
consume budget with a costly guard; only the synthetic checkpoint is tested.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import ipaddress
import math
import os
import re
import selectors
import socket
import ssl
import threading
import time
from urllib.parse import quote

HOST = 'pffafnchtxbimpwyaczq.supabase.co'
HEADER_LIMIT = 16384
POLL_SECONDS = .1
ENV_BLOCKED = frozenset(('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY',
    'http_proxy','https_proxy','all_proxy','no_proxy','SSLKEYLOGFILE'))


class Refused(ValueError):
    """Fixed code only; native exceptions/request headers are never reflected."""


@dataclass(frozen=True, repr=False)
class Endpoint:
    host: str
    addresses: tuple[str, ...]
    port: int = 443
    profile: str = 'nominal'


def need(ok, code):
    if not ok:
        raise Refused(code)


def environment():
    need(not any(name in os.environ for name in ENV_BLOCKED), 'http-environment-refused')


def tls_profile(context):
    need(isinstance(context,ssl.SSLContext) and context.check_hostname is True
         and context.verify_mode == ssl.CERT_REQUIRED
         and context.minimum_version >= ssl.TLSVersion.TLSv1_2
         and context.keylog_filename is None, 'http-tls-profile')


def endpoint_profile(endpoint):
    need(type(endpoint) is Endpoint and type(endpoint.port) is int and 1 <= endpoint.port <= 65535
         and type(endpoint.addresses) is tuple and 1 <= len(endpoint.addresses) <= 8,
         'http-endpoint-profile')
    values = []
    for address in endpoint.addresses:
        need(type(address) is str and '%' not in address, 'http-endpoint-profile')
        try:
            values.append(ipaddress.ip_address(address))
        except ValueError:
            raise Refused('http-endpoint-profile') from None
    if endpoint.profile == 'nominal':
        need(endpoint.host == HOST and endpoint.port == 443 and all(a.is_global for a in values),
             'http-endpoint-profile')
    else:
        need(endpoint.profile == 'synthetic' and endpoint.host == 'fixture.invalid'
             and all(a.is_loopback for a in values), 'http-endpoint-profile')
    return values[0]


class HTTPReader:
    def __init__(self, token, endpoint, context, checkpoint):
        environment()
        tls_profile(context)
        self._address = endpoint_profile(endpoint)
        need(type(token) is str and 0 < len(token) <= 8192
             and all(32 < ord(c) < 127 for c in token), 'http-token-profile')
        need(callable(checkpoint) and threading.get_ident() == threading.main_thread().ident,
             'http-checkpoint-profile')
        self._token, self._endpoint, self._context, self._checkpoint = token,endpoint,context,checkpoint
        self._thread = threading.get_ident()
        self._active = False

    def __repr__(self):
        return '<HTTPReader private>'

    def _tick(self, deadline):
        need(threading.get_ident() == self._thread, 'http-thread-refused')
        need(type(deadline) in (int,float) and math.isfinite(deadline)
             and time.monotonic() < deadline, 'http-deadline')
        try:
            self._checkpoint()
        except Exception:
            raise Refused('http-checkpoint-refused') from None
        need(time.monotonic() < deadline, 'http-deadline')

    def _request(self, entry):
        need(type(entry) is dict, 'http-entry-profile')
        bucket,key,version,size,etag = (entry.get(k) for k in ('bucket','key','version','bytes','etag'))
        need(type(bucket) is str and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}',bucket)
             and type(key) is str and 0 < len(key.encode()) <= 4096 and '\\' not in key
             and all(ord(c) >= 32 and ord(c) != 127 for c in key)
             and all(p not in ('','.','..') for p in key.split('/'))
             and type(version) is str and 0 < len(version) <= 128
             and all(32 < ord(c) < 127 for c in version)
             and type(size) is int and 0 <= size <= 1000000000
             and (etag is None or type(etag) is str and 0 < len(etag) <= 256
                  and all(32 <= ord(c) < 127 for c in etag)), 'http-entry-profile')
        path = '/storage/v1/object/authenticated/'+quote(bucket,safe='')+'/'+quote(key,safe='/')
        path += '?versionId='+quote(version,safe='')
        host = self._endpoint.host
        if self._endpoint.port != 443:
            host += ':'+str(self._endpoint.port)
        headers = ['GET '+path+' HTTP/1.1','Host: '+host,'Authorization: Bearer '+self._token,
                   'apikey: '+self._token,'Accept-Encoding: identity','Connection: close']
        if etag is not None:
            headers.append('If-Match: '+etag)
        raw = ('\r\n'.join(headers)+'\r\n\r\n').encode('ascii')
        need(len(raw) <= 32768, 'http-request-limit')
        return raw,size,etag

    @contextmanager
    def open(self, entry, deadline):
        environment()
        tls_profile(self._context)
        endpoint_profile(self._endpoint)
        need(not self._active, 'http-reader-busy')
        connection, primary = None, False
        try:
            try:
                request,size,etag = self._request(entry)
                self._tick(deadline)
                self._active = True
                connection = _Connection(self,deadline)
                connection.connect()
                connection.send(request)
                connection.headers(size,etag)
            except Refused:
                raise
            except Exception:
                raise Refused('http-operation-refused') from None
            yield _Stream(connection,size)
        except BaseException:
            primary = True
            raise  # In particular, preserve the caller's own body/cancellation.
        finally:
            try:
                if connection is not None:
                    connection.close()
            except BaseException:
                if not primary:
                    raise
            finally:
                self._active = False


class _Connection:
    def __init__(self, reader, deadline):
        self.reader, self.deadline = reader,deadline
        self.sock = self.raw = self.selector = None
        self.closed = False

    def tick(self):
        self.reader._tick(self.deadline)

    def wait(self, events):
        self.tick()
        self.selector.register(self.sock,events)
        try:
            while True:
                self.tick()
                ready = self.selector.select(min(POLL_SECONDS,max(0,self.deadline-time.monotonic())))
                self.tick()
                if ready:
                    return
        finally:
            self.selector.unregister(self.sock)

    def connect(self):
        self.tick()
        address,endpoint = self.reader._address,self.reader._endpoint
        self.selector = selectors.DefaultSelector()
        self.raw = self.sock = socket.socket(socket.AF_INET6 if address.version == 6 else socket.AF_INET,
                                            socket.SOCK_STREAM)
        self.sock.setblocking(False)
        target = (str(address),endpoint.port,0,0) if address.version == 6 else (str(address),endpoint.port)
        result = self.sock.connect_ex(target)
        self.tick()
        need(result in (0,errno.EISCONN,errno.EINPROGRESS,errno.EWOULDBLOCK,errno.EALREADY),
             'http-connect-refused')
        if result not in (0,errno.EISCONN):
            self.wait(selectors.EVENT_WRITE)
            need(self.sock.getsockopt(socket.SOL_SOCKET,socket.SO_ERROR) == 0, 'http-connect-refused')
        self.tick()
        try:
            self.sock = self.reader._context.wrap_socket(self.raw,server_hostname=endpoint.host,
                                                        do_handshake_on_connect=False)
            self.sock.setblocking(False)
            while True:
                self.tick()
                try:
                    self.sock.do_handshake()
                    break
                except ssl.SSLWantReadError:
                    self.wait(selectors.EVENT_READ)
                except ssl.SSLWantWriteError:
                    self.wait(selectors.EVENT_WRITE)
            self.tick()
            need(self.sock.version() in ('TLSv1.2','TLSv1.3'), 'http-tls-refused')
        except ssl.SSLError:
            raise Refused('http-tls-refused') from None

    def send(self, data):
        remaining = memoryview(data)
        while remaining:
            self.tick()
            try:
                count = self.sock.send(remaining)
                need(count > 0, 'http-send-refused')
                remaining = remaining[count:]
            except ssl.SSLWantReadError:
                self.wait(selectors.EVENT_READ)
            except (ssl.SSLWantWriteError,BlockingIOError):
                self.wait(selectors.EVENT_WRITE)
            self.tick()

    def recv(self, count):
        # recv is attempted BEFORE select: already decrypted SSL.pending bytes
        # must not wait for a new socket event that may never arrive.
        while True:
            self.tick()
            try:
                data = self.sock.recv(count)
                self.tick()
                return data
            except ssl.SSLWantReadError:
                self.wait(selectors.EVENT_READ)
            except ssl.SSLWantWriteError:
                self.wait(selectors.EVENT_WRITE)
            except BlockingIOError:
                self.wait(selectors.EVENT_READ)
            except (ssl.SSLZeroReturnError,ssl.SSLEOFError):
                return b''

    def headers(self, expected_size, expected_etag):
        raw = bytearray()
        while not raw.endswith(b'\r\n\r\n'):
            need(len(raw) < HEADER_LIMIT, 'http-header-limit')
            data = self.recv(1)
            need(data != b'', 'http-header-truncated')
            raw.extend(data)
        lines = bytes(raw[:-4]).split(b'\r\n')
        need(re.fullmatch(rb'HTTP/1\.[01] 200(?: [\x20-\x7e]*)?',lines[0]) is not None,
             'http-status-refused')
        values = {}
        for line in lines[1:]:
            name,sep,value = line.partition(b':')
            need(sep and re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+",name) is not None
                 and all(32 <= c < 127 or c == 9 for c in value), 'http-header-profile')
            name,value = name.lower(),value.strip(b' \t')
            need(name not in values, 'http-header-duplicate')
            values[name] = value
        need(b'transfer-encoding' not in values and b'content-range' not in values
             and values.get(b'content-encoding',b'identity').lower() == b'identity', 'http-framing-refused')
        length = values.get(b'content-length')
        need(type(length) is bytes and re.fullmatch(rb'[0-9]{1,10}',length)
             and int(length) == expected_size, 'http-size-refused')
        need(expected_etag is None or values.get(b'etag') == expected_etag.encode('ascii'), 'http-etag-refused')

    def close(self):
        if self.closed:
            return
        failure = None
        try:
            self.tick()
        except BaseException as error:
            failure = error
        for resource in (self.sock,self.raw,self.selector):
            if resource is not None:
                try:
                    resource.close()
                except BaseException as error:
                    if failure is None:
                        failure = error if not isinstance(error,Exception) else Refused('http-close-refused')
        self.closed = True
        try:
            self.tick()
        except BaseException as error:
            if failure is None:
                failure = error
        if failure is not None:
            raise failure


class _Stream:
    def __init__(self, connection, remaining):
        self.connection,self.remaining = connection,remaining

    def __repr__(self):
        return '<HTTPStream private>'

    def read(self, n, deadline):
        need(type(n) is int and 0 < n <= 65536 and type(deadline) in (int,float)
             and deadline == self.connection.deadline and not self.connection.closed, 'http-read-profile')
        try:
            self.connection.tick()
            if self.remaining == 0:
                return b''  # Content-Length-framed EOF; no read(n+1)/TLS EOF probe.
            data = self.connection.recv(min(n,self.remaining))
            need(data != b'', 'http-body-truncated')
            self.remaining -= len(data)
            return data
        except Refused:
            raise
        except Exception:
            raise Refused('http-body-refused') from None
