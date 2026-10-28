#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib,Gio,Gdk
from syslogapp.app import MainWindow,SysLogApplication
from syslogapp.hosts import host_profile


class SidebarTests(unittest.TestCase):
    def test_switches_route_all_tabs_and_releases_old_pages(self):
        app=SysLogApplication()
        app.set_application_id('gr.syslogapp.sshUiTests.p'+str(os.getpid()))
        app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(app.register(None))
        app.config={'log_lines':100,'window':{},'columns':{},'hosts':[host_profile(dict(hostname='test-host',username='test-user'))]}
        app.run_async=Mock()
        window=MainWindow(app)
        app.window=window
        window.show_all()
        def settle():
            loop=GLib.MainLoop()
            GLib.timeout_add(100,lambda:(loop.quit(),False)[1])
            loop.run()
        remote=SimpleNamespace(target='test-user@test-host:22',label='Test host',close=Mock(),uid=1000,
                rotation_text='',which=lambda name:'/usr/bin/'+name,
                overview=lambda:{'rows':[['Host','REMOTE','#6aa8ff']],'time':'now'},
                resolve_action=Mock(return_value=(['remote-command'],'')))
        def capture(args,**kwargs):
            if args[0]=='ip':return '[]',False
            if args[0]=='ss':return 'tcp ESTAB 0 0 10.0.0.1:123 192.0.2.1:443\n',False
            if args[0]=='journalctl':return '{"MESSAGE":"REMOTE","PRIORITY":"6"}',False,''
            raise AssertionError(args)
        remote.capture=Mock(side_effect=capture)
        try:
            old=window.pages['logs']
            window._use_host(remote,0)
            settle()
            self.assertTrue(old._destroyed)
            self.assertIs(window.active_host,remote)
            self.assertIn(remote.target,window.host_label.get_text())
            self.assertEqual(window.notebook.get_n_pages(),5)
            work,done=app.run_async.call_args.args
            done(work(),None)
            self.assertEqual(window.pages['logs'].store[0][3],'REMOTE')
            window.notebook.set_current_page(1)
            settle()
            work,done=app.run_async.call_args.args
            done(work(),None)
            network=window.pages['network']
            self.assertIs(network.host,remote)
            self.assertEqual(network.store[0][2],'10.0.0.1')
            network.columns[2].set_fixed_width(190)
            window.notebook.set_current_page(2)
            settle()
            work,done=app.run_async.call_args.args
            done(work(),None)
            self.assertIn('REMOTE',window.pages['overview']._text)
            window.notebook.set_current_page(3)
            settle()
            maintenance=window.pages['maintenance']
            self.assertIs(maintenance.host,remote)
            self.assertIs(maintenance._resolve.__self__,maintenance)
            previous_context=window._host_context
            maintenance._busy=True
            self.assertTrue(window._delete_event())
            self.assertTrue(window._maintenance_busy())
            maintenance._busy=False
            calls = app.run_async.call_count
            def shortcut(value):
                key, modifiers = Gtk.accelerator_parse(value)
                self.assertTrue(Gtk.accel_groups_activate(window, key, modifiers))
                settle()
            shortcut('F1')
            self.assertEqual(window.notebook.get_current_page(), 4)
            help_page = window.pages['help']
            self.assertFalse(help_page.text.get_editable())
            self.assertIn('F7', help_page.text.get_buffer().props.text)
            shortcut('F5')
            shortcut('F6')
            shortcut('F7')
            self.assertEqual(app.run_async.call_count, calls)  # help never executes commands
            shortcut('<Control>2')
            self.assertIs(window._current_page(), network)
            shortcut('<Control>f')
            self.assertIs(window.get_focus(), network.search)
            before = window.show_hosts.get_active()
            shortcut('<Control>b')
            self.assertEqual(window.show_hosts.get_active(), not before)
            shortcut('<Control>b')
            network.live.set_active(False)
            with patch.object(network, 'refresh') as refresh:
                shortcut('F5')
                refresh.assert_called_once_with()
                shortcut('F6')
                self.assertTrue(network.live.get_active())
                shortcut('F7')
                self.assertFalse(network.live.get_active())
                shortcut('F7')
                self.assertTrue(network.live.get_active())
                shortcut('F6')
                self.assertFalse(network.live.get_active())
            column = network.columns[2]
            path = Gtk.TreePath.new_from_indices([0])
            network.text_access._anchor = network.text_access._point(path, column, 0)
            network.text_access._end = network.text_access._point(path, column, 4)
            network.tree.grab_focus()
            shortcut('<Control>c')
            self.assertEqual(Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text(), '10.0')
            shortcut('Escape')
            self.assertEqual(network.text_access.selected_text(), '')
            shortcut('<Control>a')
            self.assertEqual(network.text_access.selected_text(), network.text_access.all_text())
            shortcut('Escape')
            # A disconnected/reconnected target retains widgets, filters and rows.
            remote.connected = False
            window._ssh_state_changed(remote, 'disconnected', 'fixture loss')
            self.assertEqual(window.connection_state.get_text(), 'Disconnected')
            self.assertIn('stale', window.connection_notice.get_text())
            self.assertEqual(network.store[0][2], '10.0.0.1')
            self.assertFalse(network.live.get_active())
            remote.resolve_action.reset_mock()
            self.assertIsNone(maintenance._resolve(None)[0])
            remote.resolve_action.assert_not_called()
            replacement = SimpleNamespace(**vars(remote))
            replacement.connected = True
            replacement.close = Mock()
            replacement.state_handler = None
            network.search.set_text('10.0')
            pages = dict(window.pages)
            tab = window.notebook.get_current_page()
            window._rebind_host(replacement, 0)
            self.assertEqual(window.notebook.get_current_page(), tab)
            self.assertEqual(window.pages, pages)
            self.assertEqual(network.search.get_text(), '10.0')
            self.assertEqual(network.columns[2].get_fixed_width(), 190)
            self.assertIs(network.host, replacement)
            remote.resolve_action.assert_called()  # Availability only.
            window.remote_fresh('network', replacement)
            self.assertNotIn('network', window._remote_stale)
            self.assertIn('logs', window._remote_stale)
            self.assertFalse(window.pages['logs'].log_scroll.get_overlay_scrolling())
            window._use_host(None,None)
            settle()
            self.assertFalse(previous_context.active)
            remote.close.assert_called_once_with()
            self.assertTrue(network._destroyed)
            self.assertIsNone(window.active_host)
            self.assertEqual(window.host_label.get_text(),'Local host')
            self.assertEqual(app.config['columns']['network']['Local address'],190)
            self.assertIsNone(window.pages['logs'].host)
            shortcut('<Control>5')
            self.assertIn('help', window.pages)
            self.assertFalse(window.pages['help'].text.get_editable())
        finally:
            app._closing=True
            window.close_hosts()
            window.destroy()
            app.executor.shutdown(wait=True)


if __name__=='__main__':unittest.main()
