# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""SSH profiles contain no secrets; passwords use the desktop keyring."""
from gi.repository import Gtk, Pango
from .hosts import host_profile


def edit_host(parent, initial=None):
    dialog = Gtk.Dialog(title='SSH host', transient_for=parent, modal=True)
    dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Save and connect', Gtk.ResponseType.OK)
    dialog.set_default_size(520, -1)
    box = dialog.get_content_area()
    box.set_border_width(12)
    box.set_spacing(8)
    grid = Gtk.Grid(column_spacing=10, row_spacing=8)
    entries = {}
    for row, (key, label, placeholder) in enumerate((('label','Name','Server name'),
            ('hostname','Hostname / IP','server.example or SSH alias'),('username','SSH user','username'))):
        entry = Gtk.Entry()
        entry.set_hexpand(True)
        entry.set_placeholder_text(placeholder)
        entries[key] = entry
        grid.attach(Gtk.Label(label=label, xalign=0),0,row,1,1)
        grid.attach(entry,1,row,1,1)
    port = Gtk.SpinButton.new_with_range(1,65535,1)
    port.set_value(22)
    grid.attach(Gtk.Label(label='Port',xalign=0),0,3,1,1)
    grid.attach(port,1,3,1,1)
    auth = Gtk.ComboBoxText()
    auth.append('key','SSH key / agent')
    auth.append('password','Password')
    auth.set_active_id('key')
    grid.attach(Gtk.Label(label='Authentication',xalign=0),0,4,1,1)
    grid.attach(auth,1,4,1,1)
    key = Gtk.FileChooserButton(title='Choose private SSH key',action=Gtk.FileChooserAction.OPEN)
    grid.attach(Gtk.Label(label='Key file (optional)',xalign=0),0,5,1,1)
    grid.attach(key,1,5,1,1)
    auth.connect('changed',lambda *_:key.set_sensitive(auth.get_active_id()=='key'))
    box.pack_start(grid,False,False,0)
    note = Gtk.Label(label='SSH requests authentication when connecting. Password prompts offer Remember password in the desktop keyring. Key passphrases and sudo passwords are not saved. Unknown host keys require confirmation; changed keys are rejected.',xalign=0)
    note.set_line_wrap(True)
    note.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    note.set_max_width_chars(58)
    box.pack_start(note,False,False,0)
    error = Gtk.Label(xalign=0)
    error.set_line_wrap(True)
    error.set_max_width_chars(58)
    box.pack_start(error,False,False,0)
    active = [True]
    dialog.connect('destroy', lambda *_: active.__setitem__(0, False))
    if initial and initial.get('auth') == 'password':
        forget = Gtk.Button(label='Forget saved password')
        def forget_password(*_):
            from .credentials import PasswordStore
            forget.set_sensitive(False)
            def done(_result, failure):
                if active[0]:
                    error.set_text('Could not forget password: ' + str(failure) if failure else 'Saved password removed from the desktop keyring.')
                    forget.set_sensitive(True)
                return False
            parent.app.run_async(lambda: PasswordStore(initial).forget(), done)
        forget.connect('clicked', forget_password)
        box.pack_start(forget,False,False,0)
    if initial:
        for name, entry in entries.items():
            entry.set_text(initial.get(name,''))
        port.set_value(initial.get('port',22))
        auth.set_active_id(initial.get('auth','key'))
        if initial.get('key_file'):
            key.set_filename(initial['key_file'])
    dialog.show_all()
    result = None
    while dialog.run() == Gtk.ResponseType.OK:
        try:
            result=host_profile({**{name:entry.get_text() for name,entry in entries.items()},
                    'port':port.get_value_as_int(),'auth':auth.get_active_id(),
                    'key_file':key.get_filename() or ''})
            break
        except ValueError as exc:
            error.set_text(str(exc))
    dialog.destroy()
    return result


def sudo_password(parent, target):
    dialog=Gtk.Dialog(title='Administrator authentication — '+target,transient_for=parent,modal=True)
    dialog.add_buttons('Cancel',Gtk.ResponseType.CANCEL,'Continue',Gtk.ResponseType.OK)
    box=dialog.get_content_area()
    box.set_border_width(12)
    box.set_spacing(8)
    label=Gtk.Label(label='Remote sudo password for '+target+'\nLeave blank if sudo does not require a password.',xalign=0)
    label.set_line_wrap(True)
    label.set_max_width_chars(60)
    box.add(label)
    entry=Gtk.Entry()
    entry.set_visibility(False)
    entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
    entry.set_activates_default(True)
    box.add(entry)
    dialog.set_default_response(Gtk.ResponseType.OK)
    dialog.show_all()
    response=dialog.run()
    secret=entry.get_text() if response==Gtk.ResponseType.OK else None
    entry.set_text('')
    dialog.destroy()
    return secret
