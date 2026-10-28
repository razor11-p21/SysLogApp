# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import subprocess
import sys
import unittest
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk


@unittest.skipUnless(Gtk.init_check()[0], 'GTK desktop required')
class LifecycleHealthTests(unittest.TestCase):
    def test_repeated_tab_destruction_releases_pages_and_descriptors(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('lifecycle_ui_check.py'))],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertNotIn('CRITICAL', result.stderr)
