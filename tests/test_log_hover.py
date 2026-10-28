# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk
from syslogapp.pages.logs import LogsPage
from syslogapp.log_hover import LogHover


@unittest.skipUnless(Gtk.init_check()[0], 'GTK desktop required')
class HoverTests(unittest.TestCase):
    def setUp(self):
        self.page = LogsPage(SimpleNamespace(config={}, run_async=Mock()))
        self.window = Gtk.OffscreenWindow()
        self.window.set_default_size(900, 550)
        self.window.add(self.page)
        self.window.show_all()
        self.page.store.append(['now', 'fixture.service', 'Info', '<b>literal log</b>', 6, {}, None])
        for _ in range(100):
            if Gtk.events_pending():
                Gtk.main_iteration_do(False)
        self.hover = self.page.log_hover
        self.hit = (Gtk.TreePath.new_from_indices([0]), self.page.tree_columns[3], 0, 0)

    def tearDown(self):
        self.window.destroy()

    def test_stationary_two_second_timer_restarts_on_motion(self):
        with patch.object(self.hover, '_hit', return_value=self.hit), \
             patch('syslogapp.log_hover.GLib.timeout_add', return_value=123) as timer, \
             patch('syslogapp.log_hover.GLib.source_remove') as remove:
            event = SimpleNamespace(x_root=100, y_root=100, state=0)
            self.assertFalse(self.hover._motion(None, event))
            timer.assert_called_once_with(2000, self.hover._show)
            self.assertIsNone(self.hover.window)
            self.hover._motion(None, event)
            self.assertEqual(timer.call_count, 1)
            event.x_root += 1
            self.hover._motion(None, event)
            remove.assert_called_once_with(123)
            self.assertEqual(timer.call_count, 2)
            self.hover.dismiss()
            self.assertEqual(self.hover.source, 0)

    def test_popup_hides_on_movement_and_during_selection(self):
        self.hover.point = (100, 100)
        with patch.object(self.hover, '_hit', return_value=self.hit):
            self.assertFalse(self.hover._show())
            self.assertTrue(self.hover.window.get_visible())
            self.assertFalse(self.hover.window.get_accept_focus())
            self.assertFalse(self.hover.label.get_use_markup())
            self.assertIn('<b>literal log</b>', self.hover.label.get_text())
            self.assertIsNone(Gtk.grab_get_current())
            with patch.object(self.page.text_access, 'button_press', return_value=True):
                self.page._tree_button_press(self.page.tree, SimpleNamespace(button=3))
            self.assertFalse(self.hover.window.get_visible())
            self.hover.point = (100, 100)
            self.hover._show()
            event = SimpleNamespace(x_root=101, y_root=100, state=Gdk.ModifierType.BUTTON1_MASK)
            with patch('syslogapp.log_hover.GLib.timeout_add') as timer:
                self.hover._motion(None, event)
                self.assertFalse(self.hover.window.get_visible())
                timer.assert_not_called()

    def test_leave_scroll_and_destroy_cancel_pending_preview(self):
        with patch('syslogapp.log_hover.GLib.source_remove') as remove:
            self.hover.source = 123
            self.hover.dismiss()
            remove.assert_called_once_with(123)
        self.assertEqual(self.hover.source, 0)
        self.assertIsNone(self.hover.point)
        self.hover._destroy()
        self.assertTrue(self.hover.destroyed)
        self.assertFalse(self.hover._show())

    def test_refresh_hides_visible_preview_and_large_text_is_bounded(self):
        self.page.store[0][3] = 'x' * 10000
        self.hover.point = (100, 100)
        with patch.object(self.hover, '_hit', return_value=self.hit):
            self.hover._show()
        self.assertEqual(len(self.hover.label.get_text()), 4096)
        self.page.store[0][3] = 'updated'
        self.assertFalse(self.hover.window.get_visible())

    def test_destroy_disconnects_model_and_adjustment_handlers(self):
        subscriptions = list(self.hover._subscriptions)
        self.assertTrue(subscriptions)
        self.hover._destroy()
        self.assertFalse(self.hover._subscriptions)
        self.assertTrue(all(not owner.handler_is_connected(handler) for owner, handler in subscriptions))
        self.hover._destroy()  # Native destruction can follow an earlier cleanup.
