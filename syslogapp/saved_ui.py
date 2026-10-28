# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Saved-view and bookmark dialogs, created only when requested."""
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk
from datetime import datetime
from . import investigations as store
from .services import journal_records, CheckUnavailable


def ask_name(page, title, default=''):
    dialog = Gtk.Dialog(title=title, transient_for=page.app.window, modal=True)
    dialog.get_style_context().add_class('app-root')
    dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Save', Gtk.ResponseType.OK)
    entry = Gtk.Entry()
    entry.set_max_length(80 if title == 'Save view' else 160)
    entry.set_text(default)
    entry.set_activates_default(True)
    entry.set_margin_top(12)
    entry.set_margin_bottom(12)
    entry.set_margin_start(12)
    entry.set_margin_end(12)
    dialog.get_content_area().add(entry)
    dialog.set_default_response(Gtk.ResponseType.OK)
    dialog.show_all()
    try:
        return entry.get_text().strip() if dialog.run() == Gtk.ResponseType.OK else None
    finally:
        dialog.destroy()


def readable_date(value, fallback):
    try:
        return datetime.fromtimestamp(int(value[1:])).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError, OverflowError, OSError):
        return fallback


def saved_event_text(item):
    event = item.get('event', {})
    if not isinstance(event, dict):
        return 'Saved event is unavailable.'
    message = str(event.get('message', ''))
    if event.get('excerpt'):
        message += '\n\n[Saved excerpt: first 8 KiB. Locate event to read the journal entry.]'
    return (f"{item.get('name', '')}\n{item.get('host_label', '')}\n"
            f"{event.get('time', '')} · {event.get('unit', '')} · {event.get('level', '')}\n\n{message}")


def locate_event(item, host):
    event = item.get('event', {})
    if not isinstance(event, dict):
        raise CheckUnavailable('Saved event is unavailable.')
    cursor = event.get('cursor')
    if not cursor:
        raise CheckUnavailable('This bookmark has no journal cursor. Its saved text is still available.')
    records = journal_records(['--cursor', cursor, '--reverse', '-n', '1',
                               '--output-fields=__REALTIME_TIMESTAMP,PRIORITY,_SYSTEMD_UNIT,SYSLOG_IDENTIFIER,_COMM,_PID,MESSAGE'], host=host)
    if getattr(records, 'omitted', 0):
        raise CheckUnavailable('The event exceeds the 64 KiB display limit. Saved excerpt retained.')
    if not records or records[0].get('__CURSOR') != cursor:
        raise CheckUnavailable('The event is no longer available in this journal (it may have rotated). Saved text retained.')
    record = records[0]
    if event.get('boot') and record.get('_BOOT_ID') != event['boot']:
        raise CheckUnavailable('The journal boot does not match this bookmark. Saved text retained.')
    return str(record.get('MESSAGE', ''))


class SavedDialog(Gtk.Dialog):
    def __init__(self, page):
        super().__init__(title='Saved views & bookmarks', transient_for=page.app.window, modal=True)
        self.get_style_context().add_class('app-root')
        self.page = page
        self._closed = False
        self._locating = False
        self.connect('destroy', self._destroyed)
        self.set_default_size(720, 520)
        self.add_button('Close', Gtk.ResponseType.CLOSE)
        content = self.get_content_area()
        content.set_spacing(8)
        content.set_border_width(10)
        key, label = store.host_identity(page.host)
        self.host_key = key
        self.page_kind = getattr(page, 'SAVED_PAGE', 'logs')
        heading = Gtk.Label(label=f'{label} · saved locally on this computer', xalign=0)
        heading.set_line_wrap(True)
        heading.set_selectable(True)
        heading.set_max_width_chars(70)
        content.pack_start(heading, False, False, 0)
        note = Gtk.Label(label='Views restore filters in Paused mode. Saved log date ranges stay fixed.\n'
                               'Bookmarks keep event text locally, even after journal rotation. Saving the same name replaces a view; bookmarking the same event updates it.', xalign=0)
        note.set_line_wrap(True)
        note.set_selectable(True)
        note.set_max_width_chars(70)
        content.pack_start(note, False, False, 0)
        self.notebook = Gtk.Notebook()
        content.pack_start(self.notebook, True, True, 0)
        self.tables = {}
        self.previews = {}
        self.buttons = {}
        for kind, title in (('views', 'Saved views'), ('bookmarks', 'Bookmarks')):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            model = Gtk.ListStore(str, object)
            model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
            tree = Gtk.TreeView(model=model)
            cell = Gtk.CellRendererText()
            tree.append_column(Gtk.TreeViewColumn('Name', cell, text=0))
            scroll = Gtk.ScrolledWindow()
            scroll.set_min_content_height(110)
            scroll.add(tree)
            box.pack_start(scroll, True, True, 0)
            preview = Gtk.TextView(editable=False, cursor_visible=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
            preview_scroll = Gtk.ScrolledWindow()
            preview_scroll.set_min_content_height(130)
            preview_scroll.add(preview)
            box.pack_start(preview_scroll, True, True, 0)
            self.tables[kind] = tree
            self.previews[kind] = preview
            tree.get_selection().connect('changed', self._selected, kind)
            buttons = Gtk.Box(spacing=8)
            self.buttons[kind] = []
            choices = [('Apply view', self._apply)] if kind == 'views' else [
                ('Locate event', self._locate), ('Copy saved event', self._copy)]
            choices.append(('Remove', self._remove))
            for label, callback in choices:
                button = Gtk.Button(label=label)
                button.set_sensitive(False)
                self.buttons[kind].append(button)
                button.connect('clicked', callback, kind)
                buttons.pack_start(button, False, False, 0)
            box.pack_start(buttons, False, False, 0)
            self.notebook.append_page(box, Gtk.Label(label=title))
        try:
            self._reload()
        except (OSError, ValueError):
            self.destroy()
            raise

    def _destroyed(self, *_):
        self._closed = True

    def _reload(self):
        data = store.load()
        for kind, tree in self.tables.items():
            model = tree.get_model()
            model.clear()
            self.previews[kind].get_buffer().set_text('Select a saved item, or save one using the ⋯ menu.')
            for item in data[kind]:
                settings = store.view_settings(item.get('settings', {})) if kind == 'views' else {}
                if item['host'] == self.host_key and (kind != 'views' or settings['page'] == self.page_kind):
                    model.append([store.text(item['name'], 160), item])

    def _item(self, kind):
        model, itr = self.tables[kind].get_selection().get_selected()
        return model[itr][1] if itr is not None else None

    def _selected(self, selection, kind):
        item = self._item(kind)
        for button in self.buttons.get(kind, []):
            button.set_sensitive(bool(item) and not (button.get_label() == 'Locate event' and self._locating))
        if not item:
            return
        if kind == 'bookmarks':
            text = saved_event_text(item)
        else:
            values = store.view_settings(item.get('settings', {}))
            if values['page'] == 'network':
                text = (f"{item['name']}\nSocket view: {('All sockets', 'Connections', 'Listening / unconnected')[values['kind']]}\n"
                        f"Search: {values['search'] or 'Any'}\nHide TIME-WAIT: {values['hide_time_wait']}\n"
                        f"Process details: {values['processes']}")
                self.previews[kind].get_buffer().set_text(text)
                return
            query = values['history']
            text = (f"{item['name']}\nBoot scope: {values['scope']} · Severity: {values['priority']}\n"
                    f"Service: {values['unit'] or 'All'}\nLoaded text: {values['search'] or 'Any'}\n"
                    f"Journal message: {query.get('match') or 'Any'}\n"
                    f"Range (local time): {readable_date(query.get('since'), 'Any')} → {readable_date(query.get('until'), 'Now')}")
        self.previews[kind].get_buffer().set_text(text)

    def _apply(self, _button, kind):
        item = self._item(kind)
        if item:
            self.page._apply_saved_view(item)
            self.response(Gtk.ResponseType.CLOSE)

    def _copy(self, _button, kind):
        item = self._item(kind)
        if item:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(saved_event_text(item), -1)

    def _remove(self, _button, kind):
        item = self._item(kind)
        if item:
            try:
                store.remove(kind, item['id'])
                self._reload()
            except (OSError, ValueError) as exc:
                self.page.app.window.toast(str(exc), 'error')

    def _locate(self, button, kind):
        if self._locating:
            return
        item = self._item(kind)
        if not item:
            return
        self._locating = True
        button.set_sensitive(False)
        def done(message, error):
            self._locating = False
            if self._closed or self.page._destroyed:
                return
            self._selected(None, kind)
            # Never replace a different selection if a remote read completed late.
            current = self._item(kind)
            if not current or current['id'] != item['id']:
                return
            text = saved_event_text(item) + '\n\n'
            text += str(error) if error else 'Journal entry located:\n' + message
            self.previews[kind].get_buffer().set_text(text)
        host = self.page.host
        self.page.app.run_async(lambda: locate_event(item, host), done)
