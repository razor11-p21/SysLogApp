# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from syslogapp import services as s


class CollectionTests(unittest.TestCase):
    def test_journal_counts_events_not_message_lines(self):
        output = json.dumps({'PRIORITY': '4', 'MESSAGE': 'first\nsecond\nthird'}) + '\n'
        with patch.object(s, 'run_command', return_value=(0, output, '')) as run:
            self.assertEqual(s.journal_count('warning'), 1)
            self.assertIn('warning..warning', run.call_args.args[0])
            self.assertIn('json', run.call_args.args[0])

    def test_errors_include_critical_priorities(self):
        with patch.object(s, 'run_command', return_value=(0, '', '')) as run:
            self.assertEqual(s.journal_count('err'), 0)
            self.assertIn('emerg..err', run.call_args.args[0])

    def test_empty_success_is_a_valid_zero(self):
        with patch.object(s, 'run_command', return_value=(0, '', '')):
            self.assertEqual(s.failed_services(), [])
            self.assertEqual(s.journal_count(), 0)
            self.assertEqual(s.recent_issues(), [])

    def test_command_failures_are_not_healthy(self):
        for rc in (1, 124, 127):
            with self.subTest(rc=rc), patch.object(s, 'run_command', return_value=(rc, '', 'failed')):
                for check in (s.failed_services, s.journal_count, s.recent_issues, s.load_logs):
                    with self.assertRaises(s.CheckUnavailable):
                        check()

    def test_partial_journal_access_is_unavailable(self):
        for hint in ('Permission denied', 'Hint: You are currently not seeing messages from other users and the system.'):
            with self.subTest(hint=hint), patch.object(s, 'run_command', return_value=(0, '{}\n', hint)):
                with self.assertRaises(s.CheckUnavailable):
                    s.journal_count()

    def test_malformed_journal_data_is_unavailable(self):
        for output in ('not json', '[]', 'null'):
            with self.subTest(output=output), patch.object(s, 'run_command', return_value=(0, output, '')):
                with self.assertRaises(s.CheckUnavailable):
                    s.journal_count()

    def test_log_filters_preserve_literal_unit_names(self):
        with patch.object(s, 'run_command', return_value=(0, '', '')) as run:
            s.load_logs(limit=123, boot_only=True, priority='Warning', unit='json')
            args = run.call_args.args[0]
            self.assertEqual(args[args.index('-u') + 1], 'json')
            self.assertEqual(args[args.index('-p') + 1], 'warning..warning')
            self.assertIn('-b', args)
            self.assertIn('123', args)

    def test_recent_issues_include_emergency_and_current_boot(self):
        output = json.dumps({'PRIORITY': '0', 'MESSAGE': 'emergency'})
        with patch.object(s, 'run_command', return_value=(0, output, '')) as run:
            self.assertEqual(s.recent_issues()[0]['level'], 'Emergency')
            self.assertIn('emerg..warning', run.call_args.args[0])
            self.assertIn('-b', run.call_args.args[0])

    def test_diagnostics_report_incomplete_checks(self):
        with patch.object(s, 'run_command', return_value=(127, '', 'Missing command')), patch.object(s, 'psutil', None):
            result = {title: (state, detail) for state, title, detail in s.run_diagnostics()}
            for title in ('Failed services', 'Recent OOM kills', 'Journal errors (1h)', 'Memory pressure'):
                self.assertEqual(result[title][0], 'info')
                self.assertIn("Couldn't check", result[title][1])

    def test_oom_count_does_not_double_count_one_event(self):
        output = json.dumps({'MESSAGE': 'Out of memory: oom-kill detected'})
        with patch.object(s, 'run_command', return_value=(0, output, '')):
            result = {title: detail for _, title, detail in s.run_diagnostics()}
            self.assertEqual(result['Recent OOM kills'], '1 related messages today')

    def test_health_preserves_other_checks_after_failure(self):
        with patch.object(s, 'failed_services', side_effect=s.CheckUnavailable('systemctl failed')), \
             patch.object(s, 'network_status', return_value={'connected': True, 'dns': True}), \
             patch.object(s, 'journal_count', return_value=2), \
             patch.object(s, 'recent_issues', return_value=[]), \
             patch.object(s, 'run_diagnostics', return_value=[]):
            result = s.health_snapshot()
            self.assertIsNone(result['failed_services'])
            self.assertEqual(result['error_count'], 2)
            self.assertEqual(result['warning_count'], 2)
            self.assertIn('failed_services', result['check_errors'])

    def test_fast_metrics_do_not_run_commands_or_network_checks(self):
        with patch.object(s, 'run_command', side_effect=AssertionError('Slow command')), \
             patch.object(s.socket, 'getaddrinfo', side_effect=AssertionError('DNS lookup')):
            result = s.resource_snapshot()
            self.assertIn('cpu', result)
            self.assertNotIn('error_count', result)

    def test_missing_metrics_are_unknown_not_zero(self):
        psutil = SimpleNamespace(cpu_percent=lambda **kw: (_ for _ in ()).throw(OSError()),
                                 virtual_memory=lambda: (_ for _ in ()).throw(OSError()),
                                 swap_memory=lambda: (_ for _ in ()).throw(OSError()),
                                 disk_usage=lambda *args: (_ for _ in ()).throw(OSError()),
                                 boot_time=lambda: 0)
        with patch.object(s, 'psutil', psutil):
            result = s.resource_snapshot()
            for field in ('cpu', 'mem_pct', 'disk_pct', 'swap_used'):
                self.assertIsNone(result[field])

    def test_dns_lookup_has_a_deadline(self):
        with patch.object(s, 'run_command', return_value=(124, '', 'Command timed out')) as run:
            with self.assertRaises(s.CheckUnavailable):
                s.dns_available()
            self.assertEqual(run.call_args.kwargs['timeout'], 4)

    def test_missing_route_command_is_unknown_not_offline(self):
        with patch.object(s, 'run_command', return_value=(127, '', 'Command not found')):
            result = s.network_status()
            self.assertIsNone(result['connected'])
            self.assertEqual(result['route_error'], 'Command not found')


if __name__ == '__main__':
    unittest.main()
