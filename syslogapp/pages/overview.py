# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
from gi.repository import Gtk, Gdk, Pango, GLib
from ..overview import snapshot
from ..widgets import WrappingToolbar, action_menu, ColumnSizing, TableTextAccess, selectable_readouts
from ..config import column_widths


class OverviewPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.app = app
        self.host = getattr(app, "host", None)
        self._busy = self._loaded_once = self._destroyed = False
        self._text = ''
        self.set_border_width(8)
        toolbar = WrappingToolbar()
        toolbar.get_style_context().add_class('toolbar-card')
        self.refresh_btn = Gtk.Button(label='Refresh')
        self.refresh_btn.connect('clicked', self._refresh_clicked)
        toolbar.add(self.refresh_btn)
        copy = Gtk.Button(label='Copy snapshot')
        copy.connect('clicked', lambda *_: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self._text, -1))
        toolbar.add(copy)
        self.pack_start(toolbar, False, False, 0)
        self.status = Gtk.Label(label='Snapshot on opening · manual refresh · no background sampling', xalign=0)
        self.status.set_line_wrap(True)
        self.status.set_max_width_chars(1)
        self.status.get_style_context().add_class('muted')
        self.pack_start(self.status, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.store = Gtk.ListStore(str, str, str)
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.set_enable_search(False)
        self.columns, self.renderers = [], []
        for index, title in enumerate(('Field', 'Value')):
            renderer = Gtk.CellRendererText()
            renderer.set_property('wrap-mode', Pango.WrapMode.WORD_CHAR)
            renderer.set_property('wrap-width', 160)
            renderer.set_property('yalign', 0.0)
            renderer.set_property('ypad', 3)
            column = Gtk.TreeViewColumn(title, renderer, text=index)
            column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            column.set_min_width(60)
            column.set_fixed_width(160)
            if index == 1:
                column.add_attribute(renderer, 'foreground', 2)
            else:
                renderer.set_property('foreground', '#91d89d')
            self.tree.append_column(column)
            self.columns.append(column)
            self.renderers.append(renderer)
        self._reflow_source = 0
        self.column_sizing = ColumnSizing(self.columns, self.renderers, self._schedule_reflow,
                                          column_widths(getattr(app, 'config', {}), 'overview'))
        self.table_scroll = Gtk.ScrolledWindow()
        self.table_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.table_scroll.add(self.tree)
        self.table_scroll.connect('size-allocate', self._resize_columns)
        toolbar.add(action_menu([('Fit columns', self._fit_columns)]))
        self.fetch_pane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.logo = Gtk.Label(xalign=0, yalign=0)
        self.logo.set_selectable(True)
        self.logo.get_style_context().add_class('fetch-logo')
        self.fetch_pane.pack1(self.logo, resize=False, shrink=True)
        self.fetch_pane.pack2(self.table_scroll, resize=True, shrink=True)
        self.fetch_pane.set_position(150)
        scroll.add(self.fetch_pane)
        self.pack_start(scroll, True, True, 0)
        self.text_access = TableTextAccess(
            self.tree, {column: i for i, column in enumerate(self.columns)})
        self.table_scroll.set_margin_bottom(12)
        selectable_readouts(self)
        self.connect('map', self._mapped)
        self.connect('destroy', self._destroy)

    def _mapped(self, *_):
        if not self._loaded_once:
            self._loaded_once = True
            self._refresh_clicked()

    def _destroy(self, *_):
        self._destroyed = True
        self.column_sizing.cancel_pending()
        if self._reflow_source:
            GLib.source_remove(self._reflow_source)
            self._reflow_source = 0

    def _resize_columns(self, _, allocation):
        width = max(180, allocation.width - 12)
        label = min(180, max(90, width // 3))
        self.column_sizing.apply_deferred([label, max(90, width - label)])

    def _fit_columns(self, *_):
        self.column_sizing.reset()
        self._resize_columns(self.table_scroll, self.table_scroll.get_allocation())

    def _schedule_reflow(self):
        if self._destroyed:
            return
        if self._reflow_source:
            GLib.source_remove(self._reflow_source)
        self._reflow_source = GLib.timeout_add(100, self._reflow)

    def _reflow(self):
        self._reflow_source = 0
        if not self._destroyed:
            for row in self.store:
                self.store.row_changed(row.path, row.iter)
        return False

    def _refresh_clicked(self, *_):
        if self._busy or self._destroyed:
            return
        self._busy = True
        self.refresh_btn.set_sensitive(False)
        if not self._text:
            self.status.set_text('Reading snapshot…')
        self.app.run_async(self.host.overview if self.host else snapshot, self._done)

    def _done(self, result, error):
        if self._destroyed:
            return False
        self._busy = False
        self.refresh_btn.set_sensitive(True)
        if error:
            self.status.set_text(f'Could not read snapshot: {error}')
            return False
        self.store.clear()
        system = next((value for name, value, _ in result['rows'] if name == 'System'), '')
        if 'mint' in system.lower():
            art = "   __________\n  /  ______  |\n |  |  LM  | |\n |  | |  | | |\n |  | |__| | |\n |  |______| |\n  \\_________/\n\n  Linux Mint"
        else:
            art = "    .--.\n   |o_o |\n   |:_/ |\n  //   \\ \\\n (|     | )\n  /'---'\\\n  '-----'\n\n    Linux"
        self.logo.set_text(art)
        for row in result['rows']:
            self.store.append(row)
        self._schedule_reflow()
        self._text = art + '\n\n' + '\n'.join(f'{name}: {value}' for name, value, _ in result['rows'])
        self.status.set_text(f"Snapshot: {result['time']} · manual refresh · load is not CPU percent")
        return False
