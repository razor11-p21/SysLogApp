# SPDX-License-Identifier: GPL-3.0-or-later
import io
import json
import sys
import unittest
from unittest.mock import Mock, patch
from syslogapp import services as s
from syslogapp import network as n


class JournalBudgetTests(unittest.TestCase):
    def test_real_capture_stops_a_producer_at_budget(self):
        with patch.object(s, 'MAX_CAPTURE_BYTES', 4096):
            rc, out, error = s.run_command([sys.executable, '-c', 'print("x" * 1000000)'])
        self.assertNotEqual(rc, 0)
        self.assertEqual(out, '')
        self.assertIn('exceeded', error)

    def test_stream_discards_whole_oversized_record_then_recovers(self):
        source = io.BytesIO(b'x' * (s.MAX_RECORD_BYTES * 3) + b'\n{"MESSAGE":"next"}\n')
        self.assertEqual(list(s.bounded_lines(source)), [None, '{"MESSAGE":"next"}\n'])

    def test_record_limit_is_utf8_bytes_and_snapshot_reports_omissions(self):
        oversized = json.dumps({'MESSAGE': '\u03b1' * s.MAX_RECORD_BYTES}, ensure_ascii=False)
        good = json.dumps({'MESSAGE': 'keep', '__CURSOR': 'good'})
        with patch.object(s, 'run_command', return_value=(0, oversized + '\n' + good, '')):
            rows = s.load_logs()
        self.assertEqual([r['message'] for r in rows], ['keep'])
        self.assertEqual(rows.omitted, 1)

    def test_byte_budget_keeps_recent_entries_without_shortening_messages(self):
        rows = [{'raw': {'MESSAGE': str(i) * 60}, 'message': str(i) * 60} for i in range(10)]
        budget = s.row_bytes(rows[-1]) * 3
        with patch.object(s, 'MAX_HISTORY_BYTES', budget):
            retained = s.bound_rows(rows)
        self.assertEqual(retained, rows[-3:])
        self.assertEqual(retained.omitted, 7)
        self.assertEqual(retained[-1]['message'], '9' * 60)

    def test_remote_snapshot_uses_same_budget_and_rejects_partial_data(self):
        host = Mock()
        host.capture.return_value = ('{"MESSAGE":"partial"}', True, '')
        with self.assertRaisesRegex(s.CheckUnavailable, 'exceeded'):
            s.load_logs(host=host)
        self.assertEqual(host.capture.call_args.kwargs['max_bytes'], s.MAX_CAPTURE_BYTES)


class JournalHistoryTests(unittest.TestCase):
    def test_range_message_and_previous_boot_filters_are_literal_arguments(self):
        with patch.object(s, 'run_command', return_value=(0, '', '')) as run:
            s.load_logs(boot_only=False, boot=-1, since='@100', until='@200',
                        match='error.* $(uname)', unit='test.service')
        args = run.call_args.args[0]
        for flag, value in [('-b', '-1'), ('--since', '@100'), ('--until', '@200'), ('-u', 'test.service')]:
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertEqual(args[args.index('--grep') + 1], r'error\.\*\ \$\(uname\)')
        self.assertIn('--case-sensitive=no', args)

    def test_older_page_excludes_anchor_and_returns_chronological_order(self):
        records = [{'MESSAGE': name, '__CURSOR': name} for name in ('anchor', 'older', 'oldest')]
        with patch.object(s, 'run_command', return_value=(0, '\n'.join(map(json.dumps, records)), '')) as run:
            rows = s.load_logs(before='anchor', since='@100', until='@200')
        self.assertEqual([r['message'] for r in rows], ['oldest', 'older'])
        args = run.call_args.args[0]
        self.assertEqual(args[args.index('--cursor') + 1], 'anchor')
        self.assertIn('--reverse', args)
        self.assertIn('--since', args)
        self.assertIn('--until', args)


class NetworkCacheTests(unittest.TestCase):
    def test_cached_details_only_query_sockets_and_preserve_detail_limits(self):
        cached = {'interfaces': [{'ifname': 'eth0'}], 'routes': [{'dev': 'eth0'}],
                  'errors': ['-6 routes: unavailable', 'Sockets: previous failure'],
                  'details_limited': True}
        with patch.object(n, 'capture', return_value=('tcp ESTAB 0 0 127.0.0.1:1 127.0.0.1:2\n', False)) as collect:
            result = n.snapshot(True, cached=cached)
        self.assertEqual(collect.call_count, 1)
        self.assertEqual(collect.call_args.args[0][0], 'ss')
        self.assertEqual(result['interfaces'], cached['interfaces'])
        self.assertEqual(result['routes'], cached['routes'])
        self.assertEqual(result['errors'], ['-6 routes: unavailable'])
        self.assertTrue(result['limited'])
        self.assertFalse(result['details_refreshed'])

    def test_remote_cache_never_runs_ip_queries(self):
        host = Mock()
        host.capture.return_value = ('', False)
        n.snapshot(host=host, cached={'interfaces': [], 'routes': [], 'errors': []})
        self.assertEqual(host.capture.call_count, 1)
        self.assertEqual(host.capture.call_args.args[0][0], 'ss')


try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib
    from types import SimpleNamespace
    from syslogapp.pages.logs import LogsPage
    from syslogapp.pages.network import NetworkPage
    DISPLAY = Gtk.init_check()[0]
except ImportError:
    DISPLAY = False


@unittest.skipUnless(DISPLAY, 'No GTK display')
class HistoryUITests(unittest.TestCase):
    def setUp(self):
        self.window = Gtk.Window()
        self.window.toast = Mock()
        self.app = SimpleNamespace(config={'log_lines': 100}, run_async=Mock(), window=self.window)
        self.page = LogsPage(self.app)

    def tearDown(self):
        self.page.destroy()
        self.window.destroy()

    def test_history_dialog_searches_only_on_submit_with_frozen_time_range(self):
        def submit(dialog):
            children = dialog.get_content_area().get_children()
            next(w for w in children if isinstance(w, Gtk.ComboBoxText)).set_active(0)
            entries = [w for w in children if isinstance(w, Gtk.Entry)]
            entries[-1].set_text('denied.*')
            self.app.run_async.assert_not_called()
            return Gtk.ResponseType.OK
        with patch.object(Gtk.Dialog, 'run', submit):
            self.page._history_dialog()
        self.assertFalse(self.page.live.get_active())
        query = self.page._history_query
        self.assertEqual(int(query['until'][1:]) - int(query['since'][1:]), 900)
        self.assertEqual(query['match'], 'denied.*')
        with patch('syslogapp.pages.logs.load_logs', return_value=[]) as load:
            self.app.run_async.call_args.args[0]()
        self.assertEqual(load.call_args.kwargs['match'], 'denied.*')

    def test_older_page_keeps_range_and_live_returns_to_recent(self):
        self.page._history_query = {'since': '@100', 'until': '@200', 'match': 'test'}
        self.page._all_rows = [{'raw': {'__CURSOR': 'oldest'}}]
        self.page._load_older()
        with patch('syslogapp.pages.logs.load_logs', return_value=[]) as load:
            self.app.run_async.call_args.args[0]()
        self.assertEqual(load.call_args.kwargs['before'], 'oldest')
        self.assertEqual(load.call_args.kwargs['since'], '@100')
        self.assertEqual(load.call_args.kwargs['match'], 'test')
        with patch.object(self.page, 'start_live') as start:
            self.page.live.set_active(True)
        start.assert_called_once_with(reset_view=True, include_history=True)
        self.assertEqual(self.page._history_query, {})
        self.assertIsNone(self.page._before)

    def test_oversized_live_record_is_reported_even_without_valid_rows(self):
        self.page.live.handler_block_by_func(self.page._on_live)
        self.page.live.set_active(True)
        self.page.live.handler_unblock_by_func(self.page._on_live)
        generation = self.page._live_generation
        self.page._queue_live(None, generation)
        GLib.source_remove(self.page._drain_source)
        self.page._drain_live(generation)
        self.assertIn('1 omitted by byte limits', self.page.count_label.get_text())
        self.assertEqual(len(self.page.store), 0)

    def test_live_pending_and_history_respect_byte_budget(self):
        self.page.live.handler_block_by_func(self.page._on_live)
        self.page.live.set_active(True)
        self.page.live.handler_unblock_by_func(self.page._on_live)
        generation = self.page._live_generation
        def row(i):
            return {'raw': {'MESSAGE': str(i) * 60}, 'message': str(i) * 60,
                    'time': '2026-10-25 10:00:00', 'unit': 'test', 'level': 'Info', 'priority': 6}
        budget = s.row_bytes(row(0)) * 3
        with patch('syslogapp.pages.logs.MAX_HISTORY_BYTES', budget), patch.object(s, 'MAX_HISTORY_BYTES', budget):
            for i in range(10):
                self.page._queue_live(row(i), generation)
            self.assertLessEqual(self.page._pending_bytes, budget)
            GLib.source_remove(self.page._drain_source)
            self.page._drain_live(generation)
        self.assertEqual([r['message'] for r in self.page._all_rows], [str(i) * 60 for i in (7, 8, 9)])
        self.assertEqual(len(self.page.store), 3)
        self.assertIn('7 omitted', self.page.count_label.get_text())

    def test_network_automatic_refresh_reuses_details_until_expiry_manual_refresh_forces_them(self):
        page = NetworkPage(self.app)
        result = {'interfaces': [], 'routes': [], 'sockets': [], 'errors': [],
                  'time': '10:00:00', 'processes': True, 'limited': False}
        try:
            with patch('syslogapp.pages.network.time.monotonic', return_value=100):
                page._loaded(result, None)
            with patch('syslogapp.pages.network.time.monotonic', return_value=110), patch('syslogapp.pages.network.snapshot') as collect:
                page.refresh(automatic=True)
                self.app.run_async.call_args.args[0]()
                self.assertIs(collect.call_args.kwargs['cached'], result)
                page._busy = False
                page.refresh()
                self.app.run_async.call_args.args[0]()
                self.assertNotIn('cached', collect.call_args.kwargs)
            page._busy = False
            with patch('syslogapp.pages.network.time.monotonic', return_value=131), patch('syslogapp.pages.network.snapshot') as collect:
                page.refresh(automatic=True)
                self.app.run_async.call_args.args[0]()
                self.assertNotIn('cached', collect.call_args.kwargs)
        finally:
            page.destroy()
