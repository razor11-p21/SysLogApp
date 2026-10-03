# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Exercise scheduling and routing without requiring a graphical display."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    from syslogapp.app import MainWindow
    from syslogapp.pages import dashboard
    from syslogapp.widgets import ResponsiveColumns
    from gi.repository import Gtk
    GTK_AVAILABLE = True
except ImportError:
    GTK_AVAILABLE = False


@unittest.skipUnless(GTK_AVAILABLE, 'GTK Python bindings unavailable')
class UIBehaviorTests(unittest.TestCase):
    def page(self, checked=None, busy=False):
        return SimpleNamespace(_busy=False, _health_busy=busy, _health_checked=checked,
                               refresh_btn=Mock(), health_updated=Mock(),
                               _apply_resources=Mock(), _apply_health=Mock(), app=Mock())

    def test_first_refresh_starts_fast_and_slow_work_independently(self):
        page = self.page()
        dashboard.DashboardPage.refresh(page, force_health=False)
        self.assertEqual(page.app.run_async.call_count, 2)
        self.assertIs(page.app.run_async.call_args_list[0].args[0], dashboard.resource_snapshot)
        self.assertIs(page.app.run_async.call_args_list[1].args[0], dashboard.health_snapshot)

    def test_normal_tick_only_samples_metrics_with_fresh_health(self):
        page = self.page(checked=100)
        with patch.object(dashboard.time, 'monotonic', return_value=130):
            dashboard.DashboardPage.refresh(page, force_health=False)
        self.assertEqual(page.app.run_async.call_count, 1)
        self.assertFalse(page._health_busy)

    def test_due_health_check_runs_once(self):
        page = self.page(checked=100)
        with patch.object(dashboard.time, 'monotonic', return_value=161):
            dashboard.DashboardPage.refresh(page, force_health=False)
            dashboard.DashboardPage.refresh(page, force_health=False)
        self.assertEqual(page.app.run_async.call_count, 2)
        self.assertTrue(page._health_busy)

    def test_manual_refresh_forces_fresh_health(self):
        page = self.page(checked=100)
        with patch.object(dashboard.time, 'monotonic', return_value=105):
            dashboard.DashboardPage.refresh(page)
        self.assertEqual(page.app.run_async.call_count, 2)

    def test_slow_health_does_not_block_live_metrics(self):
        page = self.page(checked=100, busy=True)
        with patch.object(dashboard.time, 'monotonic', return_value=190):
            dashboard.DashboardPage.refresh(page, force_health=False)
        self.assertEqual(page.app.run_async.call_count, 1)
        self.assertIs(page.app.run_async.call_args.args[0], dashboard.resource_snapshot)

    def test_network_search_opens_connections_and_filters(self):
        page = Mock()
        window = SimpleNamespace(search_target=Mock(), show_page=Mock(), pages={'network': page})
        window.search_target.get_active_id.return_value = 'network'
        entry = Mock()
        entry.get_text.return_value = '  firefox  '
        MainWindow._global_search_activate(window, entry)
        window.show_page.assert_called_once_with('network')
        page.view_stack.set_visible_child_name.assert_called_once_with('connections')
        page.search.set_text.assert_called_once_with('firefox')

    def test_logs_search_filters_loaded_logs(self):
        page = Mock()
        window = SimpleNamespace(search_target=Mock(), show_page=Mock(), pages={'logs': page})
        window.search_target.get_active_id.return_value = 'logs'
        entry = Mock()
        entry.get_text.return_value = 'kernel'
        MainWindow._global_search_activate(window, entry)
        page.search.set_text.assert_called_once_with('kernel')
        page.view_stack.set_visible_child_name.assert_not_called()

    def test_sections_stack_at_laptop_width(self):
        widget = Mock()
        widget.get_orientation.return_value = Gtk.Orientation.HORIZONTAL
        ResponsiveColumns._resize(widget, widget, SimpleNamespace(width=700))
        widget.set_orientation.assert_called_once_with(Gtk.Orientation.VERTICAL)

    def test_sections_use_columns_when_space_allows(self):
        widget = Mock()
        widget.get_orientation.return_value = Gtk.Orientation.VERTICAL
        ResponsiveColumns._resize(widget, widget, SimpleNamespace(width=1200))
        widget.set_orientation.assert_called_once_with(Gtk.Orientation.HORIZONTAL)

    def test_navigation_compacts_at_small_width(self):
        labels = [Mock(), Mock()]
        window = SimpleNamespace(sidebar_text=labels, sidebar=Mock())
        MainWindow._resize_navigation(window, window, SimpleNamespace(width=900))
        for label in labels:
            label.set_visible.assert_called_with(False)
            label.set_no_show_all.assert_called_with(True)
        window.sidebar.set_size_request.assert_called_once_with(72, -1)

    def test_unavailable_health_never_renders_a_healthy_summary(self):
        page = SimpleNamespace(_health_busy=True, cards={key: Mock() for key in ('services', 'network', 'logs')},
                               health_pill=Mock(), health_updated=Mock(), issues_list=Mock(),
                               quick_box=Mock(), show_all=Mock())
        page.issues_list.get_children.return_value = []
        page.quick_box.get_children.return_value = []
        snap = {'failed_services': None, 'network': {'connected': True, 'dns': True},
                'error_count': None, 'warning_count': None, 'issues': None,
                'check_errors': {'failed_services': 'Permission denied', 'issues': 'No journal access'},
                'diagnostics': [('info', 'Failed services', "Couldn't check")]}
        with patch.object(dashboard.Gtk, 'Label', return_value=Mock()), patch.object(dashboard, 'DiagnosticRow', return_value=Mock()):
            dashboard.DashboardPage._apply_health(page, snap, None)
        page.health_pill.set_state.assert_called_once_with('Health checks incomplete', 'info')
        self.assertEqual(page.cards['services'].update.call_args.args[1], "Couldn't check")
        self.assertEqual(page.cards['logs'].update.call_args.args[1], "Couldn't check")

    def test_missing_resource_data_does_not_render_normal(self):
        page = SimpleNamespace(_busy=True, refresh_btn=Mock(), cards={key: Mock() for key in ('cpu', 'memory', 'disk')},
                               graph=Mock(), health_labels={key: Mock() for key in ('hostname', 'os', 'kernel', 'uptime', 'last_boot', 'cpu_model', 'disk_space')},
                               last_updated=Mock(), show_all=Mock())
        snap = {key: 'unknown' for key in ('hostname', 'os', 'kernel', 'uptime', 'last_boot', 'cpu_model')}
        snap.update(cpu=None, mem_pct=None, disk_pct=None, disk_free=None, disk_total=None)
        dashboard.DashboardPage._apply_resources(page, snap, None)
        for card in page.cards.values():
            self.assertEqual(card.update.call_args.args[1], "Couldn't check")
        page.graph.add_value.assert_not_called()


if __name__ == '__main__':
    unittest.main()
