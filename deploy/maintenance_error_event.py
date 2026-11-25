"""Sanitized, best-effort diagnostics for generic maintenance refusals.

The random identifier is per event and does not correlate events. Exceptions
converted at earlier boundaries can no longer reveal their original class.
"""
import json
import secrets
import sys

_CLASSES = {ValueError: 'value_error', TypeError: 'type_error', OSError: 'os_error',
            RuntimeError: 'runtime_error'}
_STAGES = frozenset({'transition', 'resume', 'cli'})


def format_event(exc, stage):
    return json.dumps({'class': _CLASSES.get(type(exc), 'other'),
                       'stage': stage if stage in _STAGES else 'other',
                       'correlation': secrets.token_hex(16)}, sort_keys=True)


def emit_event(exc, stage):
    try:
        print(format_event(exc, stage), file=sys.stderr)
    except BaseException:
        pass
