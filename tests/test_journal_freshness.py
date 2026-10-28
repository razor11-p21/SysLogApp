# SPDX-License-Identifier: GPL-3.0-or-later
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from syslogapp.hosts import SSHHost
from syslogapp.services import journal_records, CheckUnavailable


class RemoteJournalWarningsTests(unittest.TestCase):
    def test_real_capture_preserves_successful_command_stderr(self):
        host = SSHHost(dict(hostname='fixture.invalid', username='fixture'))
        try:
            script = ('import sys; print(\'{"MESSAGE":"visible user event"}\'); '
                      'print("You are currently not seeing messages from other users and the system.", file=sys.stderr)')
            with patch.object(host, 'command', return_value=[sys.executable, '-c', script]):
                with self.assertRaisesRegex(CheckUnavailable, 'not seeing messages'):
                    journal_records([], host=host)
        finally:
            host.close()

    def test_local_and_remote_permission_warnings_use_same_policy(self):
        output = json.dumps({'MESSAGE': 'visible user event'})
        for warning in ('Permission denied', 'Access denied', 'No journal files were opened',
                        'You are not seeing messages from other users'):
            with self.subTest(warning=warning):
                host = SimpleNamespace(capture=Mock(return_value=(output, False, warning)))
                with self.assertRaises(CheckUnavailable):
                    journal_records([], host=host)
                self.assertTrue(host.capture.call_args.kwargs['return_stderr'])
                with patch('syslogapp.services.run_command', return_value=(0, output, warning)):
                    with self.assertRaises(CheckUnavailable):
                        journal_records([])

    def test_success_with_no_permission_warning_and_empty_result_is_valid(self):
        for output, count in (('', 0), ('{"MESSAGE":"ok"}', 1)):
            host = SimpleNamespace(capture=Mock(return_value=(output, False, '')))
            self.assertEqual(len(journal_records([], host=host)), count)

    def test_existing_capture_pair_and_optional_diagnostics_are_compatible(self):
        host = SSHHost(dict(hostname='fixture.invalid', username='fixture'))
        try:
            command = [sys.executable, '-c', 'import sys; print("out"); print("notice",file=sys.stderr)']
            with patch.object(host, 'command', return_value=command):
                self.assertEqual(host.capture([]), ('out\n', False))
                self.assertEqual(host.capture([], return_stderr=True), ('out\n', False, 'notice'))
        finally:
            host.close()


try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib
    from syslogapp.pages.logs import LogsPage
    from syslogapp.export_capture import snapshot
    DISPLAY = Gtk.init_check()[0]
except ImportError:
    DISPLAY = False


@unittest.skipUnless(DISPLAY, 'GTK desktop required')
class JournalFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.window = Gtk.Window()
        self.window.toast = Mock()
        self.app = SimpleNamespace(config={}, window=self.window, run_async=Mock())
        self.page = LogsPage(self.app)
        self.addCleanup(self.window.destroy)
        self.addCleanup(self.page.destroy)
        self.rows = [dict(time='2026-10-28 12:00:00', unit='fixture.service', level='Info',
                          priority=6, message='keep this event', raw={'MESSAGE': 'keep this event'})]
        self.page._loaded(self.rows, None)
        self.last_read = self.page._last_successful_read

    def state(self):
        return snapshot(self.page)['metadata']['view_state']

    def test_failed_local_refresh_retains_rows_and_exports_stale_state(self):
        self.page._loaded(None, RuntimeError('fixture read failure'))
        self.assertEqual(self.page._all_rows, self.rows)
        self.assertEqual(len(self.page.store), 1)
        state = self.state()
        self.assertTrue(state['stale'])
        self.assertEqual(state['error'], 'fixture read failure')
        self.assertEqual(state['last_successful_read'], self.last_read)
        self.assertIn('Stale data', self.page.count_label.get_text())
        self.assertIn(self.last_read[11:19], self.page.count_label.get_text())
        self.page.search.set_text('keep')
        self.assertIn('Stale data', self.page.count_label.get_text())
        self.assertTrue(self.state()['stale'])
        self.app.run_async.assert_not_called()

    def test_successful_empty_refresh_clears_error_and_staleness(self):
        self.page._loaded(None, RuntimeError('fixture'))
        self.page._loaded([], None)
        self.assertFalse(self.state()['stale'])
        self.assertIsNone(self.state()['error'])
        self.assertIsNotNone(self.state()['last_successful_read'])
        self.assertEqual(len(self.page.store), 0)
        self.assertNotIn('Stale', self.page.count_label.get_text())

    def test_first_load_failure_has_no_successful_timestamp(self):
        page = LogsPage(self.app)
        self.addCleanup(page.destroy)
        page._loaded(None, RuntimeError('unavailable'))
        state = snapshot(page)['metadata']['view_state']
        self.assertTrue(state['stale'])
        self.assertIsNone(state['last_successful_read'])

    def test_remote_disconnect_marker_still_exports_as_stale(self):
        self.page._remote_stale = True
        self.assertTrue(self.state()['stale'])
        self.page._loaded(self.rows, None)
        self.assertFalse(self.state()['stale'])

    def enable_fake_live(self):
        self.page.live.handler_block_by_func(self.page._on_live)
        self.page.live.set_active(True)
        self.page.live.handler_unblock_by_func(self.page._on_live)

    def test_obsolete_history_error_cannot_mark_active_live_feed_stale(self):
        self.enable_fake_live()
        self.page._loaded(None, RuntimeError('obsolete snapshot error'))
        self.assertFalse(self.state()['stale'])
        self.assertEqual(self.last_read, self.page._last_successful_read)

    def test_live_failure_exports_stale_after_draining_pending_events(self):
        self.enable_fake_live()
        process = Mock()
        self.page._live_proc = process
        self.page._queue_live(self.rows[0], self.page._live_generation)
        self.page._live_exited(process, self.page._live_generation, 1, 'fixture live failure')
        self.assertFalse(self.page.live.get_active())
        self.assertTrue(self.state()['stale'])
        self.assertEqual(self.state()['error'], 'fixture live failure')
        self.assertIn('Stale data', self.page.count_label.get_text())

    def test_live_batch_clears_prior_read_failure(self):
        self.page._loaded(None, RuntimeError('fixture failure'))
        self.enable_fake_live()
        self.page._queue_live(self.rows[0], self.page._live_generation)
        if self.page._drain_source:
            GLib.source_remove(self.page._drain_source)
        self.page._drain_live(self.page._live_generation)
        self.assertFalse(self.state()['stale'])
        self.assertIsNone(self.state()['error'])

    def test_failed_live_start_retains_rows_and_marks_export_stale(self):
        with patch('syslogapp.pages.logs.subprocess.Popen', side_effect=OSError('fixture spawn failure')):
            self.page.live.set_active(True)
        self.assertFalse(self.page.live.get_active())
        self.assertEqual(self.page._all_rows, self.rows)
        self.assertTrue(self.state()['stale'])
        self.assertEqual(self.state()['error'], 'fixture spawn failure')
        self.assertIn('Stale data', self.page.count_label.get_text())
