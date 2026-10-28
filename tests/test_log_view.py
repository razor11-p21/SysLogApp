# SPDX-License-Identifier: GPL-3.0-or-later
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
from syslogapp.log_view import LogFilter, groups, display_settings
from syslogapp.investigations import view_settings


def event(i, message='repeat', unit='fixture.service', **raw):
    return dict(time=f'2026-10-28 12:00:{i%60:02d}', unit=unit, level='Info', priority=6,
                message=message, raw=dict(MESSAGE=message, __REALTIME_TIMESTAMP=str(1793188800000000+i*1000000),
                                          __CURSOR=f'cursor{i}', _PID='123', **raw))


class ViewTests(unittest.TestCase):
    def test_snapshot_requests_repeat_identity_fields(self):
        from syslogapp.services import load_logs, JOURNAL_OUTPUT_FIELDS
        with patch('syslogapp.services.run_command', return_value=(0, '', '')) as run:
            load_logs()
        self.assertIn('--output-fields=' + JOURNAL_OUTPUT_FIELDS, run.call_args.args[0])
        for field in ('_BOOT_ID', '_PID', '_UID', '_SYSTEMD_INVOCATION_ID'):
            self.assertIn(field, JOURNAL_OUTPUT_FIELDS.split(','))

    def test_exclusions_are_literal_case_insensitive_message_and_exact_service(self):
        filters = LogFilter(exclude_units=['fixture.service'], exclude_message='a.*')
        self.assertFalse(filters.matches(event(0)))
        self.assertTrue(filters.matches(event(1, unit='fixture.service.extra')))
        self.assertFalse(filters.matches(event(2, 'A.* literally', unit='other')))
        self.assertTrue(filters.matches(event(3, 'anything', unit='other')))

    def test_only_consecutive_events_with_same_identity_are_grouped(self):
        rows = [event(0), event(1), event(2, 'different'), event(3)]
        result = groups(rows, LogFilter())
        self.assertEqual(list(map(len, result)), [2, 1, 1])
        self.assertIs(result[0][1], rows[1])
        for field in ('_PID', '_BOOT_ID', '_UID', '_SYSTEMD_INVOCATION_ID'):
            other = event(4)
            other['raw'][field] = 'different'
            self.assertEqual(len(groups([rows[0], other], LogFilter())), 2)

    def test_filtered_intervening_event_still_breaks_consecutive_run(self):
        rows = [event(0), event(1, 'hide'), event(2)]
        self.assertEqual(list(map(len, groups(rows, LogFilter(exclude_message='hide')))), [1, 1])

    def test_display_settings_bounded_and_old_views_default_off(self):
        self.assertEqual(display_settings({}), dict(exclude_units=[], exclude_message='', group_repeats=False))
        settings = display_settings(dict(exclude_units=['a']*4+['u'+str(i) for i in range(50)], exclude_message='x'*1000,
                                         group_repeats='yes'))
        self.assertLessEqual(len(settings['exclude_units']), 32)
        self.assertEqual(len(settings['exclude_message']), 512)
        self.assertFalse(settings['group_repeats'])
        self.assertFalse(view_settings({})['group_repeats'])


try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib
    from syslogapp.pages.logs import LogsPage
    from syslogapp.export_capture import snapshot
    from syslogapp.exports import render
    DISPLAY = Gtk.init_check()[0]
except ImportError:
    DISPLAY = False


@unittest.skipUnless(DISPLAY, 'GTK desktop required')
class ViewUITests(unittest.TestCase):
    def setUp(self):
        self.window = Gtk.Window()
        self.window.toast = Mock()
        self.app = SimpleNamespace(config={'log_lines': 100}, window=self.window, run_async=Mock())
        self.page = LogsPage(self.app)
        self.page._mapped_once = True
        self.addCleanup(self.window.destroy)
        self.addCleanup(self.page.destroy)
        self.page._loaded([event(0), event(1), event(2, 'other')], None)

    def live(self):
        self.page.live.handler_block_by_func(self.page._on_live)
        self.page.live.set_active(True)
        self.page.live.handler_unblock_by_func(self.page._on_live)

    def drain(self, rows):
        for row in rows:
            self.page._queue_live(row, self.page._live_generation)
        if self.page._drain_source:
            GLib.source_remove(self.page._drain_source)
        self.page._drain_live(self.page._live_generation)

    def test_hidden_batches_keep_history_bounded_without_model_work(self):
        self.live()
        self.page._on_unmap()
        changed = Mock()
        for signal in ('row-inserted', 'row-deleted', 'row-changed'):
            self.page.store.connect(signal, changed)
        with patch.object(self.page, '_schedule_reflow') as reflow:
            for start in range(0, 300, 50):
                self.drain([event(i) for i in range(start, start+50)])
            self.assertEqual(len(self.page._all_rows), 100)
            self.assertEqual(len(self.page.store), 0)
            changed.assert_not_called()
            reflow.assert_not_called()
        self.page._on_map()
        self.assertEqual(len(self.page.store), 100)
        self.assertEqual(self.page.store[-1][5]['__CURSOR'], 'cursor299')
        self.assertFalse(self.page._view_dirty)
        self.app.run_async.assert_not_called()

    def test_hidden_snapshot_and_filters_render_once_on_return(self):
        self.page._on_unmap()
        self.page._loaded([event(10), event(11, 'other')], None)
        self.page.exclude_message.set_text('other')
        self.page._display_filter_changed()
        self.assertEqual(len(self.page.store), 0)
        with patch.object(self.page, '_apply_filter', wraps=self.page._apply_filter) as apply:
            self.page._on_map()
            apply.assert_called_once_with()
        self.assertEqual(len(self.page.store), 1)
        self.assertEqual(self.page.store[0][5]['__CURSOR'], 'cursor10')

    def test_returning_to_paused_tab_does_not_jump_to_latest(self):
        self.page._on_unmap()
        with patch.object(self.page, '_scroll_to_latest') as latest:
            self.page._on_map()
            latest.assert_not_called()

    def test_group_details_and_export_preserve_every_original(self):
        self.page.group_repeats.set_active(True)
        self.assertEqual(len(self.page.store), 2)
        self.assertIn('[×2]', self.page.store[0][3])
        self.page.tree.get_selection().select_path(Gtk.TreePath.new_from_indices([0]))
        self.page._selection_changed(self.page.tree.get_selection(), reveal=True)
        text = self.page.detail_message.get_buffer().props.text
        self.assertIn('2 consecutive events', text)
        for row in self.page._all_rows[:2]:
            self.assertIn(self.page._exact_time(row['raw'], row['time']), text)
        data = snapshot(self.page)
        self.assertEqual([r['raw']['__CURSOR'] for r in data['records']], ['cursor0', 'cursor1', 'cursor2'])
        self.assertEqual([r['message'] for r in data['records']], ['repeat', 'repeat', 'other'])
        document = [json.loads(line) for line in render(data['records'], data['metadata']).splitlines()]
        self.assertEqual(document[0]['entry_count'], 3)
        self.assertTrue(data['metadata']['filters']['group_repeats'])

    def test_group_selection_export_expands_selected_display_rows(self):
        self.page.group_repeats.set_active(True)
        access = self.page.text_access
        column = self.page.tree_columns[0]
        access._anchor = access._point(Gtk.TreePath.new_from_indices([0]), column, 0)
        access._end = access._point(Gtk.TreePath.new_from_indices([1]), column, 0)
        self.assertEqual(snapshot(self.page)['selected'], [0, 1])

    def test_grouped_live_updates_stable_row_and_expires_old_originals(self):
        self.page._loaded([event(0), event(1)], None)
        self.page.group_repeats.set_active(True)
        inserted, deleted = Mock(), Mock()
        self.page.store.connect('row-inserted', inserted)
        self.page.store.connect('row-deleted', deleted)
        self.live()
        self.drain([event(2)])
        inserted.assert_not_called()
        deleted.assert_not_called()
        self.assertIn('[×3]', self.page.store[0][3])
        self.drain([event(i) for i in range(3, 103)])
        self.assertEqual(len(self.page.store), 1)
        data = snapshot(self.page)
        self.assertEqual(len(data['records']), 100)
        self.assertEqual(data['records'][0]['raw']['__CURSOR'], 'cursor3')
        self.assertEqual(data['records'][-1]['raw']['__CURSOR'], 'cursor102')

    def test_exclusions_apply_to_snapshot_live_and_export_without_queries(self):
        self.page.exclude_message.set_text('REPEAT')
        self.page._display_filter_changed()
        self.assertEqual(len(self.page.store), 1)
        self.live()
        self.drain([event(3), event(4, 'keep')])
        self.assertEqual([r['message'] for r in snapshot(self.page)['records']], ['other', 'keep'])
        self.assertEqual(len(self.page._all_rows), 5)
        self.app.run_async.assert_not_called()
        self.page._clear_display_filters()
        self.assertEqual(len(self.page.store), 5)

    def test_context_exclusions_and_clear_are_reversible(self):
        self.page.tree.get_selection().select_path(Gtk.TreePath.new_from_indices([0]))
        self.page._hide_selected_message()
        self.assertEqual(len(self.page.store), 1)
        self.page._clear_display_filters()
        self.page.tree.get_selection().select_path(Gtk.TreePath.new_from_indices([0]))
        self.page._hide_selected_service()
        self.assertEqual(len(self.page.store), 0)
        self.assertEqual(len(self.page._all_rows), 3)
        self.page._clear_display_filters()
        self.assertEqual(len(self.page.store), 3)
        self.app.run_async.assert_not_called()

    def test_saved_view_retains_display_filters(self):
        from syslogapp.investigations import host_identity
        settings = dict(exclude_units=['fixture.service'], exclude_message='abc', group_repeats=True)
        self.page._apply_saved_view(dict(host=host_identity()[0], settings=settings))
        self.assertEqual(self.page._display_settings(), settings)
        with patch('syslogapp.saved_ui.ask_name', return_value='Filtered'), patch('syslogapp.investigations.save_view') as save:
            self.page._save_view()
        for key, value in settings.items():
            self.assertEqual(save.call_args.args[2][key], value)

    def test_sorted_grouped_view_keeps_all_originals_and_ungroup_restores_rows(self):
        self.page.group_repeats.set_active(True)
        self.page.store.set_sort_column_id(self.page.COL_TIME, Gtk.SortType.DESCENDING)
        data = snapshot(self.page)
        self.assertEqual([row['raw']['__CURSOR'] for row in data['records']], ['cursor2', 'cursor1', 'cursor0'])
        self.page.group_repeats.set_active(False)
        self.assertEqual(len(self.page.store), 3)
        self.assertEqual([row['raw']['__CURSOR'] for row in snapshot(self.page)['records']], ['cursor2', 'cursor1', 'cursor0'])

    def test_remote_page_uses_same_loaded_filters_and_hidden_collection(self):
        remote = SimpleNamespace(connected=True, capture=Mock(), profile=dict(hostname='fixture.invalid',username='fixture',port=22))
        app = SimpleNamespace(config={'log_lines':100}, window=self.window, run_async=Mock(), host=remote)
        page = LogsPage(app)
        self.addCleanup(page.destroy)
        page._mapped_once = True
        page._loaded([event(0), event(1)], None)
        page.group_repeats.set_active(True)
        self.assertEqual(len(page.store), 1)
        page._on_unmap()
        page._loaded([event(2), event(3)], None)
        page._on_map()
        self.assertEqual(len(page.store), 1)
        self.assertEqual(len(snapshot(page)['records']), 2)
        remote.capture.assert_not_called()
        app.run_async.assert_not_called()

    def test_hidden_byte_limit_still_applies_and_release_references(self):
        import weakref
        class TrackedRow(dict): pass
        row = TrackedRow(event(0))
        reference = weakref.ref(row)
        self.page._loaded([row], None)
        self.page.group_repeats.set_active(True)
        self.page._on_unmap()
        self.live()
        from syslogapp.services import row_bytes
        with patch('syslogapp.services.MAX_HISTORY_BYTES', row_bytes(event(14, 'x'*180))):
            self.drain([event(i, 'x'*180) for i in range(10, 15)])
        self.assertLess(len(self.page._all_rows), 6)
        self.assertEqual(len(self.page.store), 0)
        del row
        import gc
        gc.collect()
        self.assertIsNone(reference())
