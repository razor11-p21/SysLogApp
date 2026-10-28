#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated real GTK close/save-failure scenarios; private temporary settings."""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
import unittest
from unittest.mock import Mock, patch
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gio, GLib
from syslogapp import config
from syslogapp.app import MainWindow, SysLogApplication


class CloseTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name, value in (('CONFIG_DIR', root), ('CONFIG_FILE', root/'config.json')):
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        config.save_config({'log_lines': 400})
        self.previous = config.CONFIG_FILE.read_bytes()
        self.app = SysLogApplication()
        self.app.set_application_id(f'gr.syslogapp.closeTests.p{os.getpid()}.t{id(self)}')
        self.app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(self.app.register(None))
        self.app.run_async = Mock()
        self.window = MainWindow(self.app)
        self.app.window = self.window
        self.window.close_hosts = Mock()
        self.app.config['log_lines'] = 700
        self.original_save = config.save_config
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.window.destroy()
        self.app.executor.shutdown(wait=True)
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

    def fail(self):
        return patch('syslogapp.app.save_config', side_effect=PermissionError('fixture write denied'))

    def test_keep_open_preserves_settings_hosts_and_can_close_later(self):
        with self.fail() as save, patch.object(self.window, '_save_failure_response', return_value=Gtk.ResponseType.CANCEL):
            self.assertTrue(self.window._delete_event())
            self.assertEqual(save.call_count, 1)
        self.window.close_hosts.assert_not_called()
        self.assertEqual(config.CONFIG_FILE.read_bytes(), self.previous)
        self.assertFalse(self.window._layout_saved)
        self.assertFalse(self.window._close_prompt_active)
        self.assertFalse(self.window._skip_layout_save)
        with patch('syslogapp.app.save_config', wraps=self.original_save) as save:
            self.assertFalse(self.window._delete_event())
            self.assertTrue(self.window._save_layout())
            self.assertEqual(save.call_count, 1)
        self.assertEqual(config.load_config()['log_lines'], 700)
        self.window.close_hosts.assert_called_once()

    def test_retry_writes_latest_layout_then_closes_once(self):
        def retry():
            self.window._normal_size = (970, 630)
            return Gtk.ResponseType.ACCEPT
        with patch('syslogapp.app.save_config', side_effect=[PermissionError('fixture'), None]) as save, \
             patch.object(self.window, '_save_failure_response', side_effect=retry):
            self.assertFalse(self.window._delete_event())
        self.assertEqual(save.call_count, 2)
        self.assertEqual(save.call_args.args[0]['window']['width'], 970)
        self.assertTrue(self.window._layout_saved)
        self.assertIsNone(self.window._layout_save_error)
        self.window.close_hosts.assert_called_once()

    def test_close_without_saving_is_not_retried_by_shutdown(self):
        with self.fail() as save, patch.object(self.window, '_save_failure_response', return_value=Gtk.ResponseType.REJECT):
            self.assertFalse(self.window._delete_event())
            self.assertTrue(self.window._save_layout())  # shutdown's fallback
            self.assertEqual(save.call_count, 1)
        self.assertTrue(self.window._skip_layout_save)
        self.assertFalse(self.window._layout_saved)
        self.assertEqual(config.CONFIG_FILE.read_bytes(), self.previous)
        self.window.close_hosts.assert_called_once()

    def test_repeated_retry_failure_keeps_open_on_dialog_dismissal(self):
        with self.fail() as save, patch.object(self.window, '_save_failure_response',
                                             side_effect=[Gtk.ResponseType.ACCEPT, Gtk.ResponseType.DELETE_EVENT]):
            self.assertTrue(self.window._delete_event())
            self.assertEqual(save.call_count, 2)
        self.window.close_hosts.assert_not_called()
        self.assertFalse(self.window._skip_layout_save)
        self.assertEqual(config.CONFIG_FILE.read_bytes(), self.previous)

    def test_busy_maintenance_and_reentrant_close_do_not_write(self):
        self.window.pages['maintenance'] = Mock(_busy=True)
        with patch('syslogapp.app.save_config') as save:
            self.assertTrue(self.window._delete_event())
            save.assert_not_called()
        self.window.pages.pop('maintenance')
        self.window._close_prompt_active = True
        with patch('syslogapp.app.save_config') as save:
            self.assertTrue(self.window._delete_event())
            save.assert_not_called()
        self.window.close_hosts.assert_not_called()

    def test_real_modal_dialog_has_safe_options_and_closing_it_keeps_open(self):
        errors = []
        def respond():
            try:
                dialogs = [widget for widget in Gtk.Window.list_toplevels() if isinstance(widget, Gtk.MessageDialog)]
                self.assertEqual(len(dialogs), 1)
                dialog = dialogs[0]
                self.assertIs(dialog.get_transient_for(), self.window)
                self.assertTrue(dialog.get_modal())
                self.assertEqual(dialog.get_default_widget().get_label(), 'Retry')
                for response, label in ((Gtk.ResponseType.ACCEPT, 'Retry'),
                                        (Gtk.ResponseType.REJECT, 'Close without saving'),
                                        (Gtk.ResponseType.CANCEL, 'Keep open')):
                    self.assertEqual(dialog.get_widget_for_response(response).get_label(), label)
                self.assertIn('fixture write denied', dialog.props.secondary_text)
                self.assertTrue(self.window._delete_event())  # no duplicate prompt
                dialog.response(Gtk.ResponseType.DELETE_EVENT)
            except BaseException as error:
                errors.append(error)
                for dialog in Gtk.Window.list_toplevels():
                    if isinstance(dialog, Gtk.MessageDialog):
                        dialog.response(Gtk.ResponseType.CANCEL)
            return False
        GLib.idle_add(respond)
        with self.fail():
            self.assertTrue(self.window._delete_event())
        if errors:
            raise errors[0]
        self.window.close_hosts.assert_not_called()
        self.assertFalse(self.window._close_prompt_active)
        self.assertFalse(any(isinstance(widget, Gtk.MessageDialog) for widget in Gtk.Window.list_toplevels()))


if __name__ == '__main__':
    unittest.main()
