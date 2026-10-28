# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, mock_open, patch
from syslogapp import overview as o

MOUNTS = ('1 0 8:1 / / rw - ext4 /dev/sda1 rw\n'
          '2 1 8:2 / /home\\040space rw - ext4 /dev/sda2 rw\n'
          '3 1 0:1 / /proc rw - proc proc rw\n'
          '4 1 0:2 / /mnt/share rw - nfs server:/share rw\n'
          '5 1 8:2 / /alias rw - ext4 /dev/sda2 rw\n')


def usage(total=1000, used=400, available=500):
    return dict(total=total, used=used, available=available, percent=44.4)


class OverviewDiagnosticTests(unittest.TestCase):
    def test_mount_parser_decodes_names_and_separates_virtual_network_and_read_only(self):
        rows = o.parse_mounts(MOUNTS)
        self.assertEqual(rows[0]['mount'], '/')
        self.assertIn('/home space', [r['mount'] for r in rows])
        self.assertTrue(next(r for r in rows if r['mount'] == '/proc')['virtual'])
        self.assertTrue(next(r for r in rows if r['mount'] == '/mnt/share')['network'])
        self.assertTrue(o.parse_mounts('1 0 8:1 / / ro - ext4 /dev/sda1 ro')[0]['read_only'])
        with self.assertRaises(ValueError):
            o.parse_mounts('not a mount record')

    def test_filesystem_usage_skips_network_by_default_and_reuses_bind_statistics(self):
        def command(args, **kwargs):
            jobs = [json.loads(value) for value in args[3:]]
            self.assertEqual(len(jobs), 2)
            self.assertNotIn('/mnt/share', [job['path'] for job in jobs])
            return '\n'.join(json.dumps({'id': job['id'], 'usage': usage()}) for job in jobs), None
        with patch('builtins.open', mock_open(read_data=MOUNTS.encode())), patch.object(o, 'bounded_command', side_effect=command):
            result = o.filesystem_snapshot()
        self.assertEqual(result['total'], 5)
        items = {item['mount']: item for item in result['items']}
        self.assertEqual(items['/alias']['usage'], items['/home space']['usage'])
        self.assertIn('Not checked', items['/mnt/share']['error'])
        self.assertIn('Not applicable', items['/proc']['error'])

    def test_partial_timeout_preserves_completed_usage_without_marking_missing_checks_healthy(self):
        output = json.dumps({'id': 0, 'usage': usage()}) + '\n' + json.dumps({'checking': 1})
        with patch('builtins.open', mock_open(read_data=MOUNTS.encode())), patch.object(o, 'bounded_command', return_value=(output, 'check timed out')):
            result = o.filesystem_snapshot(include_remote=True)
        items = {item['mount']: item for item in result['items']}
        self.assertIsNotNone(items['/']['usage'])
        self.assertIsNone(items['/alias']['usage'])
        self.assertIn('Unavailable:', items['/alias']['error'])
        self.assertIn('Not checked:', items['/mnt/share']['error'])

    def test_mount_limits_and_failed_mount_read_are_explicit(self):
        with patch('builtins.open', mock_open(read_data=MOUNTS.encode())), patch.object(o, 'MAX_MOUNTS', 2), patch.object(o, 'bounded_command', return_value=('', 'failed')):
            result = o.filesystem_snapshot()
        self.assertTrue(result['limited'])
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(result['total'], 5)
        with patch('builtins.open', side_effect=PermissionError('not permitted')):
            result = o.filesystem_snapshot()
        self.assertIn('not permitted', result['error'])
        self.assertIsNone(result['total'])

    def test_failed_service_empty_success_is_distinct_from_unavailable_or_malformed(self):
        with patch.object(o.shutil, 'which', return_value='/usr/bin/systemctl'):
            with patch.object(o, 'bounded_command', return_value=('', None)):
                self.assertEqual(o.failed_services(), {'items': [], 'limited': False, 'error': None})
            with patch.object(o, 'bounded_command', return_value=('', 'access denied')):
                self.assertEqual(o.failed_services()['error'], 'access denied')
            with patch.object(o, 'bounded_command', return_value=('bad response', None)):
                self.assertIn('unexpected', o.failed_services()['error'])
            with patch.object(o, 'bounded_command', return_value=('demo.service loaded failed failed Example daemon\n', None)) as command:
                data = o.failed_services()
            self.assertEqual(data['items'][0]['unit'], 'demo.service')
            self.assertIn('--system', command.call_args.args[0])
        with patch.object(o.shutil, 'which', return_value=None):
            self.assertIn('not installed', o.failed_services()['error'])

    def test_reboot_marker_absence_is_not_a_universal_no_reboot_claim(self):
        with patch.object(o.os, 'stat', return_value=Mock()):
            self.assertEqual(o.reboot_status()['state'], 'required')
        with patch.object(o.os, 'stat', side_effect=FileNotFoundError), patch.object(o, 'read_text', return_value='ID=linuxmint\nID_LIKE="ubuntu debian"'):
            result = o.reboot_status()
        self.assertEqual(result['state'], 'not_reported')
        self.assertIn('not a complete', result['message'])
        with patch.object(o.os, 'stat', side_effect=FileNotFoundError), patch.object(o, 'read_text', return_value='ID=fedora'):
            self.assertEqual(o.reboot_status()['state'], 'unavailable')
        with patch.object(o.os, 'stat', side_effect=PermissionError('denied')):
            self.assertEqual(o.reboot_status()['state'], 'unavailable')

    def test_bounded_command_keeps_partial_output_and_stops_timed_out_helper(self):
        output, error = o.bounded_command([sys.executable, '-u', '-c', 'import time; print("partial",flush=True); time.sleep(3)'], timeout=.1)
        self.assertIn('partial', output)
        self.assertIn('timed out', error)
        output, error = o.bounded_command([sys.executable, '-c', 'print("x" * 100000)'], max_bytes=100)
        self.assertLessEqual(len(output), 100)
        self.assertIn('size limit', error)

    def test_success_exit_with_diagnostic_is_not_an_empty_healthy_check(self):
        output, error = o.bounded_command([sys.executable, '-c', 'import sys; sys.stderr.write("Permission denied")'])
        self.assertEqual(output, '')
        self.assertEqual(error, 'Permission denied')

    def test_remote_overview_forwards_opt_in_and_budgets_output(self):
        from syslogapp.hosts import SSHHost
        host = SSHHost(dict(hostname='remote', username='alice', port=22, auth='key'))
        self.addCleanup(host.close)
        host.tools = {'python3': '/usr/bin/python3'}
        host.python_version = (3, 8)
        with patch.object(host, 'capture', return_value=(json.dumps({'rows': [], 'time': 'now'}), False)) as collect:
            host.overview(include_remote=True)
        self.assertIn('snapshot(include_remote=True)', collect.call_args.args[0][2])
        self.assertEqual(collect.call_args.kwargs['max_bytes'], 256 * 1024)


try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    from syslogapp.pages.overview import OverviewPage
    DISPLAY = Gtk.init_check()[0]
except ImportError:
    DISPLAY = False


@unittest.skipUnless(DISPLAY, 'No GTK display')
class OverviewDiagnosticUITests(unittest.TestCase):
    def setUp(self):
        self.window = Gtk.Window()
        self.window.toast = Mock()
        self.window.active_host = None
        self.window.pages = {'logs': SimpleNamespace(navigate=Mock())}
        self.window.notebook = Mock()
        self.app = SimpleNamespace(config={}, run_async=Mock(), window=self.window)
        self.page = OverviewPage(self.app)
        self.addCleanup(self.window.destroy)
        self.addCleanup(self.page.destroy)
        mounts = o.parse_mounts(MOUNTS)
        for item in mounts:
            item['usage'] = usage() if not item['virtual'] else None
        self.result = dict(rows=[('System', 'Linux Mint', '#6aa8ff'), ('Reboot notice', 'Unavailable: not supported', '#ffb34c')],
                           time='12:00:00', filesystems=dict(items=mounts, total=5, limited=False, error=None),
                           failed_services=dict(items=[dict(unit='demo.service', active='failed', sub='failed', description='Example')], error=None, limited=False))

    def test_failed_service_navigation_is_explicit_and_host_scoped(self):
        self.page._done(self.result, None)
        path = next(row.path for row in self.page.store if row[0] == 'Service · demo.service')
        self.page.tree.get_selection().select_path(path)
        self.assertTrue(self.page.service_logs.get_sensitive())
        self.window.pages['logs'].navigate.assert_not_called()
        self.page._show_service_logs()
        self.window.pages['logs'].navigate.assert_called_once_with(unit='demo.service', priority='All', search='', scope='boot')
        self.window.notebook.set_current_page.assert_called_once_with(0)
        self.window.active_host = object()
        self.page._show_service_logs()
        self.assertEqual(self.window.pages['logs'].navigate.call_count, 1)

    def test_virtual_toggle_filters_loaded_snapshot_without_new_queries(self):
        self.page._done(self.result, None)
        self.assertNotIn('Mount · /proc', [row[0] for row in self.page.store])
        self.page.show_virtual.set_active(True)
        self.assertIn('Mount · /proc', [row[0] for row in self.page.store])
        self.app.run_async.assert_not_called()
        self.assertIn('/home space', self.page._text)

    def test_partial_unavailability_is_visible_and_full_failure_retains_snapshot(self):
        result = dict(self.result, failed_services=dict(items=[], error='access denied', limited=False))
        self.page._done(result, None)
        self.assertIn('Unavailable: access denied', self.page._text)
        self.assertNotIn('No failed system services', self.page._text)
        previous = self.page._text
        self.page._done(None, RuntimeError('SSH lost'))
        self.assertEqual(self.page._text, previous)
        self.assertIn('previous snapshot 12:00:00 retained', self.page.status.get_text())

    def test_network_usage_opt_in_applies_on_refresh_and_late_result_is_ignored(self):
        self.page.include_remote.set_active(True)
        self.app.run_async.assert_not_called()
        with patch('syslogapp.pages.overview.snapshot', return_value=self.result) as collect:
            self.page._refresh_clicked()
            work, done = self.app.run_async.call_args.args
            work()
        collect.assert_called_once_with(include_remote=True)
        self.page.destroy()
        done(self.result, None)

    def test_compact_summary_and_closed_details_keep_full_snapshot_available(self):
        result = dict(self.result, rows=self.result['rows'] + [
            ('Host', 'fixture-host', '#6aa8ff'), ('Uptime', '2d 3h', '#c6d4c9'),
            ('CPU', 'Fixture CPU', '#c6d4c9'), ('Memory', '4 GiB used / 16 GiB total · 12 GiB available', '#b69cff'),
            ('Root filesystem', 'Detailed root statistics', '#6aa8ff'),
            ('Kernel', 'fixture-kernel', '#c6d4c9'), ('Swap', '0 B used', '#b69cff')])
        self.page._done(result, None)
        self.assertFalse(self.page.details.get_expanded())
        text = self.page.summary.get_buffer().props.text
        self.assertIn('fixture-host', text)
        self.assertIn('4 GiB used / 16 GiB total', text)
        self.assertNotIn('12 GiB available', text)
        self.assertNotIn('fixture-kernel', text)
        self.assertNotIn('Mount ·', text)
        self.assertIn('fixture-kernel', self.page._text)
        self.assertIn('Service · demo.service', self.page._text)
        self.assertIn('1 failed service', self.page.health.get_text())
        self.page.details.set_expanded(True)
        self.app.run_async.assert_not_called()

    def test_reboot_and_unavailable_checks_remain_visible_with_details_closed(self):
        result = dict(self.result, reboot=dict(state='required'),
                      failed_services=dict(items=[], error='denied', limited=False))
        self.page._done(result, None)
        self.assertFalse(self.page.details.get_expanded())
        self.assertIn('Service check unavailable', self.page.health.get_text())
        self.assertIn('Reboot requested', self.page.health.get_text())
        self.assertNotIn('No failed services', self.page.health.get_text())

    def test_summary_wraps_inside_a_narrow_page(self):
        from gi.repository import GLib
        frame = Gtk.OffscreenWindow()
        frame.set_size_request(480, 600)
        frame.add(self.page)
        frame.show_all()
        result = dict(self.result, rows=self.result['rows'] + [
            ('CPU', 'Example processor model with a long descriptive name and twelve cores', '#c6d4c9')])
        self.page._done(result, None)
        loop = GLib.MainLoop()
        GLib.timeout_add(300, lambda: (loop.quit(), False)[1])
        loop.run()
        try:
            x, _y = self.page.summary.translate_coordinates(self.page, 0, 0)
            self.assertLessEqual(x + self.page.summary.get_allocated_width(), self.page.get_allocated_width())
            buffer = self.page.summary.get_buffer()
            start = buffer.get_iter_at_line(3)
            end = start.copy()
            end.forward_to_line_end()
            self.assertGreater(self.page.summary.get_iter_location(end).y,
                               self.page.summary.get_iter_location(start).y)
            self.assertFalse(self.page.details.get_expanded())
        finally:
            frame.destroy()

    def test_memory_summary_is_host_available_ram_and_swap_is_not_an_activity_alert(self):
        memory = o.memory_snapshot('MemTotal: 4194304 kB\nMemAvailable: 3145728 kB\n'
                                   'SwapTotal: 2097152 kB\nSwapFree: 0 kB\n')
        result = dict(self.result, memory=memory,
                      failed_services=dict(items=[], error=None, limited=False),
                      reboot=dict(state='not_reported'))
        self.page._done(result, None)
        self.assertIn('3.0 GiB available / 4.0 GiB total', self.page.summary.get_buffer().props.text)
        self.assertFalse(self.page.details.get_expanded())
        self.assertIn('Memory scope: selected host, not SysLogApp', self.page._text)
        self.assertIn('Swap occupied is not a current activity rate', self.page._text)
        self.assertNotIn('swap', self.page.health.get_text().lower())
