# SPDX-License-Identifier: GPL-3.0-or-later
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch
from syslogapp.credentials import PasswordStore, CredentialError
from syslogapp import ssh_askpass

ACCOUNT = dict(hostname='Example.COM', username='alice', port=2222)


class CredentialTests(unittest.TestCase):
    def test_store_scopes_secrets_to_host_user_and_port_and_uses_secret_service(self):
        store = PasswordStore(ACCOUNT)
        store.secret = Mock(COLLECTION_DEFAULT='default')
        store.secret.password_store_sync.return_value = True
        store.save('fixture-secret')
        args = store.secret.password_store_sync.call_args.args
        self.assertEqual(args[1], dict(hostname='example.com', username='alice', port='2222'))
        self.assertEqual(args[4], 'fixture-secret')
        self.assertNotIn('fixture-secret', args[3])
        store.lookup()
        store.forget()
        store.secret.password_lookup_sync.assert_called_once()
        store.secret.password_clear_sync.assert_called_once()

    def test_backend_failure_never_exposes_secret_diagnostics(self):
        store = PasswordStore(ACCOUNT)
        store.secret = Mock(COLLECTION_DEFAULT='default')
        store.secret.password_store_sync.side_effect = RuntimeError('fixture-secret backend error')
        with self.assertRaises(CredentialError) as caught:
            store.save('fixture-secret')
        self.assertNotIn('fixture-secret', str(caught.exception))

    def test_cache_is_tried_once_and_rejected_password_is_forgotten(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'attempt'
            env = dict(SYSLOGAPP_SSH_AUTH='password', SYSLOGAPP_SSH_ACCOUNT=json.dumps(ACCOUNT),
                       SYSLOGAPP_SSH_ATTEMPT=str(marker))
            store = Mock()
            store.lookup.return_value = 'fixture-secret'
            with patch.dict(os.environ, env), patch('syslogapp.credentials.PasswordStore', return_value=store):
                backend, cached, warning = ssh_askpass.password_store("alice@example's password: ")
                self.assertEqual(cached, 'fixture-secret')
                self.assertEqual(marker.read_bytes(), b'')
                backend, cached, warning = ssh_askpass.password_store('Password:')
                self.assertIsNone(cached)
                store.forget.assert_called_once()
                store.lookup.assert_called_once()

    def test_only_login_passwords_use_keyring(self):
        with patch.dict(os.environ, {'SYSLOGAPP_SSH_AUTH': 'password'}), \
             patch('syslogapp.credentials.PasswordStore') as store:
            for prompt in ('Verification code:', 'One-time password:', 'Enter passphrase for key:', 'yes/no'):
                self.assertEqual(ssh_askpass.password_store(prompt), (None, None, ''))
            store.assert_not_called()
        with patch.dict(os.environ, {'SYSLOGAPP_SSH_AUTH': 'key'}):
            self.assertEqual(ssh_askpass.password_store('Password:'), (None, None, ''))

    def test_saved_password_goes_only_to_ssh_stdout_without_dialog(self):
        gtk = Mock()
        output = io.StringIO()
        with patch.object(ssh_askpass, 'Gtk', gtk), patch.object(ssh_askpass, 'Gdk', Mock()), \
             patch.object(ssh_askpass, 'password_store', return_value=(Mock(), 'fixture-secret', '')), \
             patch.object(ssh_askpass.sys, 'argv', ['askpass', 'Password:']), redirect_stdout(output):
            self.assertEqual(ssh_askpass.main(), 0)
        self.assertEqual(output.getvalue(), 'fixture-secret\n')
        gtk.Dialog.assert_not_called()

    def test_saving_requires_explicit_checkbox_and_cancellation_does_not_save(self):
        for checked, canceled in ((False, False), (True, False), (True, True)):
            gtk, store, output = Mock(), Mock(), io.StringIO()
            gtk.Dialog.return_value.run.return_value = gtk.ResponseType.CANCEL if canceled else gtk.ResponseType.OK
            gtk.Entry.return_value.get_text.return_value = 'fixture-secret'
            gtk.CheckButton.return_value.get_active.return_value = checked
            with patch.object(ssh_askpass, 'Gtk', gtk), patch.object(ssh_askpass, 'Gdk', Mock()), \
                 patch.object(ssh_askpass, 'password_store', return_value=(store, None, '')), \
                 patch.object(ssh_askpass.sys, 'argv', ['askpass', 'Password:']), redirect_stdout(output):
                self.assertEqual(ssh_askpass.main(), int(canceled))
            if checked and not canceled:
                store.save.assert_called_once_with('fixture-secret')
            else:
                store.save.assert_not_called()
            gtk.CheckButton.return_value.set_active.assert_called_once_with(False)
            self.assertEqual(output.getvalue(), '' if canceled else 'fixture-secret\n')

    def test_keyring_save_failure_keeps_prompt_open_and_never_prints_secret_on_cancel(self):
        gtk, store, output = Mock(), Mock(), io.StringIO()
        gtk.Dialog.return_value.run.side_effect = [gtk.ResponseType.OK, gtk.ResponseType.CANCEL]
        gtk.Entry.return_value.get_text.return_value = 'fixture-secret'
        gtk.CheckButton.return_value.get_active.return_value = True
        store.save.side_effect = CredentialError('unavailable')
        with patch.object(ssh_askpass, 'Gtk', gtk), patch.object(ssh_askpass, 'Gdk', Mock()), \
             patch.object(ssh_askpass, 'password_store', return_value=(store, None, '')), \
             patch.object(ssh_askpass.sys, 'argv', ['askpass', 'Password:']), redirect_stdout(output):
            self.assertEqual(ssh_askpass.main(), 1)
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(gtk.Dialog.return_value.run.call_count, 2)
