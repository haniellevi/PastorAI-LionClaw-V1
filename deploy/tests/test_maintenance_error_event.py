import json
import re
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from initial_transition_ops import emit_error_event, format_error_event


class EventTest(unittest.TestCase):
    def test_event_has_fixed_fields_and_random_correlation(self):
        first = json.loads(format_error_event(ValueError('secret-marker'), 'transition'))
        second = json.loads(format_error_event(ValueError('secret-marker'), 'transition'))
        assert set(first) == {'class', 'stage', 'correlation'}
        assert first['class'] == 'value_error'
        assert first['stage'] == 'transition'
        assert re.fullmatch(r'[0-9a-f]{32}', first['correlation'])
        assert first['correlation'] != second['correlation']
        assert 'secret-marker' not in json.dumps(first)

    def test_unknown_values_and_exception_representation_do_not_leak(self):
        class SensitiveError(Exception):
            def __str__(self):
                raise AssertionError('must not stringify exception')

        event = json.loads(format_error_event(SensitiveError('secret-marker'), 'secret-stage'))
        assert event['class'] == 'other'
        assert event['stage'] == 'other'
        assert 'secret' not in json.dumps(event)

    def test_emission_failure_is_ignored(self):
        with patch('initial_transition_ops.format_error_event', side_effect=OSError('sensitive')):
            self.assertIsNone(emit_error_event(ValueError('sensitive'), 'cli'))

    def test_stderr_write_failure_is_ignored(self):
        with patch('initial_transition_ops.sys.stderr') as stderr:
            stderr.write.side_effect = OSError('sensitive')
            self.assertIsNone(emit_error_event(ValueError('sensitive'), 'cli'))
            self.assertTrue(stderr.write.called)
