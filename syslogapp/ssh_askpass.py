#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""OpenSSH askpass UI. Secrets go only to SSH's private stdout pipe."""
import os
import json
import re
from pathlib import Path
import sys
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk


def password_store(prompt):
    """Only cache password authentication, never host trust, OTPs or key phrases.

    The private marker contains no secrets and permits one automatic attempt.
    A rejected cached password is removed before asking for a replacement.
    """
    if os.environ.get('SYSLOGAPP_SSH_AUTH') != 'password' or not re.fullmatch(
            r"(?:.+['’]s )?password:\s*", prompt, re.IGNORECASE):
        return None, None, ''
    if __package__:
        from .credentials import PasswordStore, CredentialError
    else:
        from credentials import PasswordStore, CredentialError
    try:
        account = json.loads(os.environ['SYSLOGAPP_SSH_ACCOUNT'])
        marker = Path(os.environ['SYSLOGAPP_SSH_ATTEMPT'])
        store = PasswordStore(account)
        try:
            marker.touch(mode=0o600, exist_ok=False)
        except FileExistsError:
            store.forget()
            return store, None, 'Authentication was requested again. Enter the current password.'
        return store, store.lookup(), ''
    except (CredentialError, KeyError, ValueError, OSError) as error:
        return None, None, str(error) if isinstance(error, CredentialError) else 'Password keyring is unavailable.'


def main():
    if __package__:
        from .styles import TERMINAL
    else:
        from styles import TERMINAL
    settings = Gtk.Settings.get_default()
    if settings:
        settings.set_property('gtk-application-prefer-dark-theme', True)
    provider = Gtk.CssProvider()
    provider.load_from_data(TERMINAL.encode())
    if Gdk.Screen.get_default():
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    prompt = sys.argv[1] if len(sys.argv) > 1 else 'SSH authentication'
    target = os.environ.get('SYSLOGAPP_SSH_TARGET', 'SSH host')
    confirm = 'yes/no' in prompt.lower() or os.environ.get('SSH_ASKPASS_PROMPT') == 'confirm'
    if confirm:
        dialog = Gtk.MessageDialog(modal=True, message_type=Gtk.MessageType.QUESTION,
                    buttons=Gtk.ButtonsType.YES_NO, text='Trust SSH host key?')
        dialog.set_title('SysLogApp SSH — ' + target)
        dialog.format_secondary_text(target + '\n\n' + prompt)
        dialog.set_default_response(Gtk.ResponseType.NO)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            print('yes', flush=True)
            return 0
        return 1
    store, cached, warning = password_store(prompt)
    if cached is not None:
        print(cached, flush=True)
        return 0
    dialog = Gtk.Dialog(title='SysLogApp SSH — ' + target, modal=True)
    dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Authenticate', Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    box = dialog.get_content_area()
    box.set_border_width(14)
    box.set_spacing(10)
    label = Gtk.Label(label=target + '\n\n' + prompt, xalign=0)
    label.set_line_wrap(True)
    label.set_max_width_chars(65)
    box.add(label)
    entry = Gtk.Entry()
    entry.set_visibility(False)
    entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
    entry.set_activates_default(True)
    box.add(entry)
    remember = None
    if store is not None:
        remember = Gtk.CheckButton(label='Remember password in desktop keyring')
        remember.set_active(False)
        box.add(remember)
    if warning:
        note = Gtk.Label(label=warning, xalign=0)
        note.set_line_wrap(True)
        note.set_max_width_chars(65)
        box.add(note)
    else:
        note = Gtk.Label(xalign=0)
        note.set_line_wrap(True)
        note.set_max_width_chars(65)
        box.add(note)
    dialog.show_all()
    entry.grab_focus()
    secret = None
    while dialog.run() == Gtk.ResponseType.OK:
        value = entry.get_text()
        if remember is not None and remember.get_active():
            try:
                store.save(value)
            except Exception:
                note.set_text('Could not save the password. Unlock your desktop keyring and retry, or uncheck Remember password to connect without saving.')
                continue
        secret = value
        break
    entry.set_text('')
    dialog.destroy()
    if secret is None:
        return 1
    print(secret, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
