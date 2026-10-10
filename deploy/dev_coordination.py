"""One filesystem mutex for DEV promotion, reset and manual acceptance.

This prepares local coordination only. The executor remains responsible for
nominal environment checks, migration, seed, readiness and provider containment.
No network, shell commands, provisioning or production action exists here.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class DevCoordinationError(ValueError):
    pass


def package_id(package: dict) -> str:
    required = {'sha', 'backend_digest', 'frontend_sha', 'frontend_digest', 'frontend_origin', 'api_origin', 'schema', 'seed', 'sequence', 'environment'}
    if type(package) is not dict or set(package) != required or package['environment'] != 'dev-sintetico':
        raise DevCoordinationError('invalid DEV package')
    if any(type(package[key]) is not str for key in required - {'sequence'}):
        raise DevCoordinationError('invalid package field type')
    if not re.fullmatch('[0-9a-f]{40}', package['sha']) or package['frontend_sha'] != package['sha']:
        raise DevCoordinationError('backend/frontend revision mismatch')
    if any(not re.fullmatch('sha256:[0-9a-f]{64}', package[key]) for key in ('backend_digest', 'frontend_digest')):
        raise DevCoordinationError('immutable backend/frontend digests required')
    if not re.fullmatch('[0-9a-f]{64}', package['schema']):
        raise DevCoordinationError('schema receipt required')
    if not re.fullmatch('[A-Za-z0-9_.-]{1,80}', package['seed']):
        raise DevCoordinationError('synthetic seed version required')
    if type(package['sequence']) is not int or package['sequence'] < 1:
        raise DevCoordinationError('monotonic integration sequence required')
    from urllib.parse import urlsplit
    for key in ('frontend_origin', 'api_origin'):
        target = urlsplit(package[key])
        if target.scheme != 'https' or not target.hostname or target.username or target.password or target.query or target.fragment or target.path not in ('', '/'):
            raise DevCoordinationError('DEV frontend origin required')
        try:
            if target.port not in (None, 443):
                raise ValueError
        except ValueError:
            raise DevCoordinationError('invalid DEV frontend port') from None
        if target.hostname == 'igreja12.com.br' or target.hostname.endswith('.igreja12.com.br'):
            raise DevCoordinationError('production identity refused')
    return hashlib.sha256(json.dumps(package, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class DevCoordinator:
    def __init__(self, directory: Path, *, clock=time.time):
        self.directory, self.clock = Path(directory), clock
        self.directory.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self):
        with (self.directory / 'pipeline.lock').open('a+') as mutex:
            fcntl.flock(mutex, fcntl.LOCK_EX)
            path = self.directory / 'state.json'
            state = json.loads(path.read_text()) if path.exists() else {'package': None, 'reservation': None, 'receipts': {}, 'invalidated': {}, 'recovery_required': False}
            yield state
            self._write(state)

    def _write(self, state):
        path = self.directory / 'state.json'
        fd, temporary = tempfile.mkstemp(dir=self.directory, prefix='state-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as file:
                json.dump(state, file, sort_keys=True)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(self.directory, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _expire(self, state):
        reservation = state['reservation']
        if reservation and reservation['expires_at'] <= self.clock():
            state['invalidated'][reservation['token']] = 'expired'
            state['reservation'] = None

    def transition(self, package, *, operation, execute):
        """Hold the same mutex throughout deploy/reset. Commit no false success.

        execute receives only the reviewed package, and must finish all physical
        steps and readiness before returning. Failure marks recovery required;
        the previous receipt is retained, without claiming it remains deployed.
        """
        identity = package_id(package)
        if operation not in {'deploy', 'reset'}:
            raise DevCoordinationError('invalid DEV operation')
        error = None
        with self._locked() as state:
            self._expire(state)
            if state['recovery_required']:
                raise DevCoordinationError('recovery proof required')
            if state['reservation']:
                if operation == 'deploy':
                    raise DevCoordinationError('manual acceptance reserved')
                reservation = state['reservation']
                state['invalidated'][reservation['token']] = 'reset'
                state['reservation'] = None
            current = state['package']
            if current:
                if package['sequence'] < current['sequence']:
                    raise DevCoordinationError('older or conflicting candidate refused')
                if operation == 'reset':
                    if package['seed'] == current['seed'] or any(
                        package[key] != current[key] for key in package if key != 'seed'
                    ):
                        raise DevCoordinationError('reset requires current package and new synthetic seed version')
                elif package['sequence'] == current['sequence'] and package_id(current) != identity:
                    raise DevCoordinationError('older or conflicting candidate refused')
            # Persist uncertainty before the first physical effect. SIGKILL,
            # host failure or runner cancellation cannot leave a false healthy
            # previous-package receipt when the filesystem mutex is released.
            state['recovery_required'] = True
            state['failed_candidate'] = identity
            self._write(state)
            try:
                execute(dict(package))
            except BaseException as exc:
                state['recovery_required'] = True
                state['failed_candidate'] = identity
                error = exc
            else:
                state['package'] = dict(package)
                state['recovery_required'] = False
                state.pop('failed_candidate', None)
        if error is not None:
            raise error

    def record_recovery(self, package, *, verify):
        """Separate recovery evidence; no automatic rollback or database restore."""
        package_id(package)
        with self._locked() as state:
            if not state['recovery_required']:
                raise DevCoordinationError('no recovery pending')
            if verify(dict(package)) is not True:
                raise DevCoordinationError('recovery not proven')
            state['package'] = dict(package)
            state['recovery_required'] = False
            state.pop('failed_candidate', None)

    def reserve(self, *, owner, ttl=1800):
        if not re.fullmatch('[A-Za-z0-9_.-]{1,80}', owner) or type(ttl) is not int or not 1 <= ttl <= 3600:
            raise DevCoordinationError('invalid reservation owner or duration')
        with self._locked() as state:
            self._expire(state)
            if state['recovery_required'] or not state['package'] or state['reservation']:
                raise DevCoordinationError('DEV unavailable for acceptance')
            token = uuid.uuid4().hex
            state['reservation'] = {'token': token, 'owner': owner,
                'package': package_id(state['package']), 'expires_at': self.clock() + ttl}
        return token

    def finish(self, *, token, owner):
        error = None
        with self._locked() as state:
            self._expire(state)
            reservation = state['reservation']
            if not reservation or reservation['token'] != token or reservation['owner'] != owner:
                error = DevCoordinationError('reservation absent, expired or owned by another user')
            elif state['recovery_required'] or reservation['package'] != package_id(state['package']):
                error = DevCoordinationError('package changed during acceptance')
            else:
                state['receipts'][token] = {'owner': owner, 'package': reservation['package'], 'completed_at': self.clock()}
                state['reservation'] = None
        if error:
            raise error
        return token
