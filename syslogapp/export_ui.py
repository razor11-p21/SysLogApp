# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Preview-before-save export dialog; no host commands or background polling."""
import math
from datetime import datetime
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
from .exports import render, write_atomic, PREVIEW_CHARS


class ExportDialog(Gtk.Dialog):
    def __init__(self, page, snapshot):
        super().__init__(title='Export logs' if snapshot['kind'] == 'logs' else 'Export connections',
                         transient_for=page.app.window, modal=True, destroy_with_parent=True)
        self.get_style_context().add_class('app-root')
        self.page, self.snapshot = page, snapshot
        self.document = None
        self._busy = self._closed = False
        self._revision = self._page_index = 0
        self.connect('destroy', self._destroyed)
        self.set_default_size(900, 650)
        self.add_button('Cancel', Gtk.ResponseType.CANCEL)
        self.save_button = self.add_button('Save…', Gtk.ResponseType.OK)
        self.save_button.set_sensitive(False)
        box = self.get_content_area()
        box.set_border_width(10)
        box.set_spacing(8)
        note = Gtk.Label(label='Exports use a paused snapshot of loaded entries in the current sort order.\n'
                               'Selected entries include whole rows touched by your text selection.', xalign=0)
        note.set_line_wrap(True)
        note.set_max_width_chars(95)
        note.set_selectable(True)
        box.pack_start(note, False, False, 0)
        row = Gtk.Box(spacing=8)
        self.format = Gtk.ComboBoxText()
        self.format.append('jsonl', 'JSONL · collected raw fields + metadata')
        self.format.append('csv', 'Spreadsheet-safe CSV')
        self.format.set_active_id('jsonl')
        self.scope = Gtk.ComboBoxText()
        self.scope.append('all', f"All filtered loaded entries ({len(snapshot['records'])})")
        if snapshot['selected']:
            self.scope.append('selected', f"Selected entries ({len(snapshot['selected'])})")
        self.scope.set_active_id('selected' if snapshot['selected'] else 'all')
        row.pack_start(self.format, True, True, 0)
        row.pack_start(self.scope, True, True, 0)
        box.pack_start(row, False, False, 0)
        redactions = Gtk.Box(spacing=10)
        self.redactions = {}
        for key, title in (('ips', 'Redact IP addresses'), ('hosts', 'Hostnames'), ('users', 'Usernames')):
            check = Gtk.CheckButton(label=title)
            self.redactions[key] = check
            redactions.pack_start(check, False, False, 0)
        box.pack_start(redactions, False, False, 0)
        custom_box = Gtk.Expander(label='Custom text to redact (one value per line)')
        self.custom = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        custom_scroll = Gtk.ScrolledWindow()
        custom_scroll.set_size_request(-1, 75)
        custom_scroll.add(self.custom)
        custom_box.add(custom_scroll)
        box.pack_start(custom_box, False, False, 0)
        warning = Gtk.Label(label='Redaction is best effort: review every preview page before sharing. Opaque binary fields are omitted when redacting.\n'
                                  'CSV prefixes formula-like cells with an apostrophe; JSONL preserves collected values when redaction is off.', xalign=0)
        warning.set_line_wrap(True)
        warning.set_max_width_chars(95)
        warning.set_selectable(True)
        box.pack_start(warning, False, False, 0)
        toolbar = Gtk.Box(spacing=8)
        self.preview_button = Gtk.Button(label='Preview export')
        self.preview_button.connect('clicked', self._preview)
        toolbar.pack_start(self.preview_button, False, False, 0)
        self.previous = Gtk.Button(label='Previous page')
        self.next = Gtk.Button(label='Next page')
        self.previous.connect('clicked', lambda *_: self._show_page(self._page_index - 1))
        self.next.connect('clicked', lambda *_: self._show_page(self._page_index + 1))
        self.previous.set_sensitive(False)
        self.next.set_sensitive(False)
        toolbar.pack_start(self.previous, False, False, 0)
        toolbar.pack_start(self.next, False, False, 0)
        self.page_label = Gtk.Label(xalign=0)
        toolbar.pack_start(self.page_label, False, False, 0)
        box.pack_start(toolbar, False, False, 0)
        self.status = Gtk.Label(label='Choose options, then Preview export before saving.', xalign=0)
        self.status.set_line_wrap(True)
        self.status.set_selectable(True)
        self.status.set_max_width_chars(95)
        box.pack_start(self.status, False, False, 0)
        self.preview = Gtk.TextView(editable=False, cursor_visible=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.preview.get_style_context().add_class('detail-text')
        self.preview.set_left_margin(8)
        self.preview.set_right_margin(8)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(160)
        scroll.add(self.preview)
        box.pack_start(scroll, True, True, 0)
        self.format.connect('changed', self._invalidate)
        self.scope.connect('changed', self._invalidate)
        for check in self.redactions.values():
            check.connect('toggled', self._invalidate)
        self.custom.get_buffer().connect('changed', self._invalidate)

    def _destroyed(self, *_):
        self._closed = True
        self._revision += 1
        self.document = None

    def _invalidate(self, *_):
        self._revision += 1
        self.document = None
        self.save_button.set_sensitive(False)
        self.previous.set_sensitive(False)
        self.next.set_sensitive(False)
        self.preview.get_buffer().set_text('')
        self.page_label.set_text('')
        self.status.set_text('Options changed · Preview export again before saving.')

    def _preview(self, *_):
        if self._busy or self._closed:
            return
        selected = self.scope.get_active_id() == 'selected'
        records = ([self.snapshot['records'][i] for i in self.snapshot['selected']] if selected
                   else self.snapshot['records'])
        meta = dict(self.snapshot['metadata'])
        meta['selection'] = 'selected entries' if selected else 'all filtered loaded entries'
        meta['exported_at'] = datetime.now().astimezone().isoformat(timespec='seconds')
        options = {key: check.get_active() for key, check in self.redactions.items()}
        buffer = self.custom.get_buffer()
        options['custom'] = buffer.get_text(*buffer.get_bounds(), True)
        revision, format_name = self._revision, self.format.get_active_id()
        self._busy = True
        self.document = None
        self.save_button.set_sensitive(False)
        self.preview_button.set_sensitive(False)
        self.status.set_text('Preparing preview…')
        def done(document, error):
            if self._closed or self.page._destroyed:
                return
            self._busy = False
            self.preview_button.set_sensitive(True)
            if revision != self._revision:
                self.status.set_text('Options changed · Preview export again before saving.')
                return
            if error:
                self.status.set_text(str(error))
                return
            self.document = document
            self.save_button.set_sensitive(True)
            self.status.set_text(f'{len(records)} entries · {len(document.encode("utf-8")):,} bytes · review before saving')
            self._show_page(0)
        self.page.app.run_async(lambda: render(records, meta, format_name, options,
                                              self.snapshot['hosts'], self.snapshot['users']), done)

    def _show_page(self, index):
        if self.document is None:
            return
        pages = max(1, math.ceil(len(self.document) / PREVIEW_CHARS))
        self._page_index = max(0, min(index, pages - 1))
        start = self._page_index * PREVIEW_CHARS
        self.preview.get_buffer().set_text(self.document[start:start + PREVIEW_CHARS])
        self.page_label.set_text(f'Page {self._page_index + 1} / {pages}')
        self.previous.set_sensitive(self._page_index > 0)
        self.next.set_sensitive(self._page_index + 1 < pages)

    def save(self):
        if self.document is None:
            return False
        format_name = self.format.get_active_id()
        chooser = Gtk.FileChooserDialog(title='Save export', parent=self, action=Gtk.FileChooserAction.SAVE,
                                        buttons=('Cancel', Gtk.ResponseType.CANCEL, 'Save', Gtk.ResponseType.OK))
        chooser.get_style_context().add_class('app-root')
        chooser.set_destroy_with_parent(True)
        chooser.set_do_overwrite_confirmation(True)
        chooser.set_current_name(f"syslogapp-{self.snapshot['kind']}.{format_name}")
        file_filter = Gtk.FileFilter()
        file_filter.set_name(format_name.upper())
        file_filter.add_pattern('*.' + format_name)
        chooser.add_filter(file_filter)
        try:
            path = chooser.get_filename() if chooser.run() == Gtk.ResponseType.OK else None
        finally:
            chooser.destroy()
        if not path or self._closed or self.document is None:
            return False
        try:
            write_atomic(path, self.document)
            self.page.app.window.toast('Export saved', 'ok')
            return True
        except (OSError, ValueError) as exc:
            self.status.set_text(f'Export failed: {exc}')
            return False


def open_export(page):
    from .export_capture import snapshot
    page._hold_for_selection()
    data = snapshot(page)
    if not data['records']:
        page.app.window.toast('No displayed entries to export', 'info')
        return
    dialog = ExportDialog(page, data)
    dialog.show_all()
    try:
        while dialog.run() == Gtk.ResponseType.OK:
            if dialog.save():
                break
    finally:
        dialog.destroy()
