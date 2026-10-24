# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from syslogapp import logrotate_config as rotation


class RotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'etc/logrotate.d').mkdir(parents=True)
        (self.root / 'etc/logrotate.conf').write_text('weekly\ninclude /etc/logrotate.d\n')
        (self.root / 'var/log').mkdir(parents=True)
        (self.root / 'var/log/myapp.log').write_text('preserve this log\n')
        self.target = self.root / 'etc/logrotate.d/syslogapp'
        self.content = rotation.render('/var/log/myapp.log', 'weekly', 4, True, 'rename')

    def test_no_free_form_paths_or_directives(self):
        for path in ('/etc/passwd', '/var/log/../etc/passwd', '/var/log/*.log',
                     '/var/log/test\npostrotate', '/var/log/test".log'):
            with self.assertRaises(ValueError):
                rotation.render(path, 'daily', 4, True, 'rename')
        for frequency, keep, mode, size in (('never',4,'rename',0), ('daily',0,'rename',0),
                 ('daily',4,'script',0), ('daily',4,'rename',-1)):
            with self.assertRaises(ValueError):
                rotation.render('/var/log/a.log', frequency, keep, True, mode, size)

    def test_only_atomic_app_profile_changes_after_dry_run(self):
        old = '# Managed by SysLogApp.\nold contents\n'
        self.target.write_text(old)
        distro = self.root / 'etc/logrotate.d/rsyslog'
        distro.write_text('# distro owned\n')
        def validate(args, **kwargs):
            self.assertIn('--debug', args)
            self.assertNotIn('--force', args)
            self.assertEqual(self.target.read_text(), old)
            staging_main = Path(args[-1]).read_text()
            self.assertIn('rules', staging_main)
            self.assertEqual(kwargs['timeout'], 15)
            return subprocess.CompletedProcess(args, 0)
        with patch.object(rotation.shutil, 'which', return_value='/usr/sbin/logrotate'), \
             patch.object(rotation.subprocess, 'run', side_effect=validate):
            output = rotation.apply_config(self.content, '/var/log/myapp.log', self.root)
        self.assertEqual(self.target.read_text(), self.content)
        self.assertEqual(distro.read_text(), '# distro owned\n')
        backups = list((self.root / 'var/backups/syslogapp').glob('*.conf'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), old)
        self.assertIn('No logs were rotated', output)
        self.assertEqual((self.root / 'var/log/myapp.log').read_text(), 'preserve this log\n')

    def test_validation_error_does_not_change_configuration(self):
        old = '# Managed by SysLogApp.\nold\n'
        self.target.write_text(old)
        with patch.object(rotation.shutil, 'which', return_value='/usr/sbin/logrotate'), \
             patch.object(rotation.subprocess, 'run', return_value=subprocess.CompletedProcess([],1)):
            with self.assertRaisesRegex(ValueError, 'nothing changed'):
                rotation.apply_config(self.content, '/var/log/myapp.log', self.root)
        self.assertEqual(self.target.read_text(), old)
        self.assertFalse((self.root / 'var/backups/syslogapp').exists())

    def test_refuses_unmanaged_profile_symlinks_and_missing_logs(self):
        self.target.write_text('# somebody else owns this\n')
        with self.assertRaisesRegex(ValueError, 'not app-managed'):
            rotation.apply_config(self.content, '/var/log/myapp.log', self.root)
        self.target.unlink()
        self.target.symlink_to(self.root / 'etc/logrotate.conf')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            rotation.apply_config(self.content, '/var/log/myapp.log', self.root)
        with self.assertRaises(OSError):
            rotation.apply_config(self.content, '/var/log/missing.log', self.root)

    def test_copytruncate_and_size_are_explicit(self):
        text = rotation.render('/var/log/myapp.log', 'daily', 7, False, 'copytruncate', 50)
        self.assertIn('copytruncate', text)
        self.assertIn('maxsize 50M', text)
        self.assertIn('nocompress', text)
        self.assertNotIn('postrotate', text)

    def test_generated_profile_parses_with_real_logrotate_without_rotation(self):
        import shutil
        executable = shutil.which('logrotate')
        if not executable:
            self.skipTest('logrotate not installed')
        candidate = self.root / 'candidate.conf'
        candidate.write_text(self.content)
        result = subprocess.run([executable,'--debug','--state','/dev/null',str(candidate)],
                                capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((self.root / 'var/log/myapp.log').read_text(),'preserve this log\n')

    def test_duplicate_rule_detected_by_real_validator_without_install(self):
        import shutil
        if not shutil.which('logrotate'):
            self.skipTest('logrotate not installed')
        (self.root / 'etc/logrotate.d/existing').write_text('/var/log/myapp.log {\n weekly\n rotate 4\n missingok\n}\n')
        with self.assertRaisesRegex(ValueError,'validation failed'):
            rotation.apply_config(self.content, '/var/log/myapp.log', self.root)
        self.assertFalse(self.target.exists())
