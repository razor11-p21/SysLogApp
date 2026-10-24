# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib
    from syslogapp.pages.logs import LogsPage
    from syslogapp.pages.network import NetworkPage
    from syslogapp.pages.overview import OverviewPage
    HAS_DISPLAY = Gtk.init_check()[0]
except ImportError:
    HAS_DISPLAY = False


@unittest.skipUnless(HAS_DISPLAY, 'GTK desktop required')
class ColumnTests(unittest.TestCase):
    def settle(self):
        loop = GLib.MainLoop()
        GLib.timeout_add(150, lambda: (loop.quit(), False)[1])
        loop.run()

    def test_all_tables_keep_dragged_widths_and_can_refit(self):
        for page_class in (LogsPage, NetworkPage, OverviewPage):
            with self.subTest(page=page_class.__name__):
                app = SimpleNamespace(config={'log_lines':400}, run_async=Mock())
                page = page_class(app)
                window = Gtk.OffscreenWindow()
                window.set_size_request(1000,650)
                window.add(page)
                window.show_all()
                self.settle()
                sizing = page.column_sizing
                self.assertTrue(all(col.get_resizable() for col in sizing.columns))
                index = len(sizing.columns) - 1
                column = sizing.columns[index]
                column.set_fixed_width(250)
                self.settle()
                self.assertEqual(sizing.manual[index],250)
                renderer = sizing.renderers[index]
                self.assertEqual(renderer.get_property('wrap-width'),238)
                window.set_size_request(640,650)
                window.resize(640,650)
                self.settle()
                self.assertEqual(column.get_fixed_width(),250)
                page._fit_columns()
                self.settle()
                self.assertEqual(sizing.manual,{})
                window.destroy()
                self.settle()

    def test_horizontal_updates_coalesce_and_destroy_cancels_pending_work(self):
        page = LogsPage(SimpleNamespace(config={}, run_async=Mock()))
        sizing = page.column_sizing
        try:
            sizing.apply_deferred([28, 112, 168, 70, 500])
            for width in range(499, 399, -1):
                sizing.apply_deferred([28, 112, 168, 70, width])
            self.assertEqual(sizing.columns[-1].get_fixed_width(), 500)
            source = sizing._resize_source
            self.assertNotEqual(source, 0)
            sizing.apply_deferred([28, 112, 168, 70, 400])
            self.assertEqual(sizing._resize_source, source)
            self.settle()
            self.assertEqual(sizing.columns[-1].get_fixed_width(), 400)
            self.assertEqual(sizing._resize_source, 0)
            sizing.apply_deferred([28, 112, 168, 70, 450])
            self.assertNotEqual(sizing._resize_source, 0)
        finally:
            page.destroy()
        self.assertEqual(sizing._resize_source, 0)
        self.assertIsNone(sizing._pending_widths)

    def test_live_button_restores_time_sort_and_requests_newest(self):
        page = LogsPage(SimpleNamespace(config={},run_async=Mock()))
        self.assertEqual(page.store.get_sort_column_id(),(page.COL_TIME,Gtk.SortType.ASCENDING))
        page.store.set_sort_column_id(page.COL_UNIT,Gtk.SortType.ASCENDING)
        page.start_live = Mock()
        button = Mock()
        button.get_active.return_value=True
        page._on_live(button)
        self.assertEqual(page.store.get_sort_column_id(),(page.COL_TIME,Gtk.SortType.ASCENDING))
        page.start_live.assert_called_once_with()
        page.store.append(['01:00:00','a','Info','first',6,{'__REALTIME_TIMESTAMP':'1000000'}])
        page.store.append(['02:00:00','b','Info','last',6,{'__REALTIME_TIMESTAMP':'2000000'}])
        page.tree.scroll_to_cell=Mock()
        page._scroll_to_latest()
        self.assertEqual(page.tree.scroll_to_cell.call_args.args[0].to_string(),'1')
        page.destroy()
