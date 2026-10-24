# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from syslogapp.maintenance import stream_process, vacuum_action
from syslogapp import logrotate_config as rotation


class ProgressTests(unittest.TestCase):
    def test_output_arrives_before_process_finishes_and_unicode_is_decoded(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'continue'
            code = '''import os,sys,time
from pathlib import Path
print('ready',flush=True)
end=time.monotonic()+3
while not Path(sys.argv[1]).exists() and time.monotonic()<end:time.sleep(.01)
if not Path(sys.argv[1]).exists():sys.exit(3)
os.write(1,b'\\xe2');time.sleep(.03);os.write(1,b'\\x82\\xac done\\n')
'''
            chunks = []
            def receive(text):
                chunks.append(text)
                if 'ready' in text:
                    marker.touch()
            status, output = stream_process([sys.executable, '-c', code, str(marker)], receive, timeout=5)
            self.assertEqual(status, 0)
            self.assertEqual(''.join(chunks), 'ready\n€ done\n')
            self.assertEqual(output, 'ready\n€ done\n')

    def test_output_tail_is_bounded_and_exit_code_preserved(self):
        status, output = stream_process([sys.executable, '-c',
            'import sys;print("x"*300000);print("last");sys.exit(7)'], lambda _: None)
        self.assertEqual(status, 7)
        self.assertLess(len(output), 132000)
        self.assertTrue(output.startswith('[Earlier output omitted]'))
        self.assertTrue(output.endswith('last\n'))

    def test_readonly_timeout_reaps_process_and_preserves_partial_output(self):
        processes = []
        def spawn(*args, **kwargs):
            process = subprocess.Popen(*args, **kwargs)
            processes.append(process)
            return process
        with self.assertRaises(TimeoutError) as caught:
            stream_process([sys.executable, '-c', 'import time;print("before",flush=True);time.sleep(3)'],
                           lambda _: None, spawn=spawn, timeout=.15)
        self.assertIn('before', caught.exception.output)
        self.assertIsNotNone(processes[0].poll())

    def test_cleanup_parameters_are_fixed_arguments_not_shell_text(self):
        self.assertEqual(vacuum_action('age', 14).command, ('journalctl', '--vacuum-time=14d'))
        self.assertEqual(vacuum_action('size', 512).command, ('journalctl', '--vacuum-size=512M'))
        for mode, value in [('age', 0), ('size', -1), ('size', '1;cmd'), ('anything', 7)]:
            with self.assertRaises(ValueError):
                vacuum_action(mode, value)

    def test_validation_only_never_writes_profile_backup_log_or_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'etc/logrotate.d').mkdir(parents=True)
            (root / 'etc/logrotate.conf').write_text('include /etc/logrotate.d\n')
            (root / 'var/log').mkdir(parents=True)
            log = root / 'var/log/example.log'
            log.write_text('keep this log\n')
            profile = root / 'etc/logrotate.d/syslogapp'
            profile.write_text('# Managed by SysLogApp.\nprevious\n')
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch.object(rotation.shutil, 'which', return_value='/usr/sbin/logrotate'), \
                 patch.object(rotation.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                text = rotation.apply_config(rotation.render('/var/log/example.log', 'weekly', 4, True, 'rename'),
                                             '/var/log/example.log', root, validate_only=True)
            self.assertIn('Validation passed', text)
            self.assertIn('--debug', run.call_args.args[0])
            self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_display_callback_failure_does_not_interrupt_command(self):
        def broken(_):
            raise RuntimeError('display failure')
        status, output = stream_process([sys.executable, '-c', 'print("completed",flush=True)'], broken)
        self.assertEqual(status, 0)
        self.assertIn('completed', output)

    def test_remote_stream_uses_same_bounded_runner_and_password_stdin(self):
        from syslogapp.hosts import SSHHost
        host = SSHHost(dict(hostname='fixture.invalid', username='test', auth='password'))
        chunks = []
        script = 'import sys; value=sys.stdin.readline(); print("received" if value else "missing",flush=True)'
        try:
            with patch.object(host, 'command', return_value=[sys.executable, '-c', script]) as command:
                status, output = host.maintenance(['remote-command'], 'fixture-secret', on_output=chunks.append)
            command.assert_called_once_with(['remote-command'])
            self.assertEqual(status, 0)
            self.assertEqual(output, 'received\n')
            self.assertEqual(''.join(chunks), output)
            self.assertNotIn('fixture-secret', output)
        finally:
            host.close()
