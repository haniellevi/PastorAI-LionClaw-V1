"""Operator entry point of the first-transition window (A8) on the protected host.

Modes (``python -I first_transition_window.py <mode> ...``), none of which writes to the
source database:

* ``check``: loads the public configuration, prepares the pinned plan from the local repo
  and takes two fresh read-only observations; prints aggregates and the identity/ledger/
  catalog checks only;
* ``rehearse-backup``: runs the window backup provider with a REHEARSAL request (never
  journaled, so its receipt can never attest a window): fresh dump, isolated clone restore
  and replay of the pending migrations; prints the sanitized receipt;
* ``check-bindings``: observes both ingress entries and the unknown-writer count through the
  host bindings (first_transition_window_bindings); blocks or opens nothing;
* ``run``: refused (``window-bindings-pending``) until the window is wired to the bindings.

The source URL is read from a root-only env file by name (``DATABASE_URL``) inside the
process, never printed, logged or put in argv. Output is aggregates and fixed codes only.
Nothing runs at import.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys

import first_transition_database as fdb
from first_transition_adapter import prepare
from first_transition_orchestrator import load_config
from first_transition_window_backup import REHEARSAL_SCHEMA, WindowBackup, WindowBackupConfig
from first_transition_window_bindings import bindings_from_dict
from initial_transition_files import read_regular
from initial_transition_ops import Refused, require

ENV_NAME = re.compile(r'[A-Z_][A-Z0-9_]{0,62}')


def env_file_secret(path, name='DATABASE_URL'):
    """``secret()`` reading ONE variable of a root-only (0600) env file on every call.

    The file must be a regular file without group/other permissions; the variable must
    appear exactly once with a postgresql:// value. The value never leaves the returned call.
    """
    require(isinstance(path, str) and os.path.isabs(path) and ENV_NAME.fullmatch(name), 'window-env-file')

    def secret():
        # Own reader on purpose: the packaging reader refuses .env paths, which is right for artifacts.
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            raise Refused('window-env-file') from None
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            require(stat.S_ISREG(info.st_mode) and not info.st_mode & 0o077 and info.st_size <= 256 * 1024,
                    'window-env-file-mode')
            text = handle.read(256 * 1024 + 1).decode('utf-8')
        values = []
        for line in text.splitlines():
            match = re.match(r'\s*(?:export\s+)?' + name + r'\s*=(.*)', line)
            if match:
                values.append(match.group(1).strip().strip('"\''))
        require(len(values) == 1 and values[0].startswith('postgresql://') and '\n' not in values[0],
                'window-env-secret')
        return values[0]
    return secret


def _load(args):
    config = load_config(Path(args.config))
    plan = prepare(Path(config.repo))
    expected = fdb.DatabaseExpectation(config.identity, plan.baseline, config.catalog).validated()
    secret = env_file_secret(args.env_file)
    database = fdb.ReadOnlyDatabase(fdb.psycopg2_connector(secret), lease_columns=config.lease_columns,
                                    observer_applications=config.observer_applications)
    return config, plan, expected, secret, database


def check(args, out=print):
    config, plan, expected, _, database = _load(args)
    out(json.dumps(dict(plan_digest=plan.digest, baseline=len(plan.baseline), pending=len(plan.pending))))
    results = []
    for attempt in (1, 2):
        observation = database.observe(timeout=dict(config.timeouts).get('observe_s', 10))
        checks = {}
        for label, function in (('same_database', fdb.require_same_database), ('ddl_free', fdb.require_ddl_free)):
            try:
                function(observation, expected)
                checks[label] = 'ok'
            except Refused as exc:
                checks[label] = str(exc)
        try:
            fdb.require_quiet(observation)
            checks['quiet'] = 'ok'
        except Refused as exc:
            checks['quiet'] = str(exc)
        results.append(checks)
        out(json.dumps(dict(observation=attempt, summary=fdb.summary(observation), checks=checks), sort_keys=True))
    return 0 if all(c['same_database'] == 'ok' and c['ddl_free'] == 'ok' for c in results) else 1


def rehearse_backup(args, out=print):
    config, plan, expected, secret, database = _load(args)
    backup_config = WindowBackupConfig.from_dict(json.loads(read_regular(Path(args.backup_config), 64 * 1024)))
    observation = database.observe(timeout=dict(config.timeouts).get('observe_s', 10))
    fdb.require_ddl_free(observation, expected)
    request = dict(schema=REHEARSAL_SCHEMA, nonce=secrets.token_hex(32), plan_digest=plan.digest,
                   source_identity=expected.identity, baseline_digest=expected.baseline_digest)
    receipt = WindowBackup(backup_config, plan, expected, secret=secret, connect=database.connect)(request)
    out(json.dumps(receipt, sort_keys=True, indent=1))
    return 0


def check_bindings(args, out=print):
    config, _, _, secret, database = _load(args)
    data = json.loads(read_regular(Path(args.bindings_config), 64 * 1024))
    ingress, writers = bindings_from_dict(data, secret=secret, connect=database.connect)
    timeout = dict(config.timeouts).get('observe_s', 10)
    result = {}
    for name, binding in (*ingress.items(), ('unknown_writers', writers)):
        try:
            result[name] = binding.observe(binding.scope, timeout=timeout)
        except Refused as exc:
            result[name] = 'refused:' + str(exc)
        except Exception:
            result[name] = 'refused:window-binding-failed'
    out(json.dumps(result, sort_keys=True))
    return 0 if all(type(v) is int or not v.startswith('refused:') for v in result.values()) else 1


def main(argv=None, out=print):
    parser = argparse.ArgumentParser(prog='first_transition_window')
    parser.add_argument('mode', choices=('check', 'rehearse-backup', 'check-bindings', 'run'))
    parser.add_argument('--config', required=True)
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--backup-config')
    parser.add_argument('--bindings-config')
    args = parser.parse_args(argv)
    try:
        if args.mode == 'check':
            return check(args, out)
        if args.mode == 'rehearse-backup':
            require(args.backup_config is not None, 'window-backup-config-missing')
            return rehearse_backup(args, out)
        if args.mode == 'check-bindings':
            require(args.bindings_config is not None, 'window-bindings-config-missing')
            return check_bindings(args, out)
        raise Refused('window-bindings-pending')
    except Refused as exc:
        out(json.dumps(dict(refused=str(exc))))
        return 2
    except Exception:
        # Driver/library messages may name hosts or roles: only a fixed code leaves the process.
        out(json.dumps(dict(refused='window-failed')))
        return 2


if __name__ == '__main__':
    sys.exit(main())
