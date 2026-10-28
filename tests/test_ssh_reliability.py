# SPDX-License-Identifier: GPL-3.0-or-later
import os
import stat
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from syslogapp.hosts import SSHHost, HostContext
from syslogapp.pending_password import PendingPassword, send

PROFILE = dict(hostname='example.com', username='fixture', auth='password')


class ReliabilityTests(unittest.TestCase):
    def test_password_handoff_is_private_and_retry_clears_it(self):
        with tempfile.TemporaryDirectory() as directory:
            try:
                pending = PendingPassword(directory)
            except PermissionError:
                self.skipTest('Unix socket access required')
            try:
                self.assertTrue(stat.S_ISSOCK(pending.path.stat().st_mode))
                self.assertEqual(stat.S_IMODE(pending.path.stat().st_mode), 0o600)
                with patch.dict(os.environ, SYSLOGAPP_SSH_PENDING=str(pending.path)):
                    self.assertTrue(send('fixture-secret'))
                    self.assertTrue(send())
                    self.assertIsNone(pending.take())
                    self.assertTrue(send('fixture-replacement'))
                    self.assertEqual(pending.take(), 'fixture-replacement')
                    self.assertIsNone(pending.take())
            finally:
                pending.close()
            self.assertFalse(pending.path.exists())

    def test_new_password_saved_only_after_successful_authentication_and_probe(self):
        for result in ('success', 'authentication-failed', 'probe-failed'):
            with self.subTest(result=result):
                host = SSHHost(PROFILE)
                pending = Mock(path=Path('/tmp/fixture-password-handoff'))
                pending.take.return_value = 'fixture-secret'
                proc = Mock()
                proc.wait.return_value = 255 if result == 'authentication-failed' else 0
                events = []
                def probe():
                    events.append('verified')
                    if result == 'probe-failed':
                        raise RuntimeError('fixture probe failure')
                def save(secret):
                    self.assertEqual(secret, 'fixture-secret')
                    self.assertTrue(host.connected)
                    self.assertEqual(events, ['verified'])
                try:
                    with patch('syslogapp.pending_password.PendingPassword', return_value=pending), \
                         patch('syslogapp.credentials.PasswordStore') as store, \
                         patch.object(host, '_spawn', return_value=proc), \
                         patch.object(host, '_probe', side_effect=probe), \
                         patch.object(host, '_watch_master'), \
                         patch('syslogapp.hosts.subprocess.run'):
                        store.return_value.save.side_effect = save
                        if result == 'success':
                            host.connect()
                            store.return_value.save.assert_called_once()
                        else:
                            with self.assertRaises(RuntimeError):
                                host.connect()
                            store.assert_not_called()
                            pending.take.assert_not_called()
                        pending.close.assert_called_once()
                finally:
                    host.close()

    def test_command_failure_only_disconnects_when_transport_check_fails(self):
        host = SSHHost(PROFILE)
        self.addCleanup(host.close)
        host._set_state('connected')
        host.state_handler = Mock()
        with patch.object(host, '_control_check', return_value='healthy'):
            host.check_transport()
        self.assertTrue(host.connected)
        host.state_handler.assert_not_called()
        with patch.object(host, '_control_check', side_effect=RuntimeError('gone')):
            host.check_transport()
        self.assertFalse(host.connected)
        self.assertEqual(host.state, 'disconnected')
        host.state_handler.assert_called_once()

    @unittest.skipUnless(hasattr(os, 'pidfd_open'), 'Linux pidfd required')
    def test_idle_master_exit_notifies_without_polling(self):
        child = subprocess.Popen(['sleep', '30'])
        host = SSHHost(PROFILE)
        event = threading.Event()
        host._set_state('connected')
        host.state_handler = lambda *args: event.set()
        try:
            with patch.object(host, '_control_check', return_value=f'Master running (pid={child.pid})') as check:
                host._watch_master()
                child.terminate()
                child.wait(timeout=3)
                self.assertTrue(event.wait(3))
                self.assertFalse(host.connected)
                check.assert_called_once()
        finally:
            host.close()
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=3)

    def test_reconnect_invalidates_queued_work_and_callbacks(self):
        app = SimpleNamespace(config={}, window=None, _closing=False, run_async=Mock())
        context = HostContext(app, SimpleNamespace(connected=True))
        read, done = Mock(), Mock()
        context.run_async(read, done)
        work, callback = app.run_async.call_args.args
        context.generation += 1
        with self.assertRaisesRegex(RuntimeError, 'Obsolete'):
            work()
        callback('old data', None)
        read.assert_not_called()
        done.assert_not_called()
        context.host.connected = False
        context.run_async(read, done)
        work, callback = app.run_async.call_args.args
        with self.assertRaisesRegex(RuntimeError, 'disconnected'):
            work()
        read.assert_not_called()

    def test_failed_password_socket_setup_closes_descriptor_and_removes_owned_path(self):
        channel = Mock()
        with tempfile.TemporaryDirectory() as directory:
            for failure in ('bind', 'chmod'):
                with self.subTest(failure=failure):
                    channel.reset_mock()
                    channel.bind.side_effect = PermissionError('fixture') if failure == 'bind' else None
                    with patch('syslogapp.pending_password.socket.socket', return_value=channel), \
                         patch('syslogapp.pending_password.Path.chmod', side_effect=PermissionError('fixture')), \
                         patch('syslogapp.pending_password.Path.unlink') as unlink:
                        with self.assertRaises(PermissionError):
                            PendingPassword(directory)
                        channel.close.assert_called_once()
                        self.assertEqual(unlink.call_count, int(failure == 'chmod'))

    def test_closed_session_cannot_be_revived_by_late_connection_notification(self):
        host = SSHHost(PROFILE)
        host.close()
        host._set_state('connected')
        self.assertFalse(host.connected)
        self.assertEqual(host.state, 'disconnected')

    @unittest.skipUnless(hasattr(os, 'pidfd_open'), 'Linux pidfd required')
    def test_watcher_setup_failure_closes_pidfd(self):
        host = SSHHost(PROFILE)
        self.addCleanup(host.close)
        with patch.object(host, '_control_check', return_value='Master running (pid=123)'), \
             patch('syslogapp.hosts.os.pidfd_open', return_value=999), \
             patch('syslogapp.hosts.os.pipe', side_effect=OSError('fixture descriptor limit')), \
             patch('syslogapp.hosts.os.close') as close:
            host._watch_master()
            close.assert_called_once_with(999)
