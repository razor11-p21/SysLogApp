# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import subprocess
import sys
import unittest
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk


@unittest.skipUnless(Gtk.init_check()[0], 'GTK desktop required')
class SettingsCloseTests(unittest.TestCase):
    def test_real_gtk_settings_save_failure_scenarios(self):
        scenarios = ('keep_open_preserves_settings_hosts_and_can_close_later',
                     'retry_writes_latest_layout_then_closes_once',
                     'close_without_saving_is_not_retried_by_shutdown',
                     'repeated_retry_failure_keeps_open_on_dialog_dismissal',
                     'busy_maintenance_and_reentrant_close_do_not_write',
                     'real_modal_dialog_has_safe_options_and_closing_it_keeps_open')
        # Gtk.Application registration/shutdown needs one process per lifecycle.
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                result = subprocess.run([sys.executable, '-W', 'error::ResourceWarning',
                                         str(Path(__file__).with_name('settings_close_ui_check.py')),
                                         'CloseTests.test_' + scenario],
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertNotIn('CRITICAL', result.stderr)
                self.assertNotIn('ResourceWarning', result.stderr)
