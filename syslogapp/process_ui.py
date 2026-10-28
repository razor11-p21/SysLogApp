# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Static, selectable process and service readouts, loaded only on request."""
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk
from .process_details import owners, collect, related_logs


class ProcessDialog(Gtk.Dialog):
    def __init__(self, page, values, show_logs=False):
        super().__init__(title='Connection details', transient_for=page.app.window,
                         modal=True, destroy_with_parent=True)
        self.get_style_context().add_class('app-root')
        self.page, self.values, self.host = page, tuple(values), page.host
        self._closed = self._busy = self._logs_busy = False
        self._token = 0
        self.details = None
        self._logs_loaded = False
        self._want_logs = show_logs
        self.connect('destroy', self._destroyed)
        self.set_default_size(800, 570)
        self.add_button('Close', Gtk.ResponseType.CLOSE)
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(10)
        host = getattr(self.host, 'target', None) or 'Local host'
        def endpoint(address, port):
            return f'[{address}]:{port}' if ':' in address else f'{address}:{port}'
        self.heading = Gtk.Label(label=f'{host}\n{values[0]} · {endpoint(values[2], values[3])} → {endpoint(values[4], values[5])}', xalign=0)
        self.heading.set_line_wrap(True)
        self.heading.set_max_width_chars(80)
        self.heading.set_selectable(True)
        box.pack_start(self.heading, False, False, 0)
        toolbar = Gtk.Box(spacing=8)
        self.owner = Gtk.ComboBoxText()
        for pid, fd in owners(values):
            self.owner.append_text(f'PID {pid} · descriptor {fd}')
        self.owner.set_active(0)
        self.owner.connect('changed', self._owner_changed)
        toolbar.pack_start(self.owner, False, False, 0)
        refresh = Gtk.Button(label='Refresh details')
        refresh.connect('clicked', self._owner_changed)
        toolbar.pack_start(refresh, False, False, 0)
        copy = Gtk.Button(label='Copy shown text')
        copy.connect('clicked', self._copy)
        toolbar.pack_start(copy, False, False, 0)
        box.pack_start(toolbar, False, False, 0)
        self.status = Gtk.Label(label='Read on demand · no automatic refresh', xalign=0)
        self.status.set_line_wrap(True)
        self.status.set_max_width_chars(80)
        self.status.set_selectable(True)
        box.pack_start(self.status, False, False, 0)
        self.notebook = Gtk.Notebook()
        self.views = []
        for title in ('Process details', 'Service logs'):
            view = Gtk.TextView(editable=False, cursor_visible=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
            view.get_style_context().add_class('detail-text')
            view.set_left_margin(10)
            view.set_right_margin(10)
            view.set_bottom_margin(16)
            scroll = Gtk.ScrolledWindow()
            scroll.add(view)
            self.notebook.append_page(scroll, Gtk.Label(label=title))
            self.views.append(view)
        self.views[1].get_buffer().set_text('Open this tab to read related service logs.')
        self.notebook.connect('switch-page', self._switch_page)
        box.pack_start(self.notebook, True, True, 0)

    def _destroyed(self, *_):
        self._closed = True
        self._token += 1

    def start(self):
        self._owner_changed()
        if self._want_logs:
            self.notebook.set_current_page(1)

    def _owner_changed(self, *_):
        self._token += 1
        self.details = None
        self._logs_loaded = self._logs_busy = False
        self.views[0].get_buffer().set_text('Reading and verifying the connection owner…')
        self.views[1].get_buffer().set_text('Resolve the connection owner before reading service logs.')
        self.status.set_text('Reading process details…')
        self._inspect()

    def _inspect(self):
        if self._closed or self.page._destroyed or self._busy:
            return
        selected = self.owner.get_active()
        choices = owners(self.values)
        if not 0 <= selected < len(choices):
            return
        self._busy = True
        token, owner = self._token, choices[selected]
        def done(result, error):
            if self._closed or self.page._destroyed:
                return
            self._busy = False
            if token != self._token:
                self._inspect()
                return
            if error:
                self.views[0].get_buffer().set_text(str(error))
                self.views[1].get_buffer().set_text('Service logs unavailable: the connection owner could not be verified.')
                self.status.set_text('Inspection unavailable · refresh Network if the connection has changed')
                return
            self.details = result
            self._show_details(result)
            if self.notebook.get_current_page() == 1 or self._want_logs:
                self._read_logs()
        self.page.app.run_async(lambda: collect(self.values, owner, self.host), done)

    def _show_details(self, data):
        buffer = self.views[0].get_buffer()
        buffer.set_text('')
        key_tag = buffer.get_tag_table().lookup('key') or buffer.create_tag('key', foreground='#96a79a')
        value_tag = buffer.get_tag_table().lookup('value') or buffer.create_tag('value', foreground='#6aa8ff')
        fields = [('Process', data['name']), ('PID', data['pid']), ('Parent PID', data['parent']),
                  ('UID', data.get('uid') or 'Unavailable'), ('State', data['state']),
                  ('Executable', data['exe']), ('Working directory', data['cwd']),
                  ('Command', data['command'] or '(empty)'), ('Resident memory', data['rss']),
                  ('Systemd unit', data.get('unit') or 'No associated unit'),
                  ('Unit scope', ('User' if data.get('user_unit') else 'System') if data.get('unit') else 'Unavailable'),
                  ('Checked', data['time'])]
        for label, value in fields:
            buffer.insert_with_tags(buffer.get_end_iter(), label + ': ', key_tag)
            buffer.insert_with_tags(buffer.get_end_iter(), str(value) + '\n', value_tag)
        if data.get('warnings'):
            buffer.insert(buffer.get_end_iter(), '\n' + '\n'.join(data['warnings']))
        self.status.set_text('Connection owner verified · snapshot ' + data['time'] + ' · no automatic refresh')

    def _switch_page(self, _notebook, _child, index):
        if index == 1:
            self._want_logs = True
            self._read_logs()

    def _read_logs(self):
        if self._closed or self.page._destroyed or self._logs_busy or self._logs_loaded or not self.details:
            return
        if not self.details.get('unit'):
            self.views[1].get_buffer().set_text('No associated systemd service or scope was found for this process.')
            return
        self._logs_busy = True
        token, details = self._token, self.details
        self.views[1].get_buffer().set_text('Reading related service logs…')
        def done(rows, error):
            if self._closed or self.page._destroyed or token != self._token:
                return
            self._logs_busy = False
            buffer = self.views[1].get_buffer()
            if error:
                buffer.set_text(str(error))
                return
            self._logs_loaded = True
            buffer.set_text(f"{details['unit']} · {len(rows)} recent entries from this process’s boot\n\n")
            from .pages.logs import SEVERITY_COLORS
            for row in rows:
                name = 'priority-' + str(row['priority'])
                tag = buffer.get_tag_table().lookup(name) or buffer.create_tag(name, foreground=SEVERITY_COLORS.get(row['priority'], '#c6d4c9'))
                text = f"{row['time']}  {row['level']}  {row['raw'].get('MESSAGE', row['message'])}\n"
                buffer.insert_with_tags(buffer.get_end_iter(), text, tag)
            if not rows:
                buffer.insert(buffer.get_end_iter(), 'No journal entries visible for this unit. Journal access depends on permissions.')
            if getattr(rows, 'omitted', 0):
                buffer.insert(buffer.get_end_iter(), f'\n{rows.omitted} entries omitted by journal byte limits.')
        self.page.app.run_async(lambda: related_logs(details, self.host), done)

    def _copy(self, *_):
        view = self.views[max(0, self.notebook.get_current_page())]
        buffer = view.get_buffer()
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(buffer.get_text(*buffer.get_bounds(), True), -1)
