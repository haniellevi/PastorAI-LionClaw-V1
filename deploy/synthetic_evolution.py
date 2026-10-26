"""Fake Evolution/Brevo endpoint for the synthetic transition rehearsal (no real provider).

Executed with ``python3 -c <this file>`` inside an owned container on the
rehearsal's internal network (alias ``evolution-api``), never with a host port.
Every request is counted in Redis db 2 (``synthetic:evo:effects``, field =
method + route class); db 0 (application) is never touched. ``sendText`` answers
201; while ``synthetic:evo:hold`` is set, the FIRST ``sendText`` publishes
``synthetic:evo:held`` and waits for ``synthetic:evo:release`` (bounded), so a
transport can be observed in flight. Phone numbers are not stored, only a
SHA-1 of the target per send (``synthetic:evo:sends``).
"""
import hashlib
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import redis

DB = redis.Redis.from_url(os.environ['SYNTHETIC_REDIS_URL'], decode_responses=True)
LOCK = threading.Lock()
SEND = re.compile(r'/message/sendText/[A-Za-z0-9_.-]+')


def route(method, path):
    path = path.split('?', 1)[0]
    if SEND.fullmatch(path):
        return method + ' sendText'
    if path.startswith('/brevo/'):
        return method + ' brevo'
    return method + ' ' + (path.strip('/').split('/', 1)[0] or 'root')


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):  # no request lines (they could carry identifiers)
        return

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_any(self, method):
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b''
        kind = route(method, self.path)
        if kind == 'POST sendText':
            with LOCK:
                hold = DB.get('synthetic:evo:hold') == '1' and not DB.exists('synthetic:evo:held')
                if hold:
                    DB.set('synthetic:evo:held', '1')
            if hold:
                limit = time.monotonic() + 120
                while DB.get('synthetic:evo:release') != '1' and time.monotonic() < limit:
                    time.sleep(0.05)
            try:
                number = str(json.loads(raw or b'{}').get('number', ''))
            except ValueError:
                number = ''
            DB.rpush('synthetic:evo:sends', hashlib.sha1(number.encode()).hexdigest())
            DB.hincrby('synthetic:evo:effects', kind, 1)
            self.reply(201, {'key': {'id': 'synthetic-' + str(DB.hget('synthetic:evo:effects', kind))},
                             'status': 'PENDING'})
            return
        DB.hincrby('synthetic:evo:effects', kind, 1)
        if kind == 'GET root' and DB.get('synthetic:evo:fail-root') == '1':
            self.reply(503, {'status': 503, 'synthetic': True})  # induced provider outage (readiness)
            return
        self.reply(200, {'status': 200, 'synthetic': True})

    def do_GET(self):
        self.handle_any('GET')

    def do_POST(self):
        self.handle_any('POST')

    def do_PUT(self):
        self.handle_any('PUT')

    def do_DELETE(self):
        self.handle_any('DELETE')


server = ThreadingHTTPServer(('0.0.0.0', 8080), Handler)
DB.incr('synthetic:evo:boots')
server.serve_forever()
