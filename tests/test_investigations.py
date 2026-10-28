# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
from syslogapp import investigations as s


class StorageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / 'settings/investigations.json'
        p = patch.object(s, 'STORE_FILE', self.file)
        p.start()
        self.addCleanup(p.stop)

    def host(self, hostname='server', username='alice', port=22):
        return SimpleNamespace(profile=dict(hostname=hostname, username=username, port=port), label='Friendly name')

    def row(self, message='first\nsecond', cursor='cursor'):
        return dict(time='2026-10-25 12:00:00', unit='example.service', level='Warning',
                    message=message, raw={'MESSAGE': message, '__CURSOR': cursor, '_BOOT_ID': 'boot'})

    def test_views_round_trip_replace_by_name_and_remain_host_and_page_scoped(self):
        values = dict(scope='previous', priority='Warning', unit='ssh.service', search='denied',
                      history={'since': '@100', 'until': '@200', 'match': 'error.*'})
        first = s.save_view(None, 'SSH failures', values)
        s.save_view(None, 'SSH failures', dict(values, search='changed'))
        s.save_view(self.host(), 'SSH failures', values)
        s.save_view(None, 'SSH failures', dict(page='network', kind=1))
        data = s.load()
        self.assertEqual(len(data['views']), 3)
        self.assertEqual(data['views'][0]['id'], first['id'])
        self.assertEqual(data['views'][0]['settings']['search'], 'changed')
        self.assertEqual(data['views'][0]['settings']['history'], values['history'])
        self.assertEqual(os.stat(self.file).st_mode & 0o777, 0o600)

    def test_host_identity_survives_label_and_auth_changes_but_separates_user_and_port(self):
        a = self.host()
        b = self.host()
        b.label = 'Renamed'
        b.profile.update(auth='password', password='must not save', key_file='/secret/key')
        self.assertEqual(s.host_identity(a)[0], s.host_identity(b)[0])
        self.assertNotEqual(s.host_identity(a)[0], s.host_identity(self.host(port=2222))[0])
        self.assertNotEqual(s.host_identity(a)[0], s.host_identity(self.host(username='bob'))[0])
        s.save_view(b, 'View', {})
        self.assertNotIn('must not save', self.file.read_text())
        self.assertNotIn('/secret/key', self.file.read_text())

    def test_bookmarks_keep_multiline_excerpt_reference_and_deduplicate(self):
        item = s.bookmark(None, 'Important', self.row())
        self.assertEqual(item['event']['message'], 'first\nsecond')
        self.assertEqual(item['event']['boot'], 'boot')
        s.bookmark(None, 'Renamed', self.row())
        s.bookmark(self.host(), 'Remote', self.row())
        self.assertEqual(len(s.load()['bookmarks']), 2)
        self.assertEqual(s.load()['bookmarks'][0]['name'], 'Renamed')
        s.remove('bookmarks', item['id'])
        self.assertEqual(len(s.load()['bookmarks']), 1)

    def test_utf8_excerpt_is_bounded_and_flagged_without_breaking_characters(self):
        item = s.bookmark(None, 'Large', self.row('\u03b1' * 9000))
        self.assertLessEqual(len(item['event']['message'].encode()), s.MAX_MESSAGE_BYTES)
        self.assertTrue(item['event']['excerpt'])
        self.assertNotIn('\ufffd', item['event']['message'])

    def test_corrupt_or_oversized_store_is_never_overwritten(self):
        self.file.parent.mkdir()
        for data in (b'bad json', b'x' * (s.MAX_FILE_BYTES + 1)):
            self.file.write_bytes(data)
            with self.assertRaises(ValueError):
                s.save_view(None, 'New', {})
            self.assertEqual(self.file.read_bytes(), data)

    def test_atomic_failure_retains_previous_store_and_removes_temporary_file(self):
        s.save_view(None, 'Original', {})
        original = self.file.read_bytes()
        with patch.object(s.os, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                s.save_view(None, 'New', {})
        self.assertEqual(self.file.read_bytes(), original)
        self.assertEqual(list(self.file.parent.iterdir()), [self.file])

    def test_limits_refuse_new_items_but_allow_replacement(self):
        with patch.object(s, 'MAX_ITEMS', 1):
            s.save_view(None, 'One', {})
            with self.assertRaises(ValueError):
                s.save_view(None, 'Two', {})
            s.save_view(None, 'One', {'search': 'updated'})
        self.assertEqual(s.load()['views'][0]['settings']['search'], 'updated')
        with self.assertRaises(ValueError):
            s.save_view(None, 'Too long', {'search': 'x' * 513})


try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    from syslogapp.pages.logs import LogsPage
    from syslogapp.pages.network import NetworkPage
    from syslogapp.saved_ui import SavedDialog, locate_event
    DISPLAY = Gtk.init_check()[0]
except ImportError:
    DISPLAY = False


@unittest.skipUnless(DISPLAY, 'No GTK display')
class SavedUITests(unittest.TestCase):
    host = StorageTests.host
    row = StorageTests.row

    def setUp(self):
        StorageTests.setUp(self)
        self.window = Gtk.Window()
        self.window.toast = Mock()
        self.app = SimpleNamespace(config={}, window=self.window, run_async=Mock())
        self.page = LogsPage(self.app)
        self.addCleanup(self.window.destroy)
        self.addCleanup(self.page.destroy)

    def test_apply_saved_log_view_pauses_restores_filters_and_issues_one_query(self):
        item = s.save_view(None, 'Investigation', dict(scope='previous', priority='Warning',
                    search='failed', unit='ssh.service', history={'since': '@100', 'until': '@200'}))
        self.page._apply_saved_view(item)
        self.assertFalse(self.page.live.get_active())
        self.assertEqual(self.page.scope.get_active_id(), 'previous')
        self.assertEqual(self.page.unit.get_text(), 'ssh.service')
        self.assertEqual(self.page.search.get_text(), 'failed')
        self.assertEqual(self.app.run_async.call_count, 1)
        with patch('syslogapp.pages.logs.load_logs', return_value=[]) as load:
            self.app.run_async.call_args.args[0]()
        self.assertEqual(load.call_args.kwargs['boot'], -1)
        self.assertEqual(load.call_args.kwargs['since'], '@100')

    def test_manager_only_shows_current_host_and_page_and_reads_nothing_remotely(self):
        s.save_view(None, 'Local logs', {})
        s.save_view(self.host(), 'Remote logs', {})
        s.save_view(None, 'Local network', {'page': 'network'})
        s.bookmark(None, 'Local event', self.row())
        s.bookmark(self.host(), 'Remote event', self.row())
        dialog = SavedDialog(self.page)
        try:
            self.assertEqual([r[0] for r in dialog.tables['views'].get_model()], ['Local logs'])
            self.assertEqual([r[0] for r in dialog.tables['bookmarks'].get_model()], ['Local event'])
            self.app.run_async.assert_not_called()
        finally:
            dialog.destroy()

    def test_locate_rejects_nearby_event_after_rotation_and_routes_to_selected_host(self):
        host = self.host()
        item = s.bookmark(host, 'Remote', self.row())
        with patch('syslogapp.saved_ui.journal_records', return_value=[{'__CURSOR': 'other'}]) as read:
            with self.assertRaisesRegex(Exception, 'no longer available'):
                locate_event(item, host)
        self.assertIs(read.call_args.kwargs['host'], host)
        with patch('syslogapp.saved_ui.journal_records', return_value=[{'__CURSOR': 'cursor', '_BOOT_ID': 'boot', 'MESSAGE': 'original'}]):
            self.assertEqual(locate_event(item, host), 'original')
        with patch('syslogapp.saved_ui.journal_records', return_value=[{'__CURSOR': 'cursor', '_BOOT_ID': 'other'}]):
            with self.assertRaisesRegex(Exception, 'boot does not match'):
                locate_event(item, host)

    def test_network_view_applies_loaded_filters_without_polling(self):
        page = NetworkPage(self.app)
        try:
            item = s.save_view(None, 'Network', dict(page='network', kind=2, search='ssh',
                               processes='extended', hide_time_wait=True, application='ssh', pid='123', port='22', port_side='local'))
            page._apply_saved_view(item)
            self.assertFalse(page.live.get_active())
            self.assertEqual(page.kind.get_active(), 2)
            self.assertTrue(page.hide_time_wait.get_active())
            self.assertEqual(page.process_details.get_active_id(), 'extended')
            self.assertEqual(page.application_filter.get_text(), 'ssh')
            self.assertEqual(page.pid_filter.get_text(), '123')
            self.assertEqual(page.port_filter.get_text(), '22')
            self.assertEqual(page.port_side.get_active_id(), 'local')
            self.app.run_async.assert_not_called()
        finally:
            page.destroy()

    def test_save_actions_cancel_without_writes_and_bookmark_original_message(self):
        with patch('syslogapp.saved_ui.ask_name', return_value=None):
            self.page._save_view()
        self.assertFalse(self.file.exists())
        row = self.row()
        row['priority'] = 4
        row['message'] = 'first second'
        self.page._loaded([row], None)
        self.page.tree.get_selection().select_path(0)
        with patch('syslogapp.saved_ui.ask_name', return_value='Investigation event'):
            self.page._bookmark_selected()
        item = s.load()['bookmarks'][0]
        self.assertEqual(item['event']['message'], 'first\nsecond')
        self.assertEqual(item['event']['cursor'], 'cursor')

    def test_late_locate_callback_after_dialog_close_is_ignored(self):
        s.bookmark(None, 'Event', self.row())
        dialog = SavedDialog(self.page)
        dialog.tables['bookmarks'].get_selection().select_path(0)
        button = Gtk.Button()
        dialog._locate(button, 'bookmarks')
        done = self.app.run_async.call_args.args[1]
        dialog.destroy()
        done('late result', None)
        button.destroy()

    def test_foreign_host_view_is_not_applied(self):
        item = s.save_view(self.host(), 'Remote only', {})
        self.page._apply_saved_view(item)
        self.app.run_async.assert_not_called()
        self.window.toast.assert_called_once()
