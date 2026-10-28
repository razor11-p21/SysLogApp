# SPDX-License-Identifier: GPL-3.0-or-later
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from syslogapp.network_filters import ConnectionFilter
from syslogapp.investigations import view_settings


def socket_row(name='browser', pid=12, local=12345, peer=443):
    return dict(protocol='TCP', state='ESTAB', local=f'127.0.0.1:{local}',
                peer=f'[2001:db8::1]:{peer}', process=f'users:(("{name}",pid={pid},fd=3))', recv='0', send='0')


class ConnectionFilterTests(unittest.TestCase):
    def test_pid_and_port_are_exact_and_application_is_literal_case_insensitive(self):
        row = socket_row()
        self.assertTrue(ConnectionFilter(application='BROW', pid='12', port='443').matches(row))
        self.assertFalse(ConnectionFilter(pid='1').matches(row))
        self.assertFalse(ConnectionFilter(port='44').matches(row))
        self.assertFalse(ConnectionFilter(application='bro.*').matches(row))
        self.assertTrue(ConnectionFilter(pid='0012', port='00443').matches(row))

    def test_endpoint_side_and_ipv6_and_wildcard_ports(self):
        row = socket_row()
        self.assertTrue(ConnectionFilter(port='443', side='remote').matches(row))
        self.assertFalse(ConnectionFilter(port='443', side='local').matches(row))
        self.assertTrue(ConnectionFilter(port='12345', side='local').matches(row))
        row['peer'] = '[::]:*'
        self.assertFalse(ConnectionFilter(port='0', side='remote').matches(row))
        self.assertTrue(ConnectionFilter().matches(row))

    def test_shared_socket_application_and_pid_must_match_same_owner(self):
        row = socket_row()
        row['process'] = 'users:(("browser",pid=12,fd=3),("helper",pid=123,fd=4))'
        self.assertTrue(ConnectionFilter(application='helper', pid='123').matches(row))
        self.assertFalse(ConnectionFilter(application='browser', pid='123').matches(row))
        row['process'] = 'users:(("new",pid=99,fd=3))'
        self.assertFalse(ConnectionFilter(application='helper', pid='123').matches(row))
        self.assertTrue(ConnectionFilter(application='new', pid='99').matches(row))

    def test_invalid_numbers_are_not_silently_ignored(self):
        for kwargs in ({'pid':'0'}, {'pid':'12x'}, {'pid':'2147483648'}, {'port':'65536'}, {'port':'-1'}, {'port':'1;id'}):
            filters = ConnectionFilter(**kwargs)
            self.assertTrue(filters.error)
            self.assertFalse(filters.matches(socket_row()))
        self.assertFalse(ConnectionFilter(port='65535').error)

    def test_missing_owner_matches_port_but_not_process_filters(self):
        row = dict(socket_row(), process='')
        self.assertTrue(ConnectionFilter(port='443').matches(row))
        self.assertFalse(ConnectionFilter(application='browser').matches(row))
        self.assertFalse(ConnectionFilter(pid='12').matches(row))

    def test_old_views_default_to_empty_filters_and_new_values_are_bounded(self):
        values = view_settings({'page':'network'})
        self.assertEqual((values['application'], values['pid'], values['port'], values['port_side']), ('','','','either'))
        values = view_settings(dict(page='network', application='x'*1000, pid='1'*1000, port='2'*1000, port_side='invalid'))
        self.assertEqual((len(values['application']),len(values['pid']),len(values['port'])),(128,10,5))
        self.assertEqual(values['port_side'],'either')


try:
    import gi
    gi.require_version('Gtk','3.0')
    from gi.repository import Gtk
    from syslogapp.pages.network import NetworkPage
    DISPLAY = Gtk.init_check()[0]
except ImportError:
    DISPLAY = False


@unittest.skipUnless(DISPLAY, 'GTK desktop required')
class ConnectionFilterUITests(unittest.TestCase):
    def setUp(self):
        self.app = SimpleNamespace(config={},run_async=Mock(),window=SimpleNamespace(toast=Mock()))
        self.page = NetworkPage(self.app)
        self.page.live.set_active(False)
        self.page.kind.set_active(0)
        rows = [socket_row(),socket_row('helper',123,2222,8443),socket_row('other',99,443,123)]
        self.page._loaded(dict(interfaces=[],routes=[],errors=[],time='now',limited=False,processes=True,sockets=rows),None)
        self.addCleanup(self.page.destroy)

    def test_combined_filters_work_without_queries_and_clear_restores_rows(self):
        self.assertFalse(self.page.connection_filters.get_expanded())
        self.page.application_filter.set_text('brow')
        self.page.pid_filter.set_text('12')
        self.page.port_filter.set_text('443')
        self.page._filter()
        self.assertEqual(len(self.page.store),1)
        self.assertEqual(self.page.store[0][6],'12')
        self.assertIn('3 active',self.page.connection_filters.get_label())
        self.page.port_side.set_active_id('local')
        self.assertEqual(len(self.page.store),0)
        self.page._clear_connection_filters()
        self.assertEqual(len(self.page.store),3)
        self.app.run_async.assert_not_called()

    def test_bad_input_and_missing_owner_data_are_explained(self):
        self.page.pid_filter.set_text('bad')
        self.assertEqual(len(self.page.store),0)
        self.assertIn('whole number',self.page.filter_notice.get_text())
        self.page.pid_filter.set_text('12')
        self.page._socket_processes=False
        self.page._filter()
        self.assertIn('Basic or Extended',self.page.filter_notice.get_text())
        self.app.run_async.assert_not_called()

    def test_process_and_logs_buttons_use_existing_on_demand_inspection(self):
        self.assertFalse(self.page.inspect_btn.get_sensitive())
        self.page.tree.get_selection().select_path(0)
        self.assertTrue(self.page.inspect_btn.get_sensitive())
        self.assertTrue(self.page.logs_btn.get_sensitive())
        remote=SimpleNamespace(target='fixture@remote:22')
        self.page.host=remote
        dialog=Mock()
        with patch('syslogapp.process_ui.ProcessDialog', return_value=dialog) as factory:
            self.page.logs_btn.clicked()
        self.assertTrue(factory.call_args.kwargs['show_logs'])
        self.assertIs(factory.call_args.args[0],self.page)
        self.assertIs(factory.call_args.args[0].host,remote)
        dialog.start.assert_called_once()
        dialog.destroy.assert_called_once()
        self.app.run_async.assert_not_called()

    def test_saved_view_and_export_preserve_filter_context_without_queries(self):
        from syslogapp.investigations import host_identity
        from syslogapp.export_capture import snapshot
        item=dict(host=host_identity()[0], settings=dict(page='network',application='brow',pid='12',port='443',port_side='remote'))
        self.page._apply_saved_view(item)
        self.assertEqual(len(self.page.store),1)
        self.assertTrue(self.page.connection_filters.get_expanded())
        data=snapshot(self.page)
        filters=data['metadata']['filters']
        self.assertEqual((filters['application'],filters['pid'],filters['port'],filters['port_side']),('brow','12','443','remote'))
        self.assertEqual(len(data['records']),1)
        self.app.run_async.assert_not_called()

    def test_saved_filter_action_writes_current_criteria(self):
        self.page.application_filter.set_text('browser')
        self.page.pid_filter.set_text('12')
        self.page.port_filter.set_text('443')
        self.page.port_side.set_active_id('remote')
        with patch('syslogapp.saved_ui.ask_name', return_value='Web'), \
             patch('syslogapp.investigations.save_view') as save:
            self.page._save_view()
        fields = save.call_args.args[2]
        self.assertEqual((fields['application'],fields['pid'],fields['port'],fields['port_side']),
                         ('browser','12','443','remote'))
        self.app.run_async.assert_not_called()

    def test_port_filter_without_owners_keeps_inspection_disabled(self):
        self.page._rows=[dict(row,process='') for row in self.page._rows]
        self.page._socket_processes=False
        self.page.port_filter.set_text('443')
        self.assertEqual(len(self.page.store),2)
        self.page.tree.get_selection().select_path(0)
        self.assertFalse(self.page.inspect_btn.get_sensitive())
        self.assertFalse(self.page.logs_btn.get_sensitive())
        self.app.run_async.assert_not_called()
