# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Real GTK visibility checks; use an offscreen window on a desktop session."""
import unittest
from types import SimpleNamespace

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
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
                                           'Selected event', 6, {'MESSAGE': 'Selected event', '_PID': '123'}])
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

    def test_selecting_log_reveals_its_details(self):
        self.page.tree.get_selection().select_iter(self.row)
        self.pump_events()
        self.assertTrue(self.page.details_panel.get_visible())
        buffer = self.page.detail_message.get_buffer()
        message = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        self.assertIn('Selected event', message)
        self.assertIn('PID: 123', message)

    def test_clearing_selection_collapses_and_clears_details(self):
        self.page.tree.get_selection().select_iter(self.row)
        self.page.tree.get_selection().unselect_all()
        self.pump_events()
        self.assertFalse(self.page.details_panel.get_visible())
        self.assertEqual(self.page.detail_message.get_buffer().get_char_count(), 0)
        self.window.show_all()
        self.assertFalse(self.page.details_panel.get_visible())

    def test_reloading_rows_collapses_the_previous_event(self):
        self.page.tree.get_selection().select_iter(self.row)
        self.page.store.clear()
        self.pump_events()
        self.assertFalse(self.page.details_panel.get_visible())


if __name__ == '__main__':
    unittest.main()
