# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Exercise batching, bounded storage and lifecycle with actual GTK models."""
import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib
    from syslogapp.pages.logs import LogsPage
    from syslogapp.app import MainWindow, SysLogApplication
    HAS_DISPLAY = Gtk.init_check()[0]
except ImportError:
    HAS_DISPLAY = False


class ImportTests(unittest.TestCase):
    def test_startup_does_not_import_monitoring_or_old_pages(self):
        code = '''import sys
import syslogapp.app
assert 'psutil' not in sys.modules
assert not any('syslogapp.pages.' + name in sys.modules for name in
               ('dashboard', 'network', 'overview', 'diagnostics', 'maintenance', 'settings'))
'''
        subprocess.run([sys.executable, '-c', code], check=True)


@unittest.skipUnless(HAS_DISPLAY, 'No GTK desktop display')
class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.app = SimpleNamespace(config={'log_lines': 100}, run_async=Mock(), window=SimpleNamespace(toast=Mock()))
        self.page = LogsPage(self.app)
        # Enable the stream UI without creating a real journalctl process.
        self.page.live.handler_block_by_func(self.page._on_live)
        self.page.live.set_active(True)
        self.page.live.handler_unblock_by_func(self.page._on_live)
        self.generation = self.page._live_generation

    def tearDown(self):
        self.page.destroy()

    def row(self, i, message=None):
        return {'time': '2026-10-20 12:00:00', 'unit': 'test.service', 'level': 'Info',
                'message': message or f'event {i}', 'priority': 6,
                'raw': {'MESSAGE': message or f'event {i}', 'sequence': i}}

    def flush(self):
        source = self.page._drain_source
        if source:
            GLib.source_remove(source)
        self.page._drain_live(self.generation)

    def test_burst_uses_one_wakeup_and_bounded_inbox(self):
        with patch('syslogapp.pages.logs.GLib.timeout_add', return_value=0) as timer:
            # Nonzero fake source; remove it before cleanup.
            timer.return_value = 123456
            for i in range(10000):
                self.page._queue_live(self.row(i), self.generation)
            self.assertEqual(timer.call_count, 1)
            self.assertEqual(len(self.page._pending_rows), 100)
            self.assertEqual(self.page._dropped_pending, 9900)
            self.page._drain_source = 0
        self.flush()
        self.assertEqual(len(self.page.store), 100)
        self.assertEqual(self.page._all_rows[-1]['raw']['sequence'], 9999)
        self.assertIn('9900 skipped', self.page.count_label.get_text())

    def test_search_does_not_restart_journal_and_evicted_matches_stay_evicted(self):
        self.page.search.set_text('needle')
        self.page._queue_live(self.row(0, 'needle'), self.generation)
        self.flush()
        self.assertEqual(len(self.page.store), 1)
        for i in range(1, 101):
            self.page._queue_live(self.row(i), self.generation)
        self.flush()
        self.assertEqual(len(self.page.store), 0)
        self.assertEqual(len(self.page._all_rows), 100)
        self.app.run_async.assert_not_called()

    def test_selection_pause_stops_collection_and_keeps_displayed_rows(self):
        self.page._queue_live(self.row(1), self.generation)
        self.flush()
        self.page._queue_live(self.row(2), self.generation)
        with patch.object(self.page, '_scroll_to_latest') as scroll:
            self.page._hold_for_selection()
            self.page._queue_live(self.row(3), self.generation)
            self.flush()
            scroll.assert_not_called()
        self.assertFalse(self.page.live.get_active())
        self.assertEqual([row[self.page.COL_RAW]['sequence'] for row in self.page.store], [1])
        self.assertEqual(len(self.page._pending_rows), 0)

    def test_stop_discards_pending_and_stale_events(self):
        self.page._queue_live(self.row(1), self.generation)
        self.page.stop_live()
        self.page._queue_live(self.row(2), self.generation)
        self.assertEqual(len(self.page._pending_rows), 0)
        self.assertEqual(self.page._drain_source, 0)
        self.assertEqual(len(self.page.store), 0)

    def test_remapping_does_not_query_again(self):
        self.page.live.set_active(False)
        self.page._on_map()
        self.page._on_map()
        self.assertEqual(self.app.run_async.call_count, 1)

    def test_wrapped_rows_and_multiline_inspector(self):
        self.assertFalse(self.page.tree.get_fixed_height_mode())
        row = self.row(1, 'first\nsecond')
        self.page._queue_live(row, self.generation)
        self.flush()
        self.page.tree.row_activated(Gtk.TreePath.new_from_indices([0]), self.page.tree_columns[0])
        buffer = self.page.detail_message.get_buffer()
        self.assertEqual(buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False), 'first\nsecond')

    def test_no_periodic_timer_after_queue_drains(self):
        self.page._queue_live(self.row(1), self.generation)
        self.flush()
        self.assertEqual(self.page._drain_source, 0)
        with patch('syslogapp.pages.logs.GLib.timeout_add') as timer:
            self.page._drain_live(self.generation)
            timer.assert_not_called()

    def test_sorted_live_history_evicts_expired_rows_without_dropping_new_records(self):
        self.page.store.set_sort_column_id(self.page.COL_UNIT, Gtk.SortType.ASCENDING)
        for i in range(100):
            item = self.row(i)
            item['unit'] = 'aaa' if i >= 90 else 'zzz'
            self.page._queue_live(item, self.generation)
        self.flush()
        for i in range(100, 110):
            self.page._queue_live(self.row(i), self.generation)
        self.flush()
        sequences = {row[self.page.COL_RAW]['sequence'] for row in self.page.store}
        self.assertEqual(sequences, set(range(10, 110)))
        self.assertEqual(self.page.store.get_sort_column_id()[0], self.page.COL_UNIT)

    def test_snapshot_filter_retains_descending_sort_and_matching_records(self):
        self.page._all_rows = [self.row(i, 'match' if i % 2 else 'other') for i in range(10)]
        for i, item in enumerate(self.page._all_rows):
            item['raw']['__REALTIME_TIMESTAMP'] = str(i * 1_000_000)
        self.page.store.set_sort_column_id(self.page.COL_TIME, Gtk.SortType.DESCENDING)
        self.page.search.set_text('match')
        self.page._apply_filter()
        self.assertEqual([row[self.page.COL_RAW]['sequence'] for row in self.page.store],
                         [9, 7, 5, 3, 1])
        self.assertEqual(self.page.store.get_sort_column_id(),
                         (self.page.COL_TIME, Gtk.SortType.DESCENDING))
        self.page.search.set_text('missing')
        self.page._apply_filter()
        self.assertEqual(len(self.page.store), 0)
        self.page.search.set_text('')
        self.page._apply_filter()
        self.assertEqual([row[self.page.COL_RAW]['sequence'] for row in self.page.store],
                         list(range(9, -1, -1)))

    def test_log_headers_sort_chronologically_and_by_severity(self):
        for i, priority in [(1, 6), (3, 4), (2, 0)]:
            item = self.row(i)
            item['raw']['__REALTIME_TIMESTAMP'] = str(i * 1_000_000)
            item['priority'] = priority
            self.page._queue_live(item, self.generation)
        self.flush()
        self.assertEqual([row[self.page.COL_RAW]['sequence'] for row in self.page.store], [1, 2, 3])
        self.page.store.set_sort_column_id(self.page.COL_LEVEL, Gtk.SortType.ASCENDING)
        self.assertEqual([row[self.page.COL_PRIORITY] for row in self.page.store], [0, 4, 6])

    def test_live_uses_cursor_and_initial_load_keeps_history(self):
        row = self.row(1)
        row['raw']['__CURSOR'] = 'cursor-1'
        self.page._all_rows = [row]
        with patch('syslogapp.pages.logs.subprocess.Popen') as popen, \
             patch('syslogapp.pages.logs.threading.Thread'):
            self.page.start_live()
            args = popen.call_args.args[0]
            self.assertEqual(args[args.index('--after-cursor') + 1], 'cursor-1')
            self.page.stop_live()
            self.page._all_rows = []
            self.page._busy = True
            self.page.start_live()
            args = popen.call_args.args[0]
            self.assertEqual(args[args.index('-n') + 1], '100')
            self.assertNotIn('--after-cursor', args)

    def _check_tab_selection_reset(self, window):
        page = window.pages['logs']
        item = self.row(1, 'searchable event')
        page._all_rows = [item]
        page._apply_filter()
        page.search.set_text('searchable')
        page.search.select_region(0, -1)
        page.tree.row_activated(Gtk.TreePath.new_from_indices([0]), page.tree_columns[0])
        page.text_access.select_all()
        buffer = page.detail_message.get_buffer()
        buffer.select_range(*buffer.get_bounds())
        self.assertTrue(page.text_access.selected_text())
        self.assertTrue(page.details_panel.get_visible())
        window.notebook.set_current_page(4)
        self.assertFalse(page.text_access.selected_text())
        self.assertIsNone(page.tree.get_selection().get_selected()[1])
        self.assertFalse(page.details_panel.get_visible())
        self.assertFalse(page.search.get_selection_bounds())
        self.assertEqual(page.search.get_text(), 'searchable')
        help_page = window.pages['help']
        help_buffer = help_page.text.get_buffer()
        help_buffer.select_range(*help_buffer.get_bounds())
        self.assertTrue(help_buffer.get_has_selection())
        window.notebook.set_current_page(0)
        self.assertFalse(help_buffer.get_has_selection())
        self.assertFalse(page.details_panel.get_visible())
        window.show_all()
        window.notebook.set_current_page(3)
        maintenance = window.pages['maintenance']

        def labels(widget):
            if isinstance(widget, Gtk.Label):
                yield widget
            elif isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    yield from labels(child)

        description = next(label for label in labels(maintenance)
                           if label.get_text() == 'Read journal storage usage; no changes.')
        description.grab_focus()
        description.select_region(len(description.get_text()), len(description.get_text()))
        window.notebook.set_current_page(0)
        window.notebook.set_current_page(3)
        # Check before draining idle callbacks: no transient selection may appear.
        self.assertFalse(description.get_selection_bounds()[0])
        self.assertIs(window.get_focus(), maintenance.refresh_button)

    def test_network_is_lazy_and_does_not_collect_at_startup(self):
        app = SysLogApplication()
        # Never register under the live desktop app's ID: a remote application
        # cannot own test windows, and GTK may fail in native window creation.
        app.set_application_id(f'gr.syslogapp.tests.p{os.getpid()}')
        app.register(None)
        self.assertFalse(app.get_is_remote())
        with patch.object(app, 'run_async'), patch('syslogapp.app.save_config'):
            window = MainWindow(app)
            self.assertEqual(list(window.pages), ['logs'])
            self.assertEqual(window.notebook.get_n_pages(), 5)
            app.window = window
            window.notebook.set_current_page(1)
            self.assertIn('network', window.pages)
            page = window.pages['network']
            self.assertFalse(page._loaded_once)
            self.assertIs(window._current_page(), page)
            for index, key in ((2, 'overview'), (3, 'maintenance')):
                window.notebook.set_current_page(index)
                self.assertIn(key, window.pages)
                self.assertFalse(window.pages[key]._busy)
                window._focus_search()
                window._close_details()
            self.assertFalse(window.pages['overview']._loaded_once)
            self.assertFalse(window._delete_event())
            window.pages['maintenance']._busy = True
            self.assertTrue(window._delete_event())
            window.pages['maintenance']._busy = False
            window.notebook.set_current_page(0)
            self._check_tab_selection_reset(window)
            window.destroy()
        app.executor.shutdown(wait=True)

    def test_optimized_log_comparison_matches_full_sort_keys_for_all_columns(self):
        from syslogapp.sorting import log_sort_key
        values=[]
        for i in range(12):
            row=[f'2026-10-21 12:00:{i%3:02d}',f'unit-{i%2}', 'Info', f'event {i%4}',i%8,
                 {'__REALTIME_TIMESTAMP':str(i%3)} if i%4 else {'__REALTIME_TIMESTAMP':None}]
            values.append(row)
        for row in values:
            self.page.store.append(row + [None])
        for column in range(4):
            expected=sorted(values,key=lambda row:log_sort_key(row,column))
            self.page.store.set_sort_column_id(column,Gtk.SortType.ASCENDING)
            self.assertEqual([log_sort_key(tuple(row),column) for row in self.page.store],
                             [log_sort_key(row,column) for row in expected])
