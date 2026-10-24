# SPDX-License-Identifier: GPL-3.0-or-later
import tempfile
import sys
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from syslogapp.pages.maintenance import MaintenancePage
from syslogapp.maintenance import ACTIONS, Action
from syslogapp.hosts import HostContext


@unittest.skipUnless(Gtk.init_check()[0], 'No GTK desktop display')
class MaintenanceUITests(unittest.TestCase):
    def setUp(self):
        self.app = SimpleNamespace(config={}, run_async=Mock(), _closing=False, window=SimpleNamespace(toast=Mock()))
        self.page = MaintenancePage(self.app)

    def tearDown(self):
        self.page.destroy()

    def test_layout_is_split_advanced_collapsed_and_missing_tools_have_inline_reason(self):
        self.assertFalse(self.page.advanced.get_expanded())
        self.assertIsNotNone(self.page.split.get_child1())
        self.assertIsNotNone(self.page.split.get_child2())
        self.assertFalse(self.page.output.get_editable())
        with patch.object(self.page, '_resolve', side_effect=lambda action: (None, 'APT unavailable on this host') if action == ACTIONS[2] else (['tool'], '')):
            self.page._refresh_clicked()
        button = next(button for button, action in self.page._buttons if action == ACTIONS[2])
        self.assertFalse(button.get_sensitive())
        self.assertIn('APT unavailable', self.page._availability_labels[button][0].get_text())
        self.assertEqual(self.page._progress_source, 0)
        self.app.run_async.assert_not_called()

    def test_vacuum_reads_usage_before_reviewing_age_or_size_action(self):
        self.page._run_action = Mock()
        self.page.vacuum_mode.set_active_id('size')
        self.page._review_vacuum()
        action = self.page._run_action.call_args.args[0]
        self.assertEqual(action.command, ('journalctl', '--disk-usage'))
        review = self.page._run_action.call_args.kwargs['after']
        review(0, 'Archived and active journals take up 50M.\n')
        cleanup = self.page._run_action.call_args.args[0]
        self.assertEqual(cleanup.command, ('journalctl', '--vacuum-size=512M'))
        self.assertIn('50M', cleanup.description)
        self.assertIn('Permanently', cleanup.description)

    def test_rotation_summary_preview_and_separate_validate_have_no_write_side_effect(self):
        self.page.rotation_path.set_text('/var/log/myapp.log')
        self.page._run_action = Mock()
        self.assertIn('/var/log/myapp.log', self.page.rotation_summary.get_text())
        self.assertIn('rotate 4', self.page.rotation_preview.get_buffer().props.text)
        self.page._save_rotation(validate=True)
        validate = self.page._run_action.call_args.args[0]
        self.assertIn('--validate-only', validate.command)
        self.assertIn('No configuration', validate.description)
        self.page._save_rotation()
        save = self.page._run_action.call_args.args[0]
        self.assertNotIn('--validate-only', save.command)

    def test_stream_queue_is_coalesced_and_history_is_bounded_across_hosts(self):
        self.page._busy = True
        for _ in range(500):
            self.page._queue_output('x' * 1000)
        source = self.page._flush_source
        self.assertTrue(source)
        self.assertLessEqual(len(self.page._pending_output), 65536)
        GLib.source_remove(source)
        self.page._flush_output()
        self.assertLessEqual(self.page.output.get_buffer().get_char_count(), 128 * 1024)
        for index in range(12):
            self.page._busy = True
            self.page._running_since = time.monotonic()
            self.page._started = '2026-10-25T12:00:00'
            self.page._done(ACTIONS[0], (0, str(index) + 'y' * 100000), None)
        self.assertEqual(len(self.app.maintenance_history), 10)
        self.assertTrue(all(len(record['output']) <= 32768 for record in self.app.maintenance_history))
        self.assertEqual(self.page._flush_source, 0)
        self.assertEqual(self.page._progress_source, 0)
        remote = SimpleNamespace(target='user@remote:22', rotation_text='', uid=1000, which=lambda _: None,
                                 resolve_action=lambda _: (None, 'Unavailable'))
        other = MaintenancePage(HostContext(self.app, remote))
        try:
            self.assertIs(other._history, self.app.maintenance_history)
            other.history.set_active_id('0')
            self.assertIn('Local host', other.status.get_text())
            self.assertIn('user@remote', other.target)
        finally:
            other.destroy()

    def test_clear_is_disabled_while_running_and_save_exports_displayed_output(self):
        self.page.output.get_buffer().set_text('fixture output')
        self.page._busy = True
        self.page._clear_output()
        self.assertEqual(self.page._output_text(), 'fixture output')
        self.page._busy = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'result.txt'
            with patch('syslogapp.pages.maintenance.Gtk.FileChooserDialog') as factory:
                dialog = factory.return_value
                dialog.run.return_value = Gtk.ResponseType.OK
                dialog.get_filename.return_value = str(path)
                self.page._save_output()
            self.assertIn('fixture output', path.read_text())
        self.page._clear_output()
        self.assertEqual(self.page._output_text(), '')

    def test_explicit_action_streams_to_ui_before_completion_and_records_result(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'ui-received-output'
            code = "import sys,time;from pathlib import Path;print('first',flush=True);end=time.monotonic()+3\nwhile not Path(sys.argv[1]).exists() and time.monotonic()<end:time.sleep(.01)\nprint('second',flush=True)\nsys.exit(0 if Path(sys.argv[1]).exists() else 3)"
            action = Action('Fixture streaming check', 'Synthetic output only', (sys.executable, '-c', code, str(marker)), False)
            self.page._run_action(action)
            self.assertTrue(self.page._busy)
            self.assertTrue(self.page._progress_source)
            loop = GLib.MainLoop()
            seen = []
            deadline = time.monotonic() + 5
            def observe():
                if self.page._busy and 'first' in self.page._output_text():
                    seen.append(True)
                    marker.touch()
                if not self.page._busy or time.monotonic() > deadline:
                    loop.quit()
                    return False
                return True
            GLib.timeout_add(10, observe)
            loop.run()
            self.assertTrue(seen)
            self.assertFalse(self.page._busy)
            self.assertEqual(self.page._progress_source, 0)
            self.assertEqual(self.app.maintenance_history[-1]['code'], 0)
            self.assertIn('second', self.page._output_text())
