# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Real GTK visibility checks; use an offscreen window on a desktop session."""
import unittest
from types import SimpleNamespace

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib, Gdk
    from syslogapp.pages.logs import LogsPage
    HAS_DISPLAY = Gtk.init_check()[0]
except ImportError:
    HAS_DISPLAY = False


@unittest.skipUnless(HAS_DISPLAY, 'No GTK desktop display')
class LogDetailsTests(unittest.TestCase):
    def setUp(self):
        app = SimpleNamespace(config={'log_lines': 400}, run_async=lambda *_: None)
        self.page = LogsPage(app)
        self.window = Gtk.OffscreenWindow()
        self.window.set_default_size(1000, 650)
        self.window.add(self.page)
        self.window.show_all()
        self.row = self.page.store.append(['12:00:00 · Today', 'test.service', 'Info',
                                           'Selected event', 6, {'MESSAGE': 'Selected event', '_PID': '123'}, None])
        self.pump_events()

    def tearDown(self):
        self.window.destroy()
        self.pump_events()

    def pump_events(self):
        for _ in range(1000):
            if not Gtk.events_pending():
                break
            Gtk.main_iteration_do(False)

    def test_initial_details_remain_collapsed_after_show_all(self):
        self.assertFalse(self.page.details_panel.get_visible())
        self.window.show_all()
        self.pump_events()
        self.assertFalse(self.page.details_panel.get_visible())

    def test_single_selection_keeps_details_collapsed(self):
        self.page.tree.get_selection().select_iter(self.row)
        self.pump_events()
        self.assertFalse(self.page.details_panel.get_visible())
        self.assertEqual(self.page.detail_message.get_buffer().get_char_count(), 0)

    def test_double_click_reveals_event_details(self):
        self.settle_layout()
        path = self.page.store.get_path(self.row)
        column = self.page.tree_columns[self.page.COL_MESSAGE]
        area = self.page.tree.get_cell_area(path, column)
        event = SimpleNamespace(button=1, type=Gdk.EventType._2BUTTON_PRESS,
                                x=area.x + 10, y=area.y + 5)
        self.assertTrue(self.page._tree_button_press(self.page.tree, event))
        self.pump_events()
        self.assertTrue(self.page.details_panel.get_visible())
        buffer = self.page.detail_message.get_buffer()
        message = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        self.assertIn('Selected event', message)
        self.assertIn('PID: 123', message)

    def test_clearing_selection_collapses_and_clears_details(self):
        self.page.tree.row_activated(self.page.store.get_path(self.row), self.page.tree_columns[0])
        self.assertTrue(self.page.details_panel.get_visible())
        self.page.tree.get_selection().unselect_all()
        self.pump_events()
        self.assertFalse(self.page.details_panel.get_visible())
        self.assertEqual(self.page.detail_message.get_buffer().get_char_count(), 0)
        self.window.show_all()
        self.assertFalse(self.page.details_panel.get_visible())

    def test_reloading_rows_collapses_the_previous_event(self):
        self.page.tree.row_activated(self.page.store.get_path(self.row), self.page.tree_columns[0])
        self.assertTrue(self.page.details_panel.get_visible())
        self.page.store.clear()
        self.pump_events()
        self.assertFalse(self.page.details_panel.get_visible())

    def settle_layout(self):
        loop = GLib.MainLoop()
        GLib.timeout_add(180, lambda: (loop.quit(), False)[1])
        loop.run()
        self.pump_events()

    def test_timestamp_uses_the_same_severity_color_as_level(self):
        for priority in range(8):
            self.page.store.set_value(self.row, self.page.COL_PRIORITY, priority)
            column = self.page.tree_columns[self.page.COL_TIME]
            column.cell_set_cell_data(self.page.store, self.row, False, False)
            actual = self.page.tree_renderers[self.page.COL_TIME].get_property('foreground-rgba')
            expected = Gdk.RGBA()
            expected.parse(self.page._severity_color(priority))
            self.assertTrue(actual.equal(expected), f'Incorrect timestamp color for priority {priority}')

    def test_messages_wrap_and_unwrap_when_window_resizes(self):
        text = 'Responsive journal message with several words to wrap naturally. ' * 5
        self.page.store.set_value(self.row, self.page.COL_MESSAGE, text)
        self.window.set_size_request(1100, 650)
        self.window.resize(1100, 650)
        self.settle_layout()
        wide_width = self.page.tree_renderers[self.page.COL_MESSAGE].get_property('wrap-width')
        wide_height = self.page.tree.get_background_area(Gtk.TreePath.new_from_indices([0]), None).height
        self.window.set_size_request(640, 650)
        self.window.resize(640, 650)
        self.settle_layout()
        narrow_width = self.page.tree_renderers[self.page.COL_MESSAGE].get_property('wrap-width')
        narrow_height = self.page.tree.get_background_area(Gtk.TreePath.new_from_indices([0]), None).height
        self.assertLess(narrow_width, wide_width)
        self.assertGreater(narrow_height, wide_height)
        self.window.set_size_request(1100, 650)
        self.window.resize(1100, 650)
        self.settle_layout()
        expanded_height = self.page.tree.get_background_area(Gtk.TreePath.new_from_indices([0]), None).height
        self.assertLess(expanded_height, narrow_height)
        self.assertEqual(self.page.store[0][self.page.COL_MESSAGE], text)

    def test_destroy_cancels_resize_work(self):
        self.page._schedule_reflow()
        self.assertNotEqual(self.page._reflow_source, 0)
        self.page.destroy()
        self.assertEqual(self.page._reflow_source, 0)


if __name__ == '__main__':
    unittest.main()
