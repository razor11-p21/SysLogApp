# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Optional desktop Secret Service storage; never falls back to files."""
import threading


class CredentialError(RuntimeError):
    pass


class PasswordStore:
    def __init__(self, account):
        self.account = {key: str(account[key]) for key in ('hostname', 'username', 'port')}
        self.account['hostname'] = self.account['hostname'].lower()
        try:
            import gi
            gi.require_version('Secret', '1')
            from gi.repository import Secret, Gio
        except (ImportError, ValueError):
            raise CredentialError('Install gir1.2-secret-1 and a desktop password keyring to remember SSH passwords.') from None
        self.secret, self.gio = Secret, Gio
        self.schema = Secret.Schema.new('org.syslogapp.SSH', Secret.SchemaFlags.NONE,
                                         {key: Secret.SchemaAttributeType.STRING for key in self.account})

    def _call(self, function, *args):
        cancel = self.gio.Cancellable()
        timer = threading.Timer(30, cancel.cancel)
        timer.daemon = True
        timer.start()
        try:
            return function(self.schema, self.account, *args, cancel)
        except Exception:
            # Backend diagnostics must never include secret values in UI/logs.
            raise CredentialError('The desktop keyring is unavailable or locked. Unlock it and try again.') from None
        finally:
            timer.cancel()

    def lookup(self):
        return self._call(self.secret.password_lookup_sync)

    def save(self, password):
        label = 'SysLogApp SSH: {username}@{hostname}:{port}'.format(**self.account)
        if not self._call(self.secret.password_store_sync, self.secret.COLLECTION_DEFAULT, label, password):
            raise CredentialError('The desktop keyring could not save the password.')

    def forget(self):
        self._call(self.secret.password_clear_sync)
