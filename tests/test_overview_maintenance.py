# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from syslogapp import overview, maintenance


class OverviewTests(unittest.TestCase):
    def test_real_snapshot_has_expected_fields(self):
        data = overview.snapshot()
        names = [row[0] for row in data['rows']]
        self.assertIn('Memory', names)
        self.assertIn('Root filesystem', names)
        self.assertIn('Load · 1 / 5 / 15 min', names)
        self.assertTrue(data['time'])

    def test_unavailable_data_is_explicit(self):
        with patch.object(overview, 'read_text', side_effect=OSError('restricted')):
            rows = dict((name, value) for name, value, _ in overview.snapshot()['rows'])
        for name in ('System', 'Memory', 'Swap', 'Uptime', 'CPU'):
            self.assertIn('Unavailable', rows[name])


class MaintenanceTests(unittest.TestCase):
    def test_optional_program_disables_action(self):
        with patch.object(maintenance.shutil, 'which', return_value=None):
            args, reason = maintenance.resolve(maintenance.ACTIONS[2])
        self.assertIsNone(args)
        self.assertIn('apt-get', reason)

    def test_elevation_is_absolute_and_not_a_shell(self):
        with patch.object(maintenance.shutil, 'which', side_effect=lambda name: '/usr/bin/' + name):
            args, _ = maintenance.resolve(maintenance.ACTIONS[-1])
        self.assertEqual(args, ['/usr/bin/pkexec', '/usr/bin/dpkg', '--configure', '-a'])

    def test_output_tail_and_exit_status(self):
        code, output = maintenance.run_action([sys.executable, '-c',
            'import sys; print("x" * 200000); print("last"); sys.exit(7)'])
        self.assertEqual(code, 7)
        self.assertLess(len(output), 132000)
        self.assertIn('Earlier output omitted', output)
        self.assertTrue(output.endswith('last\n'))

    def test_no_administrative_timeout_or_interactive_stdin(self):
        process = Mock()
        process.wait.return_value = 0
        with patch.object(maintenance.subprocess, 'Popen', return_value=process) as popen:
            maintenance.run_action(['/usr/bin/dpkg', '--configure', '-a'])
        process.wait.assert_called_once_with()
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        self.assertEqual(popen.call_args.kwargs['stdin'], maintenance.subprocess.DEVNULL)

    def test_read_only_action_is_bounded(self):
        from syslogapp import network
        with patch.object(network, 'capture', return_value=('usage', False)) as capture:
            self.assertEqual(maintenance.run_action(['journalctl', '--disk-usage'], False), (0, 'usage'))
        self.assertEqual(capture.call_args.kwargs['timeout'], 5)

    def test_cancel_and_busy_never_start_worker(self):
        from syslogapp.pages.maintenance import MaintenancePage
        page = SimpleNamespace(_busy=False, _destroyed=False, _confirm=Mock(return_value=False))
        with patch('syslogapp.pages.maintenance.resolve', return_value=(['pkexec', 'cmd'], '')), \
             patch('syslogapp.pages.maintenance.threading.Thread') as thread:
            MaintenancePage._run_action(page, maintenance.ACTIONS[1])
            thread.assert_not_called()
            page._busy = True
            page._confirm.reset_mock()
            MaintenancePage._run_action(page, maintenance.ACTIONS[1])
            page._confirm.assert_not_called()

    def test_worker_completes_via_main_loop_without_snapshot_executor(self):
        from syslogapp.pages.maintenance import MaintenancePage
        page = SimpleNamespace(_destroyed=False, app=SimpleNamespace(_closing=False), _done=Mock())
        with patch('syslogapp.pages.maintenance.run_action', return_value=(0, 'done')), \
             patch('syslogapp.pages.maintenance.GLib.idle_add') as idle:
            MaintenancePage._worker(page, maintenance.ACTIONS[0], ['journalctl'])
        idle.assert_called_once_with(page._done, maintenance.ACTIONS[0], (0, 'done'), None)

    def test_completion_recovers_after_failure_and_cancel(self):
        from syslogapp.pages.maintenance import MaintenancePage
        page = SimpleNamespace(_destroyed=False, _busy=True, _refresh_clicked=Mock(),
                               status=Mock(), output=Mock())
        MaintenancePage._done(page, maintenance.ACTIONS[1], (126, 'cancelled'), None)
        self.assertFalse(page._busy)
        self.assertIn('cancelled', page.status.set_text.call_args.args[0])
        page._busy = True
        MaintenancePage._done(page, maintenance.ACTIONS[1], None, RuntimeError('failed'))
        self.assertFalse(page._busy)
        page.output.get_buffer().set_text.assert_called_with('failed')


class OverviewLifecycleTests(unittest.TestCase):
    def test_first_map_only_and_no_overlapping_reads(self):
        from syslogapp.pages.overview import OverviewPage
        page = SimpleNamespace(_loaded_once=False, _refresh_clicked=Mock())
        OverviewPage._mapped(page)
        OverviewPage._mapped(page)
        page._refresh_clicked.assert_called_once_with()
        page = SimpleNamespace(_busy=False, _destroyed=False, host=None, refresh_btn=Mock(),
                               status=Mock(), app=Mock(), _done=Mock(), _text='')
        OverviewPage._refresh_clicked(page)
        OverviewPage._refresh_clicked(page)
        page.app.run_async.assert_called_once()
        self.assertTrue(page._busy)
