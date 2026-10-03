# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from syslogapp import services
try:
    from syslogapp.pages import maintenance
    HAS_GTK = True
except ImportError:
    HAS_GTK = False


class MaintenanceProcessTests(unittest.TestCase):
    def test_collects_stdout_stderr_and_exit_code(self):
        result = services.run_maintenance_command([sys.executable, '-c', 'import sys; print("out"); print("err", file=sys.stderr); sys.exit(7)'])
        self.assertEqual(result[0], 7)
        self.assertIn('out', result[1])
        self.assertIn('err', result[1])

    def test_large_output_is_bounded(self):
        result = services.run_maintenance_command([sys.executable, '-c', 'print("x" * (2 * 1024 * 1024)); print("final line")'])
        self.assertEqual(result[0], 0)
        self.assertIn('Earlier output omitted', result[1])
        self.assertTrue(result[1].endswith('final line\n'))
        self.assertLess(len(result[1]), 1024 * 1024 + 100)

    def test_runner_detaches_and_waits_without_timeout(self):
        process = Mock()
        process.wait.return_value = 0
        with patch.object(services.subprocess, 'Popen', return_value=process) as popen:
            services.run_maintenance_command(['/usr/bin/dpkg', '--configure', '-a'])
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        self.assertEqual(popen.call_args.kwargs['stdin'], services.subprocess.DEVNULL)
        process.wait.assert_called_once_with()


@unittest.skipUnless(HAS_GTK, 'GTK bindings unavailable')
class MaintenanceBehaviorTests(unittest.TestCase):
    def page(self):
        return SimpleNamespace(_busy=False, _buttons=[(Mock(), True), (Mock(), False)],
                               app=Mock(), _output_dialog=Mock(), _done=Mock())

    def test_administrative_action_has_no_fixed_timeout(self):
        page = self.page()
        with patch.object(maintenance, 'confirm_dialog', return_value=True), \
             patch.object(maintenance.shutil, 'which', side_effect=lambda cmd: '/usr/bin/' + cmd), \
             patch.object(maintenance, 'run_maintenance_command', return_value=(0, '', '')) as run:
            maintenance.MaintenancePage._run_action(page, 'Recover', 'Recover packages', ['dpkg', '--configure', '-a'], True)
            page.app.run_async.call_args.args[0]()
        run.assert_called_once_with(['/usr/bin/pkexec', '/usr/bin/dpkg', '--configure', '-a'])
        self.assertTrue(page._busy)
        for button, _ in page._buttons:
            button.set_sensitive.assert_called_with(False)

    def test_busy_action_cannot_overlap(self):
        page = self.page()
        page._busy = True
        with patch.object(maintenance, 'confirm_dialog') as confirm:
            maintenance.MaintenancePage._run_action(page, 'Recover', '', ['dpkg'], True)
        confirm.assert_not_called()
        page.app.run_async.assert_not_called()

    def test_completion_restores_only_available_actions(self):
        page = self.page()
        page._busy = True
        maintenance.MaintenancePage._done(page, 'Recover', (0, 'out', 'err'), None)
        self.assertFalse(page._busy)
        page._buttons[0][0].set_sensitive.assert_called_with(True)
        page._buttons[1][0].set_sensitive.assert_called_with(False)
        page._output_dialog.assert_called_with('Recover', 'out\nerr')

    def test_error_releases_busy_state(self):
        page = self.page()
        page._busy = True
        maintenance.MaintenancePage._done(page, 'Recover', None, RuntimeError('failed'))
        self.assertFalse(page._busy)
        page._output_dialog.assert_not_called()
