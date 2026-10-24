# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from syslogapp.pages.logs import LogsPage
from syslogapp.pages.network import NetworkPage


@unittest.skipUnless(Gtk.init_check()[0], 'No GTK desktop display')
class ToolbarTests(unittest.TestCase):
    def app(self):
        return SimpleNamespace(config={}, run_async=Mock(), window=SimpleNamespace(toast=Mock()))

    def test_logs_live_paused_button_and_selection_pause(self):
        page = LogsPage(self.app())
        try:
            self.assertEqual(page.live.get_label(), 'Paused')
            self.assertFalse(hasattr(page, 'pause_live'))
            with patch.object(page, 'start_live') as start:
                page.toggle_pause()
                self.assertTrue(page.live.get_active())
                self.assertEqual(page.live.get_label(), 'Live')
                self.assertTrue(page.live.get_style_context().has_class('active-live'))
                start.assert_called_once_with()
                page._hold_for_selection()
                self.assertFalse(page.live.get_active())
                self.assertEqual(page.live.get_label(), 'Paused')
                self.assertTrue(page.live.get_style_context().has_class('paused-live'))
                page.toggle_pause()
                self.assertTrue(page.live.get_active())
                self.assertEqual(start.call_count, 2)
        finally:
            page.destroy()

    def test_more_menu_contains_export_and_restores_column_fit(self):
        page = LogsPage(self.app())
        try:
            items = page.more_actions.get_popup().get_children()
            self.assertEqual([item.get_label() for item in items], ['Export logs…', 'Fit columns'])
            page.tree_columns[1].set_fixed_width(250)
            self.assertTrue(page.column_sizing.manual)
            items[1].activate()
            self.assertFalse(page.column_sizing.manual)
        finally:
            page.destroy()

    def test_search_expands_with_window_and_bars_fit_narrow_viewport(self):
        for cls in (LogsPage, NetworkPage):
            page = cls(self.app())
            window = Gtk.OffscreenWindow()
            window.add(page)
            widths = []
            try:
                for width in (460, 1100):
                    window.set_size_request(width, 700)
                    window.resize(width, 700)
                    window.show_all()
                    loop = GLib.MainLoop()
                    GLib.timeout_add(180, lambda: (loop.quit(), False)[1])
                    loop.run()
                    self.assertLessEqual(window.get_allocated_width(), width)
                    widths.append(page.search.get_allocated_width())
                self.assertGreater(widths[1], widths[0] + 300)
            finally:
                window.destroy()
