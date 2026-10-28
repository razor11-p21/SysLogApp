# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
from gi.repository import Gtk, Gdk, Pango, GLib
from ..overview import snapshot, filesystem_value, filesystem_color, size
from ..widgets import WrappingToolbar, action_menu, ColumnSizing, TableTextAccess, selectable_readouts
from ..config import column_widths


class OverviewPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.app = app
        self._subscriptions = []
        self.host = getattr(app, "host", None)
        self._busy = self._loaded_once = self._destroyed = False
        self._text = ''
        self._snapshot = None
        self._service_rows = {}
        self.set_border_width(8)
        toolbar = WrappingToolbar()
        toolbar.get_style_context().add_class('toolbar-card')
        self.refresh_btn = Gtk.Button(label='Refresh')
        self.refresh_btn.connect('clicked', self._refresh_clicked)
        toolbar.add(self.refresh_btn)
        copy = Gtk.Button(label='Copy snapshot')
        copy.connect('clicked', lambda *_: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self._text, -1))
        toolbar.add(copy)
        self.service_logs = Gtk.Button(label='Show service logs')
        self.service_logs.set_sensitive(False)
        self._subscriptions.append((self.service_logs, self.service_logs.connect('clicked', self._show_service_logs)))
        self.show_virtual = Gtk.CheckButton(label='Virtual mounts')
        self.show_virtual.connect('toggled', lambda *_: self._render_snapshot())
        self.include_remote = Gtk.CheckButton(label='Network/FUSE on Refresh')
        self.pack_start(toolbar, False, False, 0)
        self.status = Gtk.Label(label='Open this tab to read a snapshot', xalign=0)
        self.status.set_line_wrap(True)
        self.status.set_max_width_chars(1)
        self.status.get_style_context().add_class('muted')
        self.pack_start(self.status, False, False, 0)
        self.health = Gtk.Label(xalign=0)
        self.health.set_selectable(True)
        self.health.set_line_wrap(True)
        self.health.set_max_width_chars(1)
        self.pack_start(self.health, False, False, 2)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.store = Gtk.ListStore(str, str, str)
        self.tree = Gtk.TreeView(model=self.store)
        # Column widths settle separately; only newly exposed areas need to
        # repaint during viewport resizing. Content changes still invalidate rows.
        self.tree.set_redraw_on_allocate(False)
        self.tree.set_enable_search(False)
        selection = self.tree.get_selection()
        self._subscriptions.append((selection, selection.connect('changed', self._service_selection)))
        self._subscriptions.append((self.tree, self.tree.connect('row-activated', self._show_service_logs)))
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
        self.table_scroll.set_overlay_scrolling(False)
        self.table_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.table_scroll.add(self.tree)
        self._subscriptions.append((self.table_scroll, self.table_scroll.connect('size-allocate', self._resize_columns)))
        self.details = Gtk.Expander(label='System details')
        self.details.set_expanded(False)
        detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        detail_toolbar = WrappingToolbar()
        for control in (self.service_logs, self.show_virtual, self.include_remote):
            detail_toolbar.add(control)
        detail_toolbar.add(action_menu([('Fit columns', self._fit_columns)]))
        detail_box.pack_start(detail_toolbar, False, False, 0)
        self.table_scroll.set_min_content_height(260)
        detail_box.pack_start(self.table_scroll, True, True, 0)
        self.details.add(detail_box)
        self.fetch_pane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.logo = Gtk.Label(xalign=0, yalign=0)
        self.logo.set_selectable(True)
        self.logo.get_style_context().add_class('fetch-logo')
        self.fetch_pane.pack1(self.logo, resize=False, shrink=True)
        self.summary = Gtk.TextView(editable=False, cursor_visible=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.summary.set_size_request(0, -1)
        self.summary.set_hexpand(True)
        self.summary.set_left_margin(8)
        self.summary.set_right_margin(8)
        self.summary.set_top_margin(8)
        self.summary.set_bottom_margin(8)
        self.summary.set_pixels_below_lines(8)
        buffer = self.summary.get_buffer()
        for name, color in (('field', '#91d89d'), ('normal', '#c6d4c9'), ('info', '#6aa8ff'),
                            ('memory', '#b69cff'), ('warning', '#ffb34c')):
            buffer.create_tag(name, foreground=color)
        self.summary_scroll = Gtk.ScrolledWindow()
        self.summary_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.summary_scroll.set_min_content_width(0)
        self.summary_scroll.set_hexpand(True)
        self.summary_scroll.set_overlay_scrolling(False)
        self.summary_scroll.set_min_content_height(240)
        self.summary_scroll.add(self.summary)
        self.fetch_pane.pack2(self.summary_scroll, resize=True, shrink=True)
        self.fetch_pane.set_size_request(0, -1)
        self.fetch_pane.set_position(150)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.pack_start(self.fetch_pane, False, False, 0)
        scope = Gtk.Label(label='Memory figures describe this host, not SysLogApp.', xalign=0)
        scope.set_line_wrap(True)
        scope.set_max_width_chars(1)
        scope.set_selectable(True)
        scope.get_style_context().add_class('muted')
        content.pack_start(scope, False, False, 0)
        memory_note = Gtk.Label(label='RAM used is an estimate: total minus available. Available includes reclaimable memory.\n'
                                     'Swap occupied is stored data, not a current activity rate.', xalign=0)
        memory_note.set_line_wrap(True)
        memory_note.set_max_width_chars(1)
        memory_note.set_selectable(True)
        memory_note.get_style_context().add_class('muted')
        detail_box.pack_start(memory_note, False, False, 0)
        content.pack_start(self.details, True, True, 0)
        scroll.add(content)
        self.pack_start(scroll, True, True, 0)
        self.text_access = TableTextAccess(
            self.tree, {column: i for i, column in enumerate(self.columns)},
            [('Show service logs', self._show_service_logs)])
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
        for owner, handler in self._subscriptions:
            owner.disconnect(handler)
        self._subscriptions.clear()
        self.text_access._destroy()
        self.column_sizing.dispose()
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
        self._reflow_source = GLib.timeout_add(50, self._reflow)

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
        include = getattr(self, 'include_remote', None)
        include = bool(include and include.get_active())
        work = self.host.overview if self.host else snapshot
        self.app.run_async((lambda: work(include_remote=True)) if include else work, self._done)

    def _done(self, result, error):
        if self._destroyed:
            return False
        self._busy = False
        self.refresh_btn.set_sensitive(True)
        if error:
            retained = f" · previous snapshot {self._snapshot['time']} retained" if self._snapshot else ''
            self.status.set_text(f'Could not read snapshot: {error}' + retained)
            return False
        self._remote_stale = False
        if self.host and hasattr(self.app.window, 'remote_fresh'):
            self.app.window.remote_fresh('overview', self.host)
        self._snapshot = result
        self._render_snapshot()
        return False

    def _render_snapshot(self):
        if self._destroyed or not self._snapshot:
            return
        result = self._snapshot
        self._service_rows = {}
        self.store.clear()
        system = next((value for name, value, _ in result['rows'] if name == 'System'), '')
        if 'mint' in system.lower():
            art = "   __________\n  /  ______  |\n |  |  LM  | |\n |  | |  | | |\n |  | |__| | |\n |  |______| |\n  \\_________/\n\n  Linux Mint"
        else:
            art = "    .--.\n   |o_o |\n   |:_/ |\n  //   \\ \\\n (|     | )\n  /'---'\\\n  '-----'\n\n    Linux"
        self.logo.set_text(art)
        self._render_summary(result)
        rows = list(result['rows'])
        failed = result.get('failed_services', {'items': [], 'error': 'not collected'})
        if failed.get('error'):
            rows.append(('Failed services', 'Unavailable: ' + failed['error'], '#ffb34c'))
        else:
            count = len(failed['items'])
            summary = f'{count} failed system services' if count else 'No failed system services reported'
            if failed.get('limited'):
                summary += ' · list limited'
            rows.append(('Failed services', summary, '#ff8188' if count else '#6aa8ff'))
            for item in failed['items']:
                label = 'Service · ' + item['unit']
                self._service_rows[label] = item['unit']
                rows.append((label, f"{item['active']}/{item['sub']} · {item['description']} · select for logs", '#ff8188'))
        filesystems = result.get('filesystems', {'items': [], 'error': 'not collected'})
        if filesystems.get('error'):
            rows.append(('Mounted filesystems', 'Unavailable: ' + filesystems['error'], '#ffb34c'))
        else:
            retained = filesystems['items']
            visible = [item for item in retained if self.show_virtual.get_active() or not item['virtual']]
            summary = f"{len(visible)} shown / {filesystems['total']} mounted"
            if not self.show_virtual.get_active():
                summary += ' · virtual mounts hidden'
            if filesystems.get('limited'):
                summary += ' · list limited to 128 mounts'
            rows.append(('Mounted filesystems', summary, '#ffb34c' if filesystems.get('limited') else '#6aa8ff'))
            for item in visible:
                if item['mount'] != '/':  # Root usage is already in the summary.
                    rows.append(('Mount · ' + item['mount'], filesystem_value(item), filesystem_color(item)))
        for row in rows:
            self.store.append(row)
        self._schedule_reflow()
        self._text = art + '\n\n' + '\n'.join(f'{name}: {value}' for name, value, _ in rows)
        self._text += ('\n\nMemory scope: selected host, not SysLogApp. RAM used is estimated as total minus available. '
                       'Available includes reclaimable memory. Swap occupied is not a current activity rate.')
        prefix = "Stale remote data · " if getattr(self, "_remote_stale", False) else ""
        self.status.set_text(prefix + f"Snapshot: {result['time']} · Refresh to update")
        return False

    def _render_summary(self, result):
        values = {name: (value, color) for name, value, color in result['rows']}
        buffer = self.summary.get_buffer()
        buffer.set_text('')
        root = next((item for item in result.get('filesystems', {}).get('items', ())
                     if item['mount'] == '/'), None)
        for name, title in (('Host', 'Host'), ('System', 'System'), ('Uptime', 'Uptime'),
                            ('CPU', 'CPU'), ('Memory', 'Memory'), ('Root filesystem', 'Disk /')):
            value, color = values.get(name, ('Unavailable', '#ffb34c'))
            if name == 'Memory':
                title = 'RAM'
                memory = result.get('memory')
                if memory and not memory.get('ram_error') and memory.get('available') is not None and memory.get('total'):
                    value = f"{size(memory['available'])} available / {size(memory['total'])} total"
                    color = '#b69cff'
                else:
                    value = value.split(' · ', 1)[0]
            if name == 'Root filesystem' and root and root.get('usage'):
                usage = root['usage']
                value = f"{usage['percent']:.0f}% used · {size(usage['available'])} available"
                color = filesystem_color(root)
            tag = {'#6aa8ff': 'info', '#b69cff': 'memory', '#ffb34c': 'warning'}.get(color, 'normal')
            buffer.insert_with_tags_by_name(buffer.get_end_iter(), title.ljust(8), 'field')
            buffer.insert_with_tags_by_name(buffer.get_end_iter(), str(value) + '\n', tag)

        failed = result.get('failed_services', {})
        notices = []
        if failed.get('error') or not failed:
            notices.append('Service check unavailable')
        elif failed.get('items'):
            notices.append(f"{len(failed['items'])} failed service" + ('s' if len(failed['items']) != 1 else ''))
        else:
            notices.append('No failed services reported')
        if failed.get('limited'):
            notices.append('Service list limited')
        reboot = result.get('reboot', {})
        if reboot.get('state') == 'required':
            notices.append('Reboot requested')
        elif reboot.get('state') == 'unavailable':
            notices.append('Reboot check unavailable')
        filesystems = result.get('filesystems', {})
        full = sum(1 for item in filesystems.get('items', ())
                   if item.get('usage') and item['usage']['percent'] >= 90)
        if filesystems.get('error'):
            notices.append('Filesystem check unavailable')
        elif full:
            notices.append(f'{full} filesystems over 90% used')
        warning = bool(failed.get('error') or not failed or failed.get('items')
                       or failed.get('limited') or reboot.get('state') in ('required', 'unavailable')
                       or filesystems.get('error') or full)
        escaped = GLib.markup_escape_text(' · '.join(notices))
        color = '#ffb34c' if warning else '#96a79a'
        self.health.set_markup(f'<span foreground="{color}">{escaped}</span>')
        self.details.set_label('System details' + (' · review notices' if warning else ''))

    def _service_selection(self, selection):
        model, itr = selection.get_selected()
        unit = self._service_rows.get(model[itr][0]) if itr is not None else None
        self.service_logs.set_sensitive(bool(unit))

    def _show_service_logs(self, *_):
        if self._destroyed:
            return
        model, itr = self.tree.get_selection().get_selected()
        unit = self._service_rows.get(model[itr][0]) if itr is not None else None
        if not unit:
            self.app.window.toast('Select a failed service row to open its logs', 'info')
            return
        window = self.app.window
        if getattr(window, 'active_host', self.host) is not self.host:
            return
        logs = window.pages.get('logs')
        if logs:
            logs.navigate(unit=unit, priority='All', search='', scope='boot')
            window.notebook.set_current_page(0)
