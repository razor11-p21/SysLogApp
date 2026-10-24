# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from syslogapp import network as n


class NetworkCollectionTests(unittest.TestCase):
    def test_host_ip_prefers_lan_over_vpn_and_respects_remote_target(self):
        interfaces = [
            {'ifname': 'proton0', 'addr_info': [{'scope': 'global', 'local': '10.2.0.2'}]},
            {'ifname': 'eth0', 'link_type': 'ether', 'addr_info': [
                {'scope': 'link', 'local': 'fe80::1'}, {'scope': 'global', 'local': '192.168.99.44'}]},
            {'ifname': 'lo', 'addr_info': [{'scope': 'host', 'local': '127.0.0.1'}]}]
        self.assertEqual(n.host_lan_ip(interfaces), '192.168.99.44')
        self.assertEqual(n.host_lan_ip(interfaces, preferred='10.2.0.2'), '10.2.0.2')
        self.assertIsNone(n.host_lan_ip(None))

    def test_numeric_endpoints_and_process_output(self):
        text = 'tcp ESTAB 0 0 [::1]:22 [::1]:3456 users:(("ssh",pid=12,fd=3))\n'
        rows, limited = n.socket_rows(text)
        self.assertFalse(limited)
        self.assertEqual(rows[0]['peer'], '[::1]:3456')
        self.assertIn('pid=12', rows[0]['process'])

    def test_socket_rows_are_bounded(self):
        rows, limited = n.socket_rows('udp UNCONN 0 0 0.0.0.0:68 0.0.0.0:*\n' * 1001)
        self.assertEqual(len(rows), n.MAX_SOCKETS)
        self.assertTrue(limited)

    def test_snapshot_collects_partially_when_one_source_fails(self):
        def capture(args):
            if args[0] == 'ss':
                raise PermissionError('Not permitted')
            return json.dumps([{'ifname': 'eth0'}] if 'address' in args else []), False
        with patch.object(n, 'capture', side_effect=capture):
            result = n.snapshot()
        self.assertEqual(result['interfaces'][0]['ifname'], 'eth0')
        self.assertIsNone(result['sockets'])
        self.assertIn('Sockets: Not permitted', result['errors'])

    def test_process_scan_is_opt_in_and_dns_is_disabled(self):
        for processes in (False, True):
            with patch.object(n, 'capture', side_effect=lambda args: ('', False) if args[0] == 'ss' else ('[]', False)) as capture:
                n.snapshot(processes)
            args = capture.call_args_list[-1].args[0]
            self.assertIn('-n', args)
            self.assertEqual('-p' in args, processes)
            self.assertEqual(capture.call_count, 4)

    def test_capture_limits_memory_and_stops_child(self):
        output, limited = n.capture([sys.executable, '-c', 'print("socket row\\n" * 10000)'], max_bytes=1024)
        self.assertTrue(limited)
        self.assertLessEqual(len(output.encode()), 1024)
        self.assertTrue(output.endswith('row'))

    def test_capture_times_out_and_reports_failures(self):
        with self.assertRaises(TimeoutError):
            n.capture([sys.executable, '-c', 'import time; time.sleep(3)'], timeout=.05)
        with self.assertRaisesRegex(RuntimeError, 'failure'):
            n.capture([sys.executable, '-c', 'import sys; sys.stderr.write("failure"); sys.exit(1)'])


try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib, Gdk
    from syslogapp.pages.network import NetworkPage
    DISPLAY = Gtk.init_check()[0]
except ImportError:
    DISPLAY = False


@unittest.skipUnless(DISPLAY, 'No GTK display')
class NetworkUITests(unittest.TestCase):
    def setUp(self):
        self.app = SimpleNamespace(run_async=Mock(), window=SimpleNamespace(toast=Mock()))
        self.page = NetworkPage(self.app)
        self.page.live.set_active(False)
        self.page.kind.set_active(0)
        self.page.process_details.set_active_id('off')
        self.result = {'interfaces': [], 'routes': [], 'errors': [], 'time': '12:00:00',
                       'limited': False, 'processes': False, 'sockets': [
                           {'protocol': 'TCP', 'state': 'ESTAB', 'local': '127.0.0.1:22',
                            'peer': '127.0.0.1:3456', 'process': '', 'recv': '0', 'send': '0'},
                           {'protocol': 'UDP', 'state': 'UNCONN', 'local': '0.0.0.0:68',
                            'peer': '0.0.0.0:*', 'process': '', 'recv': '0', 'send': '0'}]}

    def tearDown(self):
        self.page.destroy()

    def test_reopening_does_not_refresh_and_overlapping_reads_are_coalesced(self):
        self.page._on_map()
        self.page._on_map()
        self.page.refresh()
        self.assertEqual(self.app.run_async.call_count, 1)
        self.page._loaded(self.result, None)
        self.page._on_map()
        self.assertEqual(self.app.run_async.call_count, 1)

    def test_filters_are_local_and_preserve_numeric_addresses(self):
        self.page._loaded(self.result, None)
        self.page.kind.set_active(1)
        self.assertEqual(len(self.page.store), 1)
        self.assertEqual(tuple(self.page.store[0])[4:6], ('127.0.0.1', '3456'))
        self.page.search.set_text('missing')
        self.page._filter()
        self.assertEqual(len(self.page.store), 0)
        self.app.run_async.assert_not_called()

    def test_failure_keeps_previous_snapshot_and_late_callback_is_ignored(self):
        self.page._loaded(self.result, None)
        self.page._loaded(None, RuntimeError('failed'))
        self.assertEqual(len(self.page.store), 2)
        self.assertIn('Previous snapshot retained', self.page.status.get_text())
        self.page.destroy()
        self.page._loaded(self.result, None)

    def test_wrapped_endpoints_reflow_when_resizing_and_timer_stops(self):
        self.result['sockets'][0]['peer'] = '[2001:db8:1234:1234:1234:1234:1234:1234]:12345'
        self.result['sockets'][0]['local'] = '[2001:db8:5678:5678:5678:5678:5678:5678]:54321'
        self.page._loaded(self.result, None)
        window = Gtk.OffscreenWindow()
        window.set_size_request(1100, 650)
        window.add(self.page)
        window.show_all()
        def settle():
            loop = GLib.MainLoop()
            GLib.timeout_add(180, lambda: (loop.quit(), False)[1])
            loop.run()
        settle()
        path = Gtk.TreePath.new_from_indices([0])
        wide = self.page.tree.get_background_area(path, None).height
        window.set_size_request(640, 650)
        window.resize(640, 650)
        settle()
        narrow = self.page.tree.get_background_area(path, None).height
        self.assertGreater(narrow, wide)
        self.assertEqual(self.page._reflow_source, 0)
        window.destroy()

    def test_selected_socket_survives_refresh_and_copy_uses_sorted_model(self):
        self.page._loaded(self.result, None)
        self.page.tree.get_selection().select_path(0)
        selected = self.page._selected_key()
        self.page.store.set_sort_column_id(0, Gtk.SortType.DESCENDING)
        self.page._loaded(self.result, None)
        self.assertEqual(self.page._selected_key(), selected)


    def test_paused_page_schedules_live_only_after_completion(self):
        self.assertFalse(self.page.live.get_active())
        self.assertEqual(self.page._live_source, 0)
        with patch.object(self.page, 'get_mapped', return_value=True):
            self.page.live.set_active(True)
            self.assertEqual(self.app.run_async.call_count, 1)
            self.assertEqual(self.page._live_source, 0)
            self.page.refresh(automatic=True)
            self.assertEqual(self.app.run_async.call_count, 1)
            callback = self.app.run_async.call_args.args[1]
            callback(self.result, None)
            self.assertNotEqual(self.page._live_source, 0)
            self.page.live.set_active(False)
            self.assertEqual(self.page._live_source, 0)

    def test_pause_discards_inflight_update_and_resume_starts_fresh(self):
        self.page._loaded(self.result, None)
        with patch.object(self.page, 'get_mapped', return_value=True):
            self.page.live.set_active(True)
            old_callback = self.app.run_async.call_args.args[1]
            self.page.live.set_active(False)
            changed = dict(self.result, sockets=[], time='12:00:02')
            old_callback(changed, None)
            self.assertEqual(len(self.page.store), 2)
            self.assertEqual(self.page._live_source, 0)
            self.assertIn('paused', self.page.status.get_text())
            self.page.live.set_active(True)
            self.assertEqual(self.app.run_async.call_count, 2)
            self.app.run_async.call_args.args[1](changed, None)
            self.assertEqual(len(self.page.store), 0)
            self.assertNotEqual(self.page._live_source, 0)

    def test_hidden_tab_stops_polling_and_refreshes_when_reopened(self):
        with patch.object(self.page, 'get_mapped', return_value=True):
            self.page.live.set_active(True)
            self.app.run_async.call_args.args[1](self.result, None)
            self.assertNotEqual(self.page._live_source, 0)
            self.page._on_unmap()
            self.assertEqual(self.page._live_source, 0)
        with patch.object(self.page, 'get_mapped', return_value=False):
            self.page._live_tick()
            self.assertEqual(self.app.run_async.call_count, 1)
        with patch.object(self.page, 'get_mapped', return_value=True):
            self.page._on_map()
            self.assertEqual(self.app.run_async.call_count, 2)

    def test_manual_refresh_works_while_paused_without_resuming(self):
        with patch.object(self.page, 'get_mapped', return_value=True):
            self.page.live.set_active(True)
            self.app.run_async.call_args.args[1](self.result, None)
            self.page.live.set_active(False)
            self.page._refresh_clicked()
            self.app.run_async.call_args.args[1](dict(self.result, sockets=[]), None)
            self.assertEqual(len(self.page.store), 0)
            self.assertFalse(self.page.live.get_active())
            self.assertEqual(self.page._live_source, 0)

    def test_collection_failure_backs_off_and_destroy_removes_timer(self):
        with patch.object(self.page, 'get_mapped', return_value=True):
            self.page.live.set_active(True)
            with patch('syslogapp.pages.network.GLib.timeout_add_seconds', wraps=GLib.timeout_add_seconds) as timer:
                self.app.run_async.call_args.args[1](None, RuntimeError('permission denied'))
                self.assertEqual(timer.call_args.args[0], 4)
            self.assertNotEqual(self.page._live_source, 0)
            self.page.destroy()
            self.assertEqual(self.page._live_source, 0)

    def test_state_colors_are_applied_to_cells(self):
        self.page._loaded(self.result, None)
        itr = self.page.store.get_iter_first()
        for state, color in [('ESTAB', '#6aa8ff'), ('LISTEN', '#b69cff'),
                             ('SYN-SENT', '#b69cff'), ('UNCONN', '#9aa8b7')]:
            self.page.store.set_value(itr, 1, state)
            col = self.page.columns[1]
            col.cell_set_cell_data(self.page.store, itr, False, False)
            actual = self.page.renderers[1].get_property('foreground-rgba')
            expected = Gdk.RGBA()
            expected.parse(color)
            self.assertTrue(actual.equal(expected))

    def test_interface_markup_escapes_host_data_and_unknown_is_neutral(self):
        result = dict(self.result, interfaces=[{'ifname': 'vpn<&>', 'operstate': 'UNKNOWN',
                                               'flags': ['UP'], 'addr_info': []}])
        self.page._loaded(result, None)
        self.assertIn('vpn<&>', self.page.overview.get_text())
        self.assertIn('&lt;&amp;&gt;', self.page.overview.get_label())
        self.assertEqual(self.page._interface_color(result['interfaces'][0]), '#9aa8b7')


    def test_unchanged_snapshot_does_not_rebuild_the_table(self):
        self.page._loaded(self.result, None)
        self.page.tree.get_selection().select_path(0)
        with patch.object(self.page.store, 'clear', wraps=self.page.store.clear) as clear:
            self.page._loaded(dict(self.result, sockets=list(reversed(self.result['sockets']))), None)
            clear.assert_not_called()
        self.assertIsNotNone(self.page._selected_key())


    def test_numeric_address_sort_survives_live_snapshot_replacement(self):
        rows = [dict(self.result['sockets'][0], local=f'192.168.1.{octet}:{port}')
                for octet, port in [(10, 9), (2, 443), (2, 80)]]
        self.page._loaded(dict(self.result, sockets=rows), None)
        self.page.store.set_sort_column_id(2, Gtk.SortType.ASCENDING)
        self.assertEqual([(row[2],row[3]) for row in self.page.store],
                         [('192.168.1.2','80'),('192.168.1.2','443'),('192.168.1.10','9')])
        self.page._loaded(dict(self.result, sockets=[*rows, dict(rows[0], local='192.168.1.1:9')]), None)
        self.assertEqual(self.page.store.get_sort_column_id(), (2, Gtk.SortType.ASCENDING))
        self.assertEqual(self.page.store[0][2], '192.168.1.1')


    def test_processes_control_keeps_collect_on_refresh_behavior(self):
        self.page.process_details.set_active_id('basic')
        self.app.run_async.assert_not_called()
        with patch('syslogapp.pages.network.snapshot', return_value=dict(self.result, processes=True)) as snapshot:
            self.page._refresh_clicked()
            work, callback = self.app.run_async.call_args.args
            callback(work(), None)
            snapshot.assert_called_once_with(True)
        self.assertEqual(len(self.page.columns), 8)

    def test_ports_processes_and_pids_have_separate_colors_and_columns(self):
        row = dict(self.result['sockets'][0], process='users:(("ssh",pid=1234,fd=3))')
        self.page.process_details.set_active_id('basic')
        self.page._loaded(dict(self.result, processes=True, sockets=[row]), None)
        self.assertEqual([column.get_title() for column in self.page.columns],
                         ['Proto','State','Local address','Local port','Remote address','Remote port','PID','Process'])
        self.assertEqual(tuple(self.page.store[0])[:8],
                         ('TCP','ESTAB','127.0.0.1','22','127.0.0.1','3456','1234','ssh'))
        itr = self.page.store.get_iter_first()
        for index,color in ((2,'#c6d4c9'),(3,'#ffb34c'),(5,'#ffb34c'),(6,'#6aa8ff'),(7,'#b69cff')):
            self.page.columns[index].cell_set_cell_data(self.page.store, itr, False, False)
            expected = Gdk.RGBA(); expected.parse(color)
            self.assertTrue(self.page.renderers[index].get_property('foreground-rgba').equal(expected))

    def test_all_columns_fit_at_laptop_width_with_processes_enabled(self):
        self.page.process_details.set_active_id('basic')
        self.page._loaded(dict(self.result, processes=True), None)
        window = Gtk.OffscreenWindow()
        window.set_size_request(1100,650)
        window.add(self.page);window.show_all()
        for width in (1100,640,1100):
            window.set_size_request(width,650);window.resize(width,650)
            loop = GLib.MainLoop()
            GLib.timeout_add(180,lambda:(loop.quit(),False)[1]);loop.run()
            visible = [column for column in self.page.columns if column.get_visible()]
            self.assertEqual(len(visible),8)
            self.assertLessEqual(sum(column.get_width() for column in visible),self.page.socket_scroll.get_allocated_width())
            adjustment = self.page.socket_scroll.get_hadjustment()
            self.assertLessEqual(adjustment.get_upper(),adjustment.get_page_size()+1)
        window.destroy()


    def test_extended_processes_switches_loaded_details_without_collection(self):
        raw = 'users:(("ssh",pid=1234,fd=3))'
        row = dict(self.result['sockets'][0],process=raw)
        self.page.process_details.set_active_id('basic')
        self.page._loaded(dict(self.result,processes=True,sockets=[row]),None)
        self.assertTrue(self.page.process_details.get_sensitive())
        self.assertEqual(self.page.process_details.get_active_id(), 'basic')
        self.page.store.set_sort_column_id(7,Gtk.SortType.ASCENDING)
        self.page.tree.get_selection().select_path(0)
        self.page.process_details.set_active_id('extended')
        self.assertEqual(self.page.store[0][6], '1234')
        self.assertEqual(self.page.store[0][7], raw)
        self.assertIsNotNone(self.page._selected_key())
        self.assertEqual(self.page.store.get_sort_column_id(),(7,Gtk.SortType.ASCENDING))
        self.page.process_details.set_active_id('basic')
        self.assertEqual(self.page.store[0][7], 'ssh')
        self.app.run_async.assert_not_called()
        self.page._loaded(self.result,None)
        self.assertFalse(self.page.columns[7].get_visible())

    def test_pid_column_sorts_numerically_and_extended_preserves_order(self):
        rows = [dict(self.result['sockets'][0],process=f'users:(("worker",pid={pid},fd=3))') for pid in (12,2,100)]
        self.page.process_details.set_active_id('basic')
        self.page._loaded(dict(self.result,processes=True,sockets=rows),None)
        self.page.store.set_sort_column_id(6,Gtk.SortType.ASCENDING)
        self.assertEqual([row[6] for row in self.page.store],['2','12','100'])
        self.page.process_details.set_active_id('extended')
        self.assertEqual([row[6] for row in self.page.store],['2','12','100'])

    def test_hide_time_wait_is_local_reversible_and_preserves_sort_selection(self):
        rows = self.result['sockets'] + [dict(self.result['sockets'][0], state=state)
                                       for state in ('TIME-WAIT', 'CLOSE-WAIT')]
        self.page._loaded(dict(self.result, sockets=rows), None)
        self.assertFalse(self.page.hide_time_wait.get_active())
        self.assertEqual(len(self.page.store), 4)
        self.page.store.set_sort_column_id(1, Gtk.SortType.ASCENDING)
        self.page.tree.get_selection().select_path(0)
        selected = self.page._selected_key()
        self.page.hide_time_wait.set_active(True)
        self.assertEqual(len(self.page.store), 3)
        self.assertNotIn('TIME-WAIT', [row[1] for row in self.page.store])
        self.assertIn('CLOSE-WAIT', [row[1] for row in self.page.store])
        self.assertEqual(self.page._selected_key(), selected)
        self.assertEqual(self.page.store.get_sort_column_id(), (1, Gtk.SortType.ASCENDING))
        self.assertIn('3 shown / 4 loaded', self.page.status.get_text())
        self.page.hide_time_wait.set_active(False)
        self.assertEqual(len(self.page.store), 4)
        self.app.run_async.assert_not_called()

    def test_hide_time_wait_combines_with_filters_and_survives_new_snapshots(self):
        rows = self.result['sockets'] + [dict(self.result['sockets'][0], state='TIME-WAIT')]
        self.page.hide_time_wait.set_active(True)
        self.page._loaded(dict(self.result, sockets=rows), None)
        self.page.kind.set_active(1)
        self.assertEqual([row[1] for row in self.page.store], ['ESTAB'])
        self.page.search.set_text('missing')
        self.page._filter()
        self.assertEqual(len(self.page.store), 0)
        self.page.search.set_text('')
        self.page._loaded(dict(self.result, sockets=rows), None)
        self.assertEqual([row[1] for row in self.page.store], ['ESTAB'])
        self.page.kind.set_active(2)
        self.assertEqual([row[1] for row in self.page.store], ['UNCONN'])
        self.app.run_async.assert_not_called()

    def test_first_snapshot_compacts_local_address_and_handles_process_columns(self):
        window = Gtk.OffscreenWindow()
        window.set_size_request(1100,650)
        window.add(self.page)
        window.show_all()
        def settle():
            loop = GLib.MainLoop()
            GLib.timeout_add(180, lambda:(loop.quit(),False)[1])
            loop.run()
        settle()
        self.assertFalse(self.page.columns[6].get_visible())
        self.assertFalse(self.page.columns[7].get_visible())
        # Match real startup: the first result arrives after the table is mapped.
        self.page._loaded(self.result, None)
        settle()
        self.assertLess(self.page.columns[2].get_width(),150)
        self.assertEqual(self.page.columns[2].get_width(),self.page.columns[4].get_width())
        self.assertEqual(self.page.column_sizing.manual,{})
        self.page.columns[2].set_fixed_width(190)
        self.page.process_details.set_active_id('basic')
        self.page._loaded(dict(self.result,processes=True),None)
        settle()
        self.assertTrue(self.page.columns[6].get_visible())
        self.assertEqual(self.page.columns[2].get_fixed_width(),190)
        self.page._fit_columns()
        settle()
        self.assertLess(self.page.columns[2].get_width(),150)
        self.page._loaded(self.result,None)
        settle()
        self.assertFalse(self.page.columns[6].get_visible())
        self.assertLess(self.page.columns[2].get_width(),150)
        window.destroy()

    def test_visual_order_groups_owners_and_endpoints_with_matching_copy_order(self):
        row = dict(self.result['sockets'][0], process='users:(("ssh",pid=1234,fd=3))')
        self.page.process_details.set_active_id('basic')
        self.page._loaded(dict(self.result,processes=True,sockets=[row]), None)
        visible = [column.get_title() for column in self.page.tree.get_columns()
                   if column.get_visible() and column.get_title()]
        self.assertEqual(visible,['Proto','State','Local address','Local port','Remote address','Remote port',
                                  'Process','PID'])
        self.page.columns[7].clicked()
        self.assertEqual(self.page.store.get_sort_column_id()[0],7)
        self.page.tree.get_selection().select_path(0)
        self.page._copy()
        text = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
        self.assertTrue(text.startswith('TCP\tESTAB\t127.0.0.1\t22\t127.0.0.1\t3456\tssh\t1234'))

    def test_both_address_port_pairs_stay_compact_at_wide_window(self):
        self.page._loaded(self.result,None)
        window=Gtk.OffscreenWindow()
        window.set_size_request(1400,650)
        window.add(self.page)
        window.show_all()
        loop=GLib.MainLoop()
        GLib.timeout_add(180,lambda:(loop.quit(),False)[1])
        loop.run()
        self.assertEqual(self.page.columns[2].get_width(),self.page.columns[4].get_width())
        self.assertLess(self.page.columns[4].get_width(),150)
        self.assertEqual(self.page.columns[3].get_width(),self.page.columns[5].get_width())
        self.assertLessEqual(self.page.columns[5].get_width(),80)
        self.assertGreater(self.page.end_space.get_width(),200)
        window.destroy()


    def test_sparse_updates_keep_unchanged_native_rows_and_selection(self):
        self.page._loaded(self.result,None)
        path=next(row.path for row in self.page.store if row[0]=='UDP')
        reference=Gtk.TreeRowReference.new(self.page.store,path)
        self.page.tree.get_selection().select_path(path)
        counts={'inserted':0,'deleted':0}
        def count(_model,*args,kind):
            counts[kind]+=1
        self.page.store.connect('row-inserted',lambda *args:count(*args,kind='inserted'))
        self.page.store.connect('row-deleted',lambda *args:count(*args,kind='deleted'))
        changed=[dict(self.result['sockets'][0],peer='192.0.2.1:443'),self.result['sockets'][1]]
        self.page._loaded(dict(self.result,sockets=changed),None)
        self.assertEqual(counts,{'inserted':1,'deleted':1})
        self.assertTrue(reference.valid())
        self.assertEqual(self.page._selected_key()[0],'UDP')
        self.page._loaded(dict(self.result,sockets=list(reversed(changed))),None)
        self.assertEqual(counts,{'inserted':1,'deleted':1})

    def test_incremental_updates_preserve_duplicate_socket_counts(self):
        duplicate=self.result['sockets'][0]
        self.page._loaded(dict(self.result,sockets=[duplicate,duplicate]),None)
        self.assertEqual(len(self.page.store),2)
        self.page._loaded(dict(self.result,sockets=[duplicate]),None)
        self.assertEqual(len(self.page.store),1)
        self.page._loaded(dict(self.result,sockets=[duplicate,duplicate,self.result['sockets'][1]]),None)
        self.assertEqual(len(self.page.store),3)
        self.page.kind.set_active(1)
        self.assertEqual(len(self.page.store),2)

    def test_lazy_network_comparator_matches_full_keys_in_all_sort_orders(self):
        from syslogapp.sorting import network_sort_key
        rows=[]
        for i in range(18):
            rows.append(dict(protocol='UDP' if i%3 else 'TCP',state=('ESTAB','LISTEN','UNCONN')[i%3],
                local=f'10.0.0.{i%4}:{i%5}',peer=f'[2001:db8::{i%3}]:{80+i%2}',
                process=f'users:(("worker-{i%2}",pid={i%4+1},fd={i}))'))
        self.page.process_details.set_active_id('basic')
        self.page._loaded(dict(self.result,processes=True,sockets=rows),None)
        self.page.process_details.set_active_id('extended')
        original=[tuple(row) for row in self.page.store]
        for column in range(8):
            for order in (Gtk.SortType.ASCENDING,Gtk.SortType.DESCENDING):
                self.page.store.set_sort_column_id(column,order)
                actual=[network_sort_key(tuple(row),column) for row in self.page.store]
                expected=sorted((network_sort_key(row,column) for row in original),
                                reverse=order==Gtk.SortType.DESCENDING)
                self.assertEqual(actual,expected)

    def test_actual_defaults_start_live_only_when_mapped_with_connections_and_basic(self):
        app = SimpleNamespace(run_async=Mock(), window=SimpleNamespace(toast=Mock()))
        page = NetworkPage(app)
        try:
            self.assertTrue(page.live.get_active())
            self.assertEqual(page.kind.get_active(), 1)
            self.assertEqual(page.process_details.get_active_id(), 'basic')
            app.run_async.assert_not_called()
            with patch.object(page, 'get_mapped', return_value=True), \
                 patch('syslogapp.pages.network.snapshot', return_value=dict(self.result, processes=True)) as collect:
                page._on_map()
                work, done = app.run_async.call_args.args
                done(work(), None)
                collect.assert_called_once_with(True)
                self.assertEqual(len(page.store), 1)
                self.assertEqual(page.store[0][1], 'ESTAB')
                self.assertTrue(page.columns[7].get_visible())
                self.assertTrue(page._live_source)
                page._on_unmap()
                self.assertEqual(page._live_source, 0)
        finally:
            page.destroy()

    def test_automatic_refresh_keeps_control_and_visibility_properties_unchanged(self):
        self.page.process_details.set_active_id('basic')
        result = dict(self.result, processes=True)
        self.page._loaded(result, None)
        self.page.live.set_active(True)  # unmapped: does not collect
        events = []
        self.page.refresh_btn.connect('notify::sensitive', lambda *_: events.append('button'))
        for column in self.page.columns[6:8]:
            column.connect('notify::visible', lambda *_: events.append('column'))
        with patch.object(self.page, 'get_mapped', return_value=True):
            self.page.refresh(automatic=True)
            self.app.run_async.call_args.args[1](dict(result, time='12:00:02'), None)
        self.assertEqual(events, [])

    def test_replacing_all_sockets_does_not_temporarily_empty_table(self):
        self.page._loaded(self.result, None)
        sizes = []
        for signal in ('row-inserted', 'row-deleted'):
            self.page.store.connect(signal, lambda *_: sizes.append(len(self.page.store)))
        rows = [dict(row, peer='192.0.2.100:443') for row in self.result['sockets']]
        self.page._loaded(dict(self.result, sockets=rows), None)
        self.assertTrue(sizes)
        self.assertGreater(min(sizes), 0)
        self.assertEqual(len(self.page.store), len(rows))

    def test_refresh_keeps_column_widths_stable_until_fit_or_resize(self):
        self.page._loaded(self.result, None)
        window = Gtk.OffscreenWindow()
        window.set_default_size(1100, 650)
        window.add(self.page)
        window.show_all()
        def settle():
            loop = GLib.MainLoop()
            GLib.timeout_add(180, lambda: (loop.quit(), False)[1])
            loop.run()
        try:
            settle()
            widths = [column.get_width() for column in self.page.columns]
            changed = [dict(row, peer='2001:db8:1234:5678:90ab:cdef:ffff:abcd:443') for row in self.result['sockets']]
            self.page._loaded(dict(self.result, sockets=changed), None)
            settle()
            self.assertEqual([column.get_width() for column in self.page.columns], widths)
            self.assertEqual(self.page._reflow_source, 0)
            self.page._fit_columns()
            settle()
            self.assertNotEqual([column.get_width() for column in self.page.columns], widths)
        finally:
            window.destroy()
