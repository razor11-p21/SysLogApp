# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from syslogapp import process_probe as probe
from syslogapp import process_details as details
from syslogapp import services


def connection(pid=123, fd=4):
    return ('TCP', 'ESTAB', '127.0.0.1', '4660', '127.0.0.1', '80', str(pid), 'worker',
            f'users:(("worker",pid={pid},fd={fd}))')


class ProbeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.base = self.root / '123'
        (self.base / 'net').mkdir(parents=True)
        (self.base / 'fd').mkdir()
        fields = ['S', '1'] + ['0'] * 17 + ['12345']
        (self.base / 'stat').write_text('123 (worker with ) name) ' + ' '.join(fields))
        (self.base / 'status').write_text('Uid:\t1000 1000 1000 1000\nVmRSS:\t100 kB\n')
        (self.base / 'cmdline').write_bytes(b'worker\x00--argument\x00')
        (self.base / 'cgroup').write_text('0::/user.slice/user-1000.slice/user@1000.service/app.slice/demo.service\n')
        (self.base / 'fd/4').symlink_to('socket:[9876]')
        (self.base / 'exe').symlink_to('/usr/bin/worker')
        (self.base / 'cwd').symlink_to('/tmp')
        (self.base / 'net/tcp').write_text('header\n0: 0100007F:1234 0100007F:0050 01 0:0 00:0 0 1000 0 9876\n')
        boot = self.root / 'sys/kernel/random'
        boot.mkdir(parents=True)
        (boot / 'boot_id').write_text('01234567-89ab-cdef-0123-456789abcdef\n')
        self.payload = dict(pid=123, fd=4, protocol='TCP', local='127.0.0.1', local_port='4660', peer='127.0.0.1', peer_port='80')

    def test_verified_descriptor_reports_details_and_user_unit_without_process_scans(self):
        result = probe.inspect_connection(self.payload, self.root)
        self.assertEqual(result['name'], 'worker with ) name')
        self.assertEqual(result['command'], 'worker --argument')
        self.assertEqual(result['unit'], 'demo.service')
        self.assertTrue(result['user_unit'])
        self.assertEqual(result['uid'], '1000')
        self.assertEqual(result['boot'], '0123456789abcdef0123456789abcdef')

    def test_stale_descriptor_or_wrong_endpoints_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'no longer owns'):
            probe.inspect_connection(dict(self.payload, peer_port='443'), self.root)
        (self.base / 'fd/4').unlink()
        (self.base / 'fd/4').symlink_to('/tmp/a-file')
        with self.assertRaisesRegex(ValueError, 'no longer refers'):
            probe.inspect_connection(self.payload, self.root)

    def test_process_reuse_during_inspection_is_rejected(self):
        original = probe.stat_identity(self.base / 'stat')
        with patch.object(probe, 'stat_identity', side_effect=[original, ('new-start', *original[1:])]):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                probe.inspect_connection(self.payload, self.root)

    def test_descriptor_reuse_during_inspection_is_rejected(self):
        original = probe.os.readlink
        calls = []
        def readlink(path):
            if str(path).endswith('/fd/4'):
                calls.append(path)
                return 'socket:[9876]' if len(calls) == 1 else 'socket:[9999]'
            return original(path)
        with patch.object(probe.os, 'readlink', side_effect=readlink):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                probe.inspect_connection(self.payload, self.root)

    def test_optional_permission_failure_does_not_invent_values(self):
        (self.base / 'exe').unlink()
        result = probe.inspect_connection(self.payload, self.root)
        self.assertEqual(result['exe'], 'Unavailable')
        self.assertIn('Executable:', result['warnings'][0])

    def test_large_proc_tables_and_invalid_pid_are_bounded(self):
        (self.base / 'net/tcp').write_bytes(b'x' * (2 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, 'size limit'):
            probe.inspect_connection(self.payload, self.root)
        with self.assertRaisesRegex(ValueError, 'Invalid process'):
            probe.inspect_connection(dict(self.payload, pid='../etc'), self.root)

    def test_v1_unit_scope_and_mapped_ipv6_and_wildcard_endpoints(self):
        self.assertEqual(probe.associated_unit('1:name=systemd:/system.slice/ssh.service'), ('ssh.service', False))
        self.assertEqual(probe.associated_unit('0::/plain/container'), (None, False))
        self.assertEqual(probe.normalized_ip('::ffff:127.0.0.1'), '127.0.0.1')
        self.assertTrue(probe.endpoint_matches(('::', 0), '*', '*'))


class ConnectionTests(unittest.TestCase):
    def test_multiple_owners_are_explicit_and_deduplicated(self):
        values = list(connection())
        values[8] += ',("other",pid=999,fd=5),("worker",pid=123,fd=4)'
        self.assertEqual(details.owners(values), [(123, 4), (999, 5)])
        with self.assertRaises(services.CheckUnavailable):
            details.collect(values, (100, 6))

    def test_remote_probe_is_bounded_and_uses_selected_host_python(self):
        host = Mock()
        host.supports_python.return_value = True
        host.which.return_value = '/usr/bin/python3'
        host.capture.return_value = (json.dumps({'pid': 123, 'fd': 4}), False)
        self.assertEqual(details.collect(connection(), (123, 4), host)['pid'], 123)
        args = host.capture.call_args.args[0]
        self.assertEqual(args[:2], ['/usr/bin/python3', '-c'])
        self.assertEqual(json.loads(args[-1])['local_port'], '4660')
        self.assertEqual(host.capture.call_args.kwargs['max_bytes'], 128 * 1024)
        host.capture.return_value = ('{}', True)
        with self.assertRaises(services.CheckUnavailable):
            details.collect(connection(), (123, 4), host)
        host.supports_python.return_value = False
        with self.assertRaisesRegex(services.CheckUnavailable, 'Python 3.8'):
            details.collect(connection(), (123, 4), host)

    def test_related_logs_use_boot_and_exact_system_or_user_fields(self):
        host = Mock()
        for user in (False, True):
            with patch.object(details, 'load_logs', return_value=[]) as load:
                details.related_logs(dict(unit='demo.service', user_unit=user, uid='1000', boot='abc'), host)
            fields = load.call_args.kwargs['journal_match']
            self.assertEqual(fields['_BOOT_ID'], 'abc')
            self.assertIs(load.call_args.kwargs['host'], host)
            self.assertFalse(load.call_args.kwargs['boot_only'])
            if user:
                self.assertEqual(fields['_SYSTEMD_USER_UNIT'], 'demo.service')
                self.assertEqual(fields['_UID'], '1000')
                self.assertNotIn('_SYSTEMD_UNIT', fields)
            else:
                self.assertEqual(fields['_SYSTEMD_UNIT'], 'demo.service')
        with self.assertRaises(services.CheckUnavailable):
            details.related_logs({'unit': None, 'boot': 'abc'})

    def test_journal_fields_are_literal_and_restricted(self):
        with patch.object(services, 'run_command', return_value=(0, '', '')) as run:
            services.load_logs(journal_match={'_SYSTEMD_UNIT': 'a;$(id).service', '_BOOT_ID': 'abc'})
        self.assertIn('_SYSTEMD_UNIT=a;$(id).service', run.call_args.args[0])
        with self.assertRaises(services.CheckUnavailable):
            services.load_logs(journal_match={'--anything': 'x'})

    def test_real_loopback_owner_verification_ipv4_and_ipv6(self):
        for family, address in ((socket.AF_INET, '127.0.0.1'), (socket.AF_INET6, '::1')):
            sockets = []
            try:
                try:
                    server = socket.socket(family)
                    sockets.append(server)
                    server.bind((address, 0))
                except PermissionError:
                    self.skipTest('Sandbox blocks socket creation')
                except OSError:
                    if family == socket.AF_INET6:
                        continue
                    raise
                server.listen(1)
                client = socket.socket(family)
                sockets.append(client)
                client.connect(server.getsockname())
                accepted, _ = server.accept()
                sockets.append(accepted)
                result = probe.inspect_connection(dict(pid=os.getpid(), fd=client.fileno(), protocol='TCP',
                    local=address, local_port=str(client.getsockname()[1]), peer=address, peer_port=str(server.getsockname()[1])))
                self.assertEqual(result['pid'], os.getpid())
                self.assertEqual(result['fd'], client.fileno())
            finally:
                for sock in sockets:
                    sock.close()

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    from syslogapp.process_ui import ProcessDialog
    from syslogapp.pages.network import NetworkPage
    DISPLAY = Gtk.init_check()[0]
except ImportError:
    DISPLAY = False


@unittest.skipUnless(DISPLAY, 'No GTK display')
class ProcessUITests(unittest.TestCase):
    def setUp(self):
        self.window = Gtk.Window()
        self.window.toast = Mock()
        self.app = SimpleNamespace(config={}, run_async=Mock(), window=self.window)
        self.page = NetworkPage(self.app)
        self.addCleanup(self.window.destroy)
        self.addCleanup(self.page.destroy)
        self.result = dict(pid=123, fd=4, name='worker', parent='1', uid='1000', state='S',
                           exe='/bin/worker', cwd='/tmp', command='worker --argument', rss='100 kB',
                           unit='demo.service', user_unit=False, boot='abc', time='2026-10-25 12:00:00', warnings=[])

    def dialog(self, show_logs=False):
        dialog = ProcessDialog(self.page, connection(), show_logs)
        self.addCleanup(dialog.destroy)
        dialog.show_all()
        return dialog

    def test_process_action_reads_only_on_start_and_journal_only_when_tab_opened(self):
        dialog = self.dialog()
        self.app.run_async.assert_not_called()
        dialog.start()
        work, done = self.app.run_async.call_args.args
        with patch('syslogapp.process_ui.collect', return_value=self.result) as read:
            done(work(), None)
        read.assert_called_once_with(connection(), (123, 4), None)
        self.assertEqual(self.app.run_async.call_count, 1)
        dialog.notebook.set_current_page(1)
        self.assertEqual(self.app.run_async.call_count, 2)
        with patch('syslogapp.process_ui.related_logs', return_value=[]) as logs:
            work, done = self.app.run_async.call_args.args
            done(work(), None)
        logs.assert_called_once_with(self.result, None)
        dialog.notebook.set_current_page(0)
        dialog.notebook.set_current_page(1)
        self.assertEqual(self.app.run_async.call_count, 2)

    def test_service_action_resolves_owner_then_reads_logs_on_selected_host(self):
        self.page.host = SimpleNamespace(target='alice@remote:22')
        dialog = self.dialog(True)
        dialog.start()
        self.assertEqual(self.app.run_async.call_count, 1)
        self.app.run_async.call_args.args[1](self.result, None)
        self.assertEqual(self.app.run_async.call_count, 2)
        with patch('syslogapp.process_ui.related_logs', return_value=[]) as read:
            self.app.run_async.call_args.args[0]()
        self.assertIs(read.call_args.args[1], self.page.host)

    def test_late_result_after_close_and_old_owner_result_are_ignored(self):
        values = list(connection())
        values[8] += ',("other",pid=999,fd=5)'
        dialog = ProcessDialog(self.page, values)
        self.addCleanup(dialog.destroy)
        dialog.show_all()
        dialog.start()
        old_done = self.app.run_async.call_args.args[1]
        dialog.owner.set_active(1)
        self.assertEqual(self.app.run_async.call_count, 1)
        old_done(self.result, None)
        self.assertIsNone(dialog.details)
        self.assertEqual(self.app.run_async.call_count, 2)
        done = self.app.run_async.call_args.args[1]
        dialog.destroy()
        done(self.result, None)
        self.assertIsNone(dialog.details)

    def test_failed_verification_never_queries_service_logs(self):
        dialog = self.dialog(True)
        dialog.start()
        self.app.run_async.call_args.args[1](None, RuntimeError('Connection changed'))
        self.assertEqual(self.app.run_async.call_count, 1)
        self.assertIsNone(dialog.details)
        buffer = dialog.views[1].get_buffer()
        self.assertIn('could not be verified', buffer.get_text(*buffer.get_bounds(), True))

    def test_missing_owner_action_is_clear_and_does_not_fetch(self):
        values = list(connection())
        values[8] = ''
        with patch.object(self.page, '_selected_key', return_value=tuple(values)):
            self.page._inspect_selected()
        self.app.run_async.assert_not_called()
        self.window.toast.assert_called_once()

    def test_related_log_text_is_multiline_selectable_and_has_severity_color(self):
        dialog = self.dialog(True)
        dialog.start()
        self.app.run_async.call_args.args[1](self.result, None)
        row = dict(time='2026-10-25 12:00:00', level='Error', priority=3, message='first second', raw={'MESSAGE': 'first\nsecond'})
        self.app.run_async.call_args.args[1]([row], None)
        buffer = dialog.views[1].get_buffer()
        self.assertIn('first\nsecond', buffer.get_text(*buffer.get_bounds(), True))
        self.assertIsNotNone(buffer.get_tag_table().lookup('priority-3'))
        self.assertFalse(dialog.views[1].get_editable())
