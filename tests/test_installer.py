# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import install_user as installer


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        (self.source / 'syslogapp').mkdir(parents=True)
        (self.source / 'syslogapp/__init__.py').write_text('VERSION = "new"\n')
        (self.source / 'syslogapp.py').write_text('print("new")\n')
        self.user = self.root / 'user with spaces'
        self.app = self.user / '.local/share/syslogapp'
        self.launcher = self.user / '.local/bin/syslogapp'
        self.desktop = self.user / '.local/share/applications/syslogapp.desktop'
        self.app.mkdir(parents=True)
        (self.app / 'old.py').write_text('OLD = True\n')
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_text('#!/bin/sh\necho old\n')
        self.launcher.chmod(0o755)
        self.desktop.parent.mkdir(parents=True)
        self.desktop.write_text('existing desktop entry')
        self.config = self.user / '.config/syslogapp/config.json'
        self.config.parent.mkdir(parents=True)
        self.config.write_text('{"theme":"dark"}')

    def tearDown(self):
        self.temp.cleanup()

    def install(self):
        installer.install(self.source, self.user, preflight=False)

    def assert_previous_intact(self):
        self.assertTrue((self.app / 'old.py').exists())
        self.assertEqual(self.launcher.read_text(), '#!/bin/sh\necho old\n')
        self.assertEqual(self.desktop.read_text(), 'existing desktop entry')
        self.assertEqual(self.config.read_text(), '{"theme":"dark"}')

    def test_success_keeps_settings_desktop_and_backup(self):
        self.install()
        self.assertTrue((self.app / 'syslogapp/__init__.py').exists())
        self.assertEqual(self.desktop.read_text(), 'existing desktop entry')
        self.assertEqual(self.config.read_text(), '{"theme":"dark"}')
        backups = list((self.app.parent / 'syslogapp-backups').glob('*/old.py'))
        self.assertEqual(len(backups), 1)
        self.assertIn('/usr/bin/python3', self.launcher.read_text())
        self.assertIn("'", self.launcher.read_text())  # path with spaces must be quoted

    def test_syntax_error_never_replaces_previous_app(self):
        (self.source / 'syslogapp.py').write_text('this is invalid python !!!')
        with self.assertRaises(SyntaxError):
            self.install()
        self.assert_previous_intact()

    def test_failure_after_app_swap_restores_app_and_launcher(self):
        original = installer.replace_file
        calls = 0
        def fail_first(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError('Simulated launcher write failure')
            return original(*args)
        with patch.object(installer, 'replace_file', side_effect=fail_first):
            with self.assertRaises(OSError):
                self.install()
        self.assert_previous_intact()

    def test_failure_before_new_app_swap_restores_moved_previous(self):
        original = installer.os.replace
        def fail_stage(source, destination):
            if Path(source).name == 'new':
                raise OSError('Simulated app swap failure')
            return original(source, destination)
        with patch.object(installer.os, 'replace', side_effect=fail_stage):
            with self.assertRaises(OSError):
                self.install()
        self.assert_previous_intact()

    def test_failed_first_install_removes_partial_launcher_and_app(self):
        import shutil
        shutil.rmtree(self.app)
        self.launcher.unlink()
        self.desktop.unlink()
        original = installer.replace_file
        def fail_desktop(target, *args):
            if target == self.desktop:
                raise OSError('Simulated desktop write failure')
            return original(target, *args)
        with patch.object(installer, 'replace_file', side_effect=fail_desktop):
            with self.assertRaises(OSError):
                self.install()
        self.assertFalse(self.app.exists())
        self.assertFalse(self.launcher.exists())
        self.assertFalse(self.desktop.exists())
        self.assertTrue(self.config.exists())

    def test_dependency_failure_leaves_previous_installation_intact(self):
        with patch.object(installer, 'check_dependencies', side_effect=RuntimeError('Missing Gtk')):
            with self.assertRaises(RuntimeError):
                installer.install(self.source, self.user)
        self.assert_previous_intact()

    def test_symlink_target_is_not_overwritten(self):
        self.launcher.unlink()
        other = self.root / 'other-file'
        other.write_text('leave me alone')
        self.launcher.symlink_to(other)
        with self.assertRaisesRegex(RuntimeError, 'symbolic link'):
            self.install()
        self.assertEqual(other.read_text(), 'leave me alone')
        self.assertTrue((self.app / 'old.py').exists())
