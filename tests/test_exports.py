# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import csv
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from syslogapp import exports as e


def event(message='first\nsecond'):
    return {'type': 'event', 'time': '2026-10-25 12:00:00', 'unit': 'ssh.service',
            'level': 'Warning', 'message': message, 'raw': {'MESSAGE': message, '__CURSOR': 'cursor', 'binary': [0, 10, 255]}}


def meta():
    return e.metadata('logs', None, {'loaded_text': 'denied', 'unit': 'ssh.service'}, False, 2, 10)


class ExportTests(unittest.TestCase):
    def test_jsonl_preserves_raw_multiline_unicode_binary_and_metadata(self):
        row = event('first\n\u03b1\u03b2 second')
        rows = list(map(json.loads, e.render([row], meta()).splitlines()))
        self.assertEqual(rows[0]['type'], 'metadata')
        self.assertEqual(rows[0]['entry_count'], 1)
        self.assertIn('UTC', rows[0]['display_timezone'])
        self.assertEqual(rows[0]['filters']['unit'], 'ssh.service')
        self.assertEqual(rows[1], row)
        self.assertEqual(rows[1]['raw']['binary'], [0, 10, 255])

    def test_historical_event_offsets_follow_daylight_saving_time(self):
        import time
        from datetime import datetime, timezone
        from syslogapp.export_capture import event_time_iso
        try:
            with patch.dict(os.environ, {'TZ': 'Europe/Athens'}):
                time.tzset()
                winter = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()) * 1_000_000 + 123456
                summer = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()) * 1_000_000 + 123456
                self.assertTrue(event_time_iso({'__REALTIME_TIMESTAMP': str(winter)}).endswith('.123456+02:00'))
                self.assertTrue(event_time_iso({'__REALTIME_TIMESTAMP': str(summer)}).endswith('.123456+03:00'))
        finally:
            time.tzset()

    def test_redaction_covers_messages_raw_metadata_known_names_and_addresses(self):
        text = 'Accepted password for alice from 192.0.2.7 at db01 and api.example.com. [2001:db8::7] host=other01 /home/alice/x'
        row = event(text)
        context = meta()
        context['source'].update(hostname='db01', username='alice')
        context['filters']['loaded_text'] = '192.0.2.7'
        original = copy.deepcopy((row, context))
        result = e.render([row], context, options={'ips': True, 'hosts': True, 'users': True}, hosts=['db01'], users=['alice'])
        for sensitive in ('alice', '192.0.2.7', '2001:db8::7', 'db01', 'api.example.com', 'other01'):
            self.assertNotIn(sensitive, result)
        self.assertIn('ssh.service', result)
        self.assertIn('<BINARY OMITTED>', result)
        records = list(map(json.loads, result.splitlines()))
        self.assertEqual(records[1]['message'], records[1]['raw']['MESSAGE'])
        self.assertEqual((row, context), original)
        self.assertTrue(records[0]['redaction']['best_effort'])

    def test_ip_detection_handles_ipv6_mapped_scopes_and_keeps_timestamps_and_invalid_ips(self):
        redactor = e.Redactor({'ips': True})
        self.assertEqual(redactor.string('192.0.2.1 ::ffff:192.0.2.1'), '<IP1> <IP1>')
        self.assertIn('<IP', redactor.string('[fe80::1%eth0]:443'))
        self.assertEqual(redactor.string('12:34:56 999.1.1.1'), '12:34:56 999.1.1.1')
        self.assertIn('<IP', redactor.string('address=::'))

    def test_redaction_options_are_independent_and_custom_is_literal(self):
        value = 'alice@db01 192.0.2.1 secret.*'
        self.assertEqual(e.Redactor({'users': True}, users=['alice']).string(value), '<USER1>@db01 192.0.2.1 secret.*')
        self.assertEqual(e.Redactor({'custom': 'secret.*'}).string(value), 'alice@db01 192.0.2.1 <TEXT1>')
        self.assertEqual(e.Redactor({'users': True}).string('for request 123'), 'for request 123')
        output = e.render([event()], meta(), options={'custom': '  \n'})
        self.assertEqual(json.loads(output.splitlines()[1])['raw']['binary'], [0, 10, 255])

    def test_spreadsheet_csv_quotes_and_neutralizes_formula_prefixes(self):
        for message in ('=1+1', '+cmd', '-cmd', '@SUM(A1)', '\t=1', '\r=1', '  =1', '\ufeff=1', '\x00=1'):
            output = e.render([event(message)], meta(), 'csv')
            rows = list(csv.DictReader(io.StringIO(output, newline='')))
            self.assertTrue(rows[0]['Message'].startswith("'"), message)
            self.assertIn('Source host', rows[0])
            self.assertIn('Active filters', rows[0])
        normal = 'plain, "quoted"\nsecond line'
        output = e.render([event(normal)], meta(), 'csv')
        self.assertEqual(list(csv.DictReader(io.StringIO(output, newline='')))[0]['Message'], normal)

    def test_remote_metadata_never_contains_credentials_or_key_paths(self):
        host = SimpleNamespace(profile=dict(hostname='server', username='alice', port=2222,
                                           password='do not export', key_file='/private/key'), label='My server')
        context = e.metadata('logs', host, {}, False, 1, 1)
        output = e.render([event()], context, 'csv')
        self.assertNotIn('do not export', output)
        self.assertNotIn('/private/key', output)
        self.assertEqual(list(csv.DictReader(io.StringIO(output)))[0]['SSH port'], '2222')

    def test_limits_fail_without_partial_document_or_unbounded_alias_map(self):
        with patch.object(e, 'MAX_EXPORT_BYTES', 100):
            with self.assertRaisesRegex(ValueError, '32 MiB'):
                e.render([event()], meta())
        with patch.object(e, 'MAX_REDACTION_TOKENS', 1):
            with self.assertRaisesRegex(ValueError, 'distinct redaction'):
                e.Redactor({'ips': True}).string('192.0.2.1 192.0.2.2')
        with self.assertRaises(ValueError):
            e.Redactor({'custom': 'x' * 257})

    def test_atomic_save_is_private_and_failed_save_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'export.jsonl'
            e.write_atomic(path, 'original\n')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with patch.object(e.os, 'replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    e.write_atomic(path, 'replacement\n')
            self.assertEqual(path.read_text(), 'original\n')
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_structural_schema_is_not_redacted_and_long_domain_like_input_is_bounded(self):
        context = meta()
        output = e.render([event()], context, options={'custom': 'syslogapp'})
        self.assertEqual(json.loads(output.splitlines()[0])['schema'], 'syslogapp-export/v1')
        text = 'a.' * 32000 + '9'
        self.assertEqual(e.Redactor({'hosts': True}).string(text), text)

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    from syslogapp.pages.logs import LogsPage
    from syslogapp.pages.network import NetworkPage
    from syslogapp.export_capture import snapshot
    from syslogapp.export_ui import ExportDialog
    DISPLAY = Gtk.init_check()[0]
except ImportError:
    DISPLAY = False


@unittest.skipUnless(DISPLAY, 'No GTK display')
class ExportUITests(unittest.TestCase):
    def setUp(self):
        self.window = Gtk.Window()
        self.window.toast = Mock()
        self.app = SimpleNamespace(config={}, window=self.window, run_async=Mock())
        self.page = LogsPage(self.app)
        self.addCleanup(self.window.destroy)
        self.addCleanup(self.page.destroy)
        rows = [dict(time=f'2026-10-25 12:00:0{i}', unit='ssh.service', level='Info', priority=6,
                     message=f'event {i}', raw={'MESSAGE': f'event {i}\nfrom 192.0.2.7', '__CURSOR': f'cursor{i}'}) for i in range(4)]
        self.page._loaded(rows, None)

    def dialog(self):
        dialog = ExportDialog(self.page, snapshot(self.page))
        self.addCleanup(dialog.destroy)
        return dialog

    def test_selection_export_uses_complete_touched_entries_and_current_sort_order(self):
        self.page.store.set_sort_column_id(0, Gtk.SortType.DESCENDING)
        access = self.page.text_access
        col = self.page.tree_columns[0]
        access._anchor = access._point(Gtk.TreePath.new_from_indices([1]), col, 0)
        access._end = access._point(Gtk.TreePath.new_from_indices([3]), col, 0)
        data = snapshot(self.page)
        self.assertEqual(data['selected'], [1, 2])
        self.assertEqual([r['raw']['__CURSOR'] for r in data['records']], ['cursor3', 'cursor2', 'cursor1', 'cursor0'])
        dialog = self.dialog()
        self.assertEqual(dialog.scope.get_active_id(), 'selected')
        dialog._preview()
        work, done = self.app.run_async.call_args.args
        done(work(), None)
        records = list(map(json.loads, dialog.document.splitlines()))
        self.assertEqual(records[0]['entry_count'], 2)
        self.assertEqual([r['raw']['__CURSOR'] for r in records[1:]], ['cursor2', 'cursor1'])
        self.assertIn('\nfrom 192.0.2.7', records[1]['message'])

    def test_preview_is_explicit_and_changed_options_never_save_stale_content(self):
        dialog = self.dialog()
        self.app.run_async.assert_not_called()
        self.assertFalse(dialog.save_button.get_sensitive())
        dialog._preview()
        work, done = self.app.run_async.call_args.args
        dialog.redactions['ips'].set_active(True)
        done(work(), None)
        self.assertIsNone(dialog.document)
        self.assertFalse(dialog.save_button.get_sensitive())
        dialog._preview()
        work, done = self.app.run_async.call_args.args
        done(work(), None)
        self.assertNotIn('192.0.2.7', dialog.document)
        self.assertTrue(dialog.save_button.get_sensitive())
        dialog.format.set_active_id('csv')
        self.assertIsNone(dialog.document)
        self.assertFalse(dialog.save_button.get_sensitive())

    def test_preview_pages_are_bounded_and_late_closed_dialog_result_is_ignored(self):
        dialog = self.dialog()
        dialog.document = 'a' * (e.PREVIEW_CHARS * 2 + 20)
        dialog._show_page(2)
        buffer = dialog.preview.get_buffer()
        self.assertEqual(len(buffer.get_text(*buffer.get_bounds(), True)), 20)
        self.assertIn('3 / 3', dialog.page_label.get_text())
        dialog._preview()
        done = self.app.run_async.call_args.args[1]
        dialog.destroy()
        done('late data', None)
        self.assertIsNone(dialog.document)

    def test_network_exports_raw_queues_and_staleness_without_new_queries(self):
        page = NetworkPage(self.app)
        self.addCleanup(page.destroy)
        page.live.set_active(False)
        page.kind.set_active(0)
        row = dict(protocol='TCP', state='ESTAB', local='127.0.0.1:22', peer='192.0.2.1:1234',
                   process='users:(("ssh",pid=123,fd=4))', recv='1', send='2')
        result = dict(interfaces=[], routes=[], sockets=[row, dict(row, recv='3')], errors=[],
                      time='12:00:00', limited=False, processes=True)
        page._loaded(result, None)
        page._loaded(dict(result, time='12:00:02', sockets=None, errors=['Sockets: failed']), None)
        data = snapshot(page)
        self.assertTrue(data['metadata']['view_state']['stale'])
        self.assertEqual(data['metadata']['view_state']['last_successful_socket_update'], '12:00:00')
        self.assertEqual({r['raw']['recv'] for r in data['records']}, {'1', '3'})
        self.app.run_async.assert_not_called()
        csv_rows = list(csv.DictReader(io.StringIO(e.render(data['records'], data['metadata'], 'csv'))))
        self.assertEqual(csv_rows[0]['Remote address'], '192.0.2.1')

    def test_cancelled_save_does_not_create_file(self):
        dialog = self.dialog()
        dialog.document = 'data'
        with patch('syslogapp.export_ui.Gtk.FileChooserDialog') as chooser, patch('syslogapp.export_ui.write_atomic') as write:
            chooser.return_value.run.return_value = Gtk.ResponseType.CANCEL
            self.assertFalse(dialog.save())
        write.assert_not_called()
