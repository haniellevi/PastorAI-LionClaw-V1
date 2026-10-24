#!/usr/bin/env python3
"""Processos SIMULADOS do ensaio de contenção; não são os workers da aplicação.

Executado dentro de containers descartáveis criados por
``rehearse_legacy_containment.py``, que entrega este código por
``--entrypoint python3 ... -c``, sem montagem do host nem credencial. A
semântica é deliberadamente mínima: fila Redis pendente/em curso, provedor
falso com barreira, que conta o efeito na chegada e só responde quando a
barreira é liberada, e SIGTERM gracioso. Não reproduz retries, timeouts,
tratamento de sinal nem outro comportamento dos workers reais (por exemplo,
de ``07a3f4d``).
"""
import json
import os
import signal
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

CONSUMERS = {'queue-worker': 'queue', 'broadcast-worker': 'broadcast'}
EFFECTS = 'synthetic:provider:effects'
ARRIVED = 'synthetic:provider:arrived'
HOLD = 'synthetic:provider:hold'
SCHEDULED = 'synthetic:cron:scheduled'


def key(kind, state):
    return f'synthetic:{kind}:{state}'


class Redis:
    """Cliente RESP mínimo, só biblioteca padrão."""

    def __init__(self, host='redis', port=6379):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.file = self.sock.makefile('rb')

    def command(self, *args):
        parts = [str(arg).encode() for arg in args]
        payload = b'*%d\r\n' % len(parts) + b''.join(b'$%d\r\n%s\r\n' % (len(p), p) for p in parts)
        self.sock.sendall(payload)
        return self._read()

    def _read(self):
        line = self.file.readline()
        if not line:
            raise ConnectionError('redis closed')
        prefix, body = line[:1], line[1:-2]
        if prefix == b'+':
            return body.decode()
        if prefix == b'-':
            raise RuntimeError('redis error')
        if prefix == b':':
            return int(body)
        if prefix == b'$':
            size = int(body)
            return None if size < 0 else self.file.read(size + 2)[:-2].decode()
        if prefix == b'*':
            size = int(body)
            return None if size < 0 else [self._read() for _ in range(size)]
        raise RuntimeError('unexpected redis reply')


def quarantine_in_flight(redis, kind):
    """Item ainda em curso numa partida tem efeito ambíguo: revisão, nunca reenvio."""
    moved = 0
    while redis.command('LMOVE', key(kind, 'processing'), key(kind, 'ambiguous'), 'LEFT', 'RIGHT') is not None:
        moved += 1
    return moved


def process_one(redis, kind, *, send, now, gate_open, timeout=1):
    if not gate_open:
        return 'gated'
    raw = redis.command('BLMOVE', key(kind, 'pending'), key(kind, 'processing'), 'LEFT', 'RIGHT', timeout)
    if raw is None:
        return 'idle'
    item = json.loads(raw)
    if item['deadline'] <= now():
        # Expira sem reescrever o item nem o prazo.
        outcome = 'expired'
    else:
        try:
            send(item['key'])
            outcome = 'done'
        except Exception:  # noqa: BLE001 - sem resposta, o efeito pode ter ocorrido
            # Nenhum retry: o item vai para revisão humana.
            outcome = 'ambiguous'
    redis.command('RPUSH', key(kind, outcome), raw)
    redis.command('LREM', key(kind, 'processing'), 1, raw)
    return outcome


def promote_due(redis, now):
    """Cron simulado: move agendados vencidos para a fila, sem alterar o item."""
    moved = 0
    for raw in redis.command('LRANGE', SCHEDULED, 0, -1) or []:
        if json.loads(raw)['due'] <= now() and redis.command('LREM', SCHEDULED, 1, raw) == 1:
            redis.command('RPUSH', key('queue', 'pending'), raw)
            moved += 1
    return moved


def hold_until_released(redis, *, sleep=time.sleep, polls=600):
    """Barreira do provedor: espera enquanto ``HOLD`` existir, até ``polls`` x 0,1 s."""
    for _ in range(polls):
        if redis.command('EXISTS', HOLD) != 1:
            return True
        sleep(0.1)
    return False


def gate_open(role, env=os.environ):
    sends = env.get('SYNTHETIC_ALLOW_REAL_SENDS') == 'true'
    if role == 'broadcast-worker':
        return sends and env.get('SYNTHETIC_BROADCAST_ASYNC_ENABLED') == 'true'
    return sends


class Stop:
    def __init__(self, ignore_term):
        self.requested = threading.Event()
        handler = signal.SIG_IGN if ignore_term else (lambda *_: self.requested.set())
        signal.signal(signal.SIGTERM, handler)

    def wait(self):
        while not self.requested.wait(0.2):
            pass


def _sender(timeout_s):
    def send(item_key):
        request = Request('http://provider:8080/effect', data=json.dumps({'key': item_key}).encode(),
                          method='POST', headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=timeout_s) as response:
            if response.status != 200:
                raise RuntimeError('provider refused')
    return send


def _handler(role):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def _reply(self, status):
            try:
                self.send_response(status)
                self.end_headers()
            except OSError:
                pass  # cliente já desistiu (resposta que não chega)

        def do_GET(self):
            self._reply(200 if self.path == '/ready' else 404)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            redis = Redis()
            if role == 'backend' and self.path == '/webhook':
                item = {'key': str(body['key']), 'deadline': float(body['deadline'])}
                redis.command('RPUSH', key('queue', 'pending'), json.dumps(item, separators=(',', ':'), sort_keys=True))
                self._reply(202)
            elif role == 'provider' and self.path == '/effect':
                # O efeito acontece na chegada; a resposta depende da barreira.
                redis.command('HINCRBY', EFFECTS, str(body['key']), 1)
                redis.command('INCR', ARRIVED)
                hold_until_released(redis)
                self._reply(200)
            else:
                self._reply(404)
    return Handler


def connect(attempts=60):
    for _ in range(attempts):
        try:
            return Redis()
        except OSError:
            time.sleep(0.5)
    raise ConnectionError('redis unavailable')


def main(role):
    stop = Stop(os.environ.get('SYNTHETIC_IGNORE_TERM') == '1')
    redis = connect()
    if role in ('backend', 'provider'):
        server = ThreadingHTTPServer(('0.0.0.0', 8000 if role == 'backend' else 8080), _handler(role))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        # Pronto só depois de escutar: o controlador espera este marcador.
        redis.command('INCR', f'synthetic:boots:{role}')
        stop.wait()
        server.shutdown()
        server.server_close()
    elif role in CONSUMERS:
        kind = CONSUMERS[role]
        quarantine_in_flight(redis, kind)
        redis.command('INCR', f'synthetic:boots:{role}')
        send = _sender(float(os.environ.get('SYNTHETIC_PROVIDER_TIMEOUT_S', '15')))
        # Um item por vez: enquanto um envio está em curso, nada mais é consumido.
        while not stop.requested.is_set():
            if process_one(redis, kind, send=send, now=time.time, gate_open=gate_open(role)) == 'gated':
                stop.requested.wait(0.5)
    elif role == 'cron-worker':
        redis.command('INCR', f'synthetic:boots:{role}')
        while not stop.requested.is_set():
            promote_due(redis, time.time)
            stop.requested.wait(0.5)
    elif role == 'intruder':
        # Quinto writer do ensaio: escreve na fila sem pertencer ao conjunto.
        while not stop.requested.is_set():
            redis.command('RPUSH', key('queue', 'pending'), json.dumps({'key': 'intruder', 'deadline': 0}))
            stop.requested.wait(0.5)
    else:
        sys.exit(2)
    sys.exit(0)


if __name__ == '__main__':
    main(sys.argv[1])
