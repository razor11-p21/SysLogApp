# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import json
import unittest
from unittest.mock import patch
from syslogapp import services as s
from syslogapp.config import log_capacity


class JournalTests(unittest.TestCase):
    def test_exact_severity_and_literal_unit(self):
        for label, expected in [('Error', 'err..err'), ('Warning', 'warning..warning'),
                                ('Critical', 'emerg..crit')]:
            with patch.object(s, 'run_command', return_value=(0, '', '')) as run:
                s.load_logs(400, True, label, 'json')
                args = run.call_args.args[0]
                self.assertEqual(args[args.index('-p') + 1], expected)
                self.assertEqual(args[args.index('-u') + 1], 'json')

    def test_failures_are_not_empty_success(self):
        for rc, output, error in [(1, '', 'failed'), (0, 'not json', ''), (0, '[]', ''),
                                   (0, '{}', 'Permission denied')]:
            with patch.object(s, 'run_command', return_value=(rc, output, error)):
                with self.assertRaises(s.CheckUnavailable):
                    s.load_logs()

    def test_record_preserves_multiline_message_and_cursor(self):
        record = {'MESSAGE': 'first\nsecond', 'PRIORITY': '3', '__CURSOR': 'test-cursor'}
        with patch.object(s, 'run_command', return_value=(0, json.dumps(record), '')):
            rows = s.load_logs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['message'], 'first second')
        self.assertEqual(rows[0]['raw'], record)

    def test_empty_success_is_valid(self):
        with patch.object(s, 'run_command', return_value=(0, '', '')):
            self.assertEqual(s.load_logs(), [])

    def test_capacity_is_bounded_even_with_old_or_invalid_settings(self):
        for value, expected in [(None, 400), ('bad', 400), (100000, 2000), (-1, 100), (600, 600)]:
            self.assertEqual(log_capacity({'log_lines': value}), expected)

    def test_queries_limit_rows_and_select_only_needed_fields(self):
        with patch.object(s, 'run_command', return_value=(0, '', '')) as run:
            s.load_logs(999999)
        args = run.call_args.args[0]
        self.assertEqual(args[args.index('-n') + 1], '2000')
        self.assertTrue(any(arg.startswith('--output-fields=') for arg in args))
