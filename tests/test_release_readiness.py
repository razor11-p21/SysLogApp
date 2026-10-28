# SPDX-License-Identifier: GPL-3.0-or-later
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import install_user
from syslogapp.hosts import SSHHost
from syslogapp.maintenance import ACTIONS


class ReleaseReadinessTests(unittest.TestCase):
    def test_dependency_guidance_for_distro_families(self):
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / 'os-release'
            for name, family, expected in (
                ('linuxmint', 'ubuntu debian', 'sudo apt install'),
                ('ubuntu', 'debian', 'sudo apt install'),
                ('debian', '', 'sudo apt install'),
                ('fedora', '', 'sudo dnf install'),
                ('derivative', 'fedora', 'sudo dnf install'),
                ('unknown', '', 'distribution package manager'),
            ):
                with self.subTest(name=name):
                    release.write_text(f'ID={name}\nID_LIKE="{family}"\n')
                    self.assertIn(expected, install_user.dependency_hint(release))
            release.unlink()
            self.assertIn('distribution package manager', install_user.dependency_hint(release))

    def test_fedora_guidance_uses_fedora_package_names(self):
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / 'os-release'
            release.write_text('ID=fedora\n')
            hint = install_user.dependency_hint(release)
            for package in ('python3-gobject', 'gtk3', 'iproute', 'openssh-clients'):
                self.assertIn(package, hint.split())
            self.assertNotIn('python3-gi', hint)

    def test_clean_install_and_two_upgrades_preserve_settings_and_backups(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            source, user = root / 'source', root / 'user with spaces'
            (source / 'syslogapp').mkdir(parents=True)
            (source / 'syslogapp.py').write_text('pass\n')
            module = source / 'syslogapp/__init__.py'
            config = user / '.config/syslogapp/config.json'
            config.parent.mkdir(parents=True)
            config.write_text('{"hosts":[],"log_lines":700}')
            for version in range(3):
                module.write_text(f'VERSION = {version}\n')
                install_user.install(source, user, preflight=False)
                self.assertEqual((user / '.local/share/syslogapp/syslogapp/__init__.py').read_text(), module.read_text())
                self.assertEqual(config.read_text(), '{"hosts":[],"log_lines":700}')
                self.assertEqual(len(list((user / '.local/share/syslogapp-backups').glob('previous-*'))), version)
            launcher = user / '.local/bin/syslogapp'
            self.assertEqual(launcher.stat().st_mode & 0o777, 0o755)
            self.assertTrue((user / '.local/share/applications/syslogapp.desktop').exists())

    def test_debian_and_fedora_remote_capabilities_not_distro_name(self):
        for family in ('debian', 'fedora'):
            with self.subTest(family=family):
                host = SSHHost(dict(hostname='fixture.invalid', username='fixture', auth='key'))
                try:
                    tools = ['journalctl', 'ip', 'ss', 'python3', 'sudo', 'systemctl', 'cat', 'find', 'logrotate']
                    if family == 'debian':
                        tools += ['apt-get', 'dpkg']
                    probe = '\n'.join(f'{name}=/usr/bin/{name}' for name in tools)
                    probe += '\nuid=1000\nhostname=fixture\npython-version=3.12\n'
                    with patch.object(host, 'capture', side_effect=[(probe, False), ('', False)]):
                        host._probe()
                    self.assertTrue(host.python_ready)
                    self.assertIsNotNone(host.resolve_action(ACTIONS[1])[0])
                    for action in (ACTIONS[2], ACTIONS[5]):
                        command, reason = host.resolve_action(action)
                        if family == 'debian':
                            self.assertIsNotNone(command)
                        else:
                            self.assertIsNone(command)
                            self.assertIn('unavailable', reason)
                finally:
                    host.close()
