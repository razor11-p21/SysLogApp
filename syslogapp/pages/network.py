# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
from collections import Counter
import socket
import time

from gi.repository import Gtk, Gdk, Pango, GLib
from ..widgets import WrappingToolbar, set_cell_style, CommandBar, action_menu, ColumnSizing, TableTextAccess, selectable_readouts
from ..config import column_widths
from ..network import snapshot, host_lan_ip
from ..network_filters import ConnectionFilter
from ..sorting import network_field_key, network_display_row, compare


# Shared terminal palette: colors describe state, not a claim of health.
BLUE = '#6aa8ff'
AMBER = '#ffb34c'
RED = '#ff8188'
GRAY = '#9aa8b7'
PURPLE = '#b69cff'
STATE_COLORS = {'ESTAB': BLUE, 'LISTEN': PURPLE, 'UNCONN': GRAY,
                'SYN-SENT': PURPLE, 'SYN-RECV': PURPLE, 'TIME-WAIT': GRAY,
                'FIN-WAIT-1': GRAY, 'FIN-WAIT-2': GRAY, 'CLOSE-WAIT': AMBER,
                'LAST-ACK': GRAY, 'CLOSING': GRAY, 'CLOSE': GRAY}
STATE_TEXT_COLORS = {'ESTAB': '#c6d4c9', 'LISTEN': '#c2afff',
                     'SYN-SENT': '#c2afff', 'SYN-RECV': '#c2afff', 'CLOSE-WAIT': '#f6bd67'}


class NetworkPage(Gtk.Box):
    SAVED_PAGE = 'network'
    LIVE_SECONDS = 2
    DETAILS_SECONDS = 30
    HEADERS = ('Proto', 'State', 'Local address', 'Local port', 'Remote address', 'Remote port', 'PID', 'Process')
    DISPLAY_ORDER = (0, 1, 2, 3, 4, 5, 7, 6)
    SORT_FIELDS = {column: (column,) + tuple(index for index in (1, 0, 2, 3, 4, 5, 6, 7)
                                            if index != column) for column in range(8)}
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.app = app
        self.host = getattr(app, "host", None)
        self.set_border_width(8)
        self._busy = False
        self._destroyed = False
        self._loaded_once = False
        self._rows = []
        self._column_chars = [max(map(len, header.split())) for header in self.HEADERS]
        self._display_signature = ()
        self._snapshot = None
        self._details_updated = 0
        self._reflow_source = 0
        self._live_source = 0
        self._generation = 0
        self._failures = 0
        self._last_error = None
        self._socket_success_time = None
        self._socket_error = None
        self._socket_processes = False
        self._socket_limited = False
        self._layout_key = None
        self._has_fitted_snapshot = False
        self.command_bar = CommandBar()
        toolbar = self.command_bar.primary
        self.live = Gtk.ToggleButton(label='Live')
        self.live.set_active(True)
        self.live.get_style_context().add_class('active-live')
        self.live.set_image(Gtk.Image.new_from_icon_name('media-playback-start-symbolic', Gtk.IconSize.BUTTON))
        self.live.set_always_show_image(True)
        self.live.connect('toggled', self._on_live)
        toolbar.add(self.live)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text('Search loaded sockets…')
        self.search.connect('search-changed', lambda *_: self._filter())
        self.search.set_hexpand(True)
        self.search.set_width_chars(12)
        self.command_bar.secondary.pack_start(self.search, True, True, 0)
        self.kind = Gtk.ComboBoxText()
        for label in ('All sockets', 'Connections', 'Listening / unconnected'):
            self.kind.append_text(label)
        self.kind.set_active(1)
        self.kind.connect('changed', lambda *_: self._filter())
        toolbar.add(self.kind)
        self.hide_time_wait = Gtk.CheckButton(label='Hide TIME-WAIT')
        self.hide_time_wait.connect('toggled', lambda *_: self._filter())
        toolbar.add(self.hide_time_wait)
        # Keep the selected host identity at the right edge of the Live row.
        identity = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        hostname = (getattr(self.host, 'hostname', None) or getattr(self.host, 'profile', {}).get('hostname') or 'Remote host') if self.host else socket.gethostname()
        self.host_name_label = Gtk.Label(xalign=1)
        self.host_name_label.set_markup(f'<span foreground="{PURPLE}" weight="bold">{GLib.markup_escape_text(hostname)}</span>')
        self.host_name_label.set_max_width_chars(26)
        self.host_name_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.host_ip_label = Gtk.Label(label='IP: waiting for snapshot', xalign=1)
        self.host_ip_label.set_max_width_chars(26)
        self.host_ip_label.set_ellipsize(Pango.EllipsizeMode.END)
        identity.pack_start(self.host_name_label, False, False, 0)
        identity.pack_start(self.host_ip_label, False, False, 0)
        primary_row = Gtk.Box(spacing=12)
        self.command_bar.remove(toolbar)
        toolbar.set_hexpand(True)
        primary_row.pack_start(toolbar, True, True, 0)
        primary_row.pack_end(identity, False, False, 4)
        self.command_bar.pack_start(primary_row, False, False, 0)
        self.command_bar.reorder_child(primary_row, 0)

        self.process_details = Gtk.ComboBoxText()
        for key, label in (('off', 'Process details: Off'), ('basic', 'Process details: Basic'), ('extended', 'Process details: Extended')):
            self.process_details.append(key, label)
        self.process_details.set_active_id('basic')
        self.process_details.connect('changed', self._process_changed)
        self.command_bar.secondary.pack_start(self.process_details, False, False, 0)
        self.refresh_btn = Gtk.Button.new_from_icon_name('view-refresh-symbolic', Gtk.IconSize.BUTTON)
        self.refresh_btn.connect('clicked', self._refresh_clicked)
        self.command_bar.secondary.pack_start(self.refresh_btn, False, False, 0)
        self.copy = Gtk.MenuItem(label='Copy selected socket')
        self.copy.set_sensitive(False)
        self.copy.connect('activate', self._copy)
        self.more_actions = action_menu([('Process details…', self._inspect_selected), ('Related service logs…', self._related_logs), ('Save view…', self._save_view), ('Saved views & bookmarks…', self._saved_items), ('Export connections…', self._export), ('Fit columns', self._fit_columns)])
        self.more_actions.get_popup().prepend(self.copy)
        self.copy.show()
        self.command_bar.secondary.pack_start(self.more_actions, False, False, 0)
        self.pack_start(self.command_bar, False, False, 0)
        self.connection_filters = Gtk.Expander(label='Connection filters')
        filter_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        filter_bar = WrappingToolbar()
        self.application_filter = Gtk.SearchEntry()
        self.application_filter.set_placeholder_text('Application name')
        self.application_filter.set_max_length(128)
        self.application_filter.set_width_chars(12)
        self.application_filter.connect('search-changed', lambda *_: self._filter())
        self.pid_filter = Gtk.Entry()
        self.pid_filter.set_placeholder_text('PID (exact)')
        self.pid_filter.set_width_chars(8)
        self.pid_filter.set_max_length(10)
        self.port_filter = Gtk.Entry()
        self.port_filter.set_placeholder_text('Port (exact)')
        self.port_filter.set_width_chars(7)
        self.port_filter.set_max_length(5)
        for entry in (self.pid_filter, self.port_filter):
            entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
            entry.connect('changed', lambda *_: self._filter())
        self.port_side = Gtk.ComboBoxText()
        for key, label in (('either', 'Either port'), ('local', 'Local port'), ('remote', 'Remote port')):
            self.port_side.append(key, label)
        self.port_side.set_active_id('either')
        self.port_side.connect('changed', lambda *_: self._filter())
        clear_filters = Gtk.Button(label='Clear fields')
        clear_filters.connect('clicked', self._clear_connection_filters)
        for title, entry in (('App', self.application_filter), ('PID', self.pid_filter), ('Port', self.port_filter)):
            group = Gtk.Box(spacing=4)
            label = Gtk.Label(label=title)
            group.pack_start(label, False, False, 0)
            group.pack_start(entry, True, True, 0)
            entry.get_accessible().set_name(title + ' connection filter')
            filter_bar.add(group)
        for control in (self.port_side, clear_filters):
            filter_bar.add(control)
        filter_box.pack_start(filter_bar, False, False, 0)
        self.filter_notice = Gtk.Label(label='Filters apply to loaded connections; no additional scan.', xalign=0)
        self.filter_notice.set_line_wrap(True)
        self.filter_notice.set_max_width_chars(1)
        self.filter_notice.set_selectable(True)
        self.filter_notice.get_style_context().add_class('muted')
        filter_box.pack_start(self.filter_notice, False, False, 0)
        self.connection_filters.add(filter_box)
        self.pack_start(self.connection_filters, False, False, 0)
        # Interface overview is selectable, wrapped text in a bounded-height viewport.
        self.overview = Gtk.Label(label='Open Network to load a snapshot.', xalign=0, yalign=0)
        self.overview.set_selectable(True)
        self.overview.set_line_wrap(True)
        self.overview.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.overview.set_max_width_chars(1)
        overview_scroll = Gtk.ScrolledWindow()
        overview_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        overview_scroll.set_size_request(-1, 100)
        overview_scroll.add(self.overview)
        self.overview_expander = Gtk.Expander(label='Interfaces & routes')
        self.overview_expander.add(overview_scroll)
        self.pack_start(self.overview_expander, False, False, 0)
        self.store = Gtk.ListStore(*([str] * 9))
        for column in range(8):
            self.store.set_sort_func(column, self._compare_rows, column)
        self.store.set_sort_column_id(1, Gtk.SortType.ASCENDING)
        self.tree = Gtk.TreeView(model=self.store)
        # Column widths settle separately; only newly exposed areas need to
        # repaint during viewport resizing. Content changes still invalidate rows.
        self.tree.set_redraw_on_allocate(False)
        self.tree.set_enable_search(False)
        self.tree.get_style_context().add_class('network-table')
        self.tree.set_fixed_height_mode(False)
        self.tree.get_selection().connect('changed', self._selected)
        self.columns = []
        self.renderers = []
        for i, label in enumerate(self.HEADERS):
            renderer = Gtk.CellRendererText()
            renderer.set_property('yalign', 0.0)
            renderer.set_property('ypad', 0)
            renderer.set_property('xpad', 5)
            renderer.set_property('wrap-mode', Pango.WrapMode.WORD_CHAR)
            renderer.set_property('wrap-width', 160)
            renderer.set_property('xalign', 0.0)
            renderer.set_property('alignment', Pango.Alignment.LEFT)
            col = Gtk.TreeViewColumn(label, renderer, text=i)
            col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            col.set_fixed_width(160)
            header = Gtk.Label(label=label.replace(' ', '\n'), xalign=0.0)
            header.set_justify(Gtk.Justification.LEFT)
            col.set_widget(header)
            header.show()
            col.set_alignment(0.0)
            col.set_sort_column_id(i)
            col.set_cell_data_func(renderer, self._state_cell, i)
            self.tree.append_column(col)
            col.set_visible(i < 6)
            self.columns.append(col)
            self.renderers.append(renderer)
        previous = None
        for index in self.DISPLAY_ORDER:
            self.tree.move_column_after(self.columns[index], previous)
            previous = self.columns[index]
        # Absorb spare viewport space after the data instead of stretching a port.
        self.end_space = Gtk.TreeViewColumn('')
        self.end_space.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        self.end_space.set_fixed_width(16)
        self.end_space.set_min_width(16)
        self.end_space.set_expand(True)
        self.tree.append_column(self.end_space)
        self.column_sizing = ColumnSizing(self.columns, self.renderers, self._schedule_reflow,
                                          column_widths(getattr(app, 'config', {}), 'network'))
        scroll = Gtk.ScrolledWindow()
        self.socket_scroll = scroll
        scroll.set_overlay_scrolling(False)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.connect('size-allocate', self._resize)
        scroll.add(self.tree)
        self.pack_start(scroll, True, True, 0)
        selected_actions = Gtk.Box(spacing=6)
        self.inspect_btn = Gtk.Button(label='Process details…')
        self.logs_btn = Gtk.Button(label='Related logs…')
        self.inspect_btn.set_sensitive(False)
        self.logs_btn.set_sensitive(False)
        self.inspect_btn.connect('clicked', self._inspect_selected)
        self.logs_btn.connect('clicked', self._related_logs)
        selected_actions.pack_start(self.inspect_btn, False, False, 0)
        selected_actions.pack_start(self.logs_btn, False, False, 0)
        self.pack_start(selected_actions, False, False, 0)
        self.status = Gtk.Label(label='Not loaded', xalign=0)
        self.status.get_style_context().add_class('muted')
        self.status.set_line_wrap(True)
        self.pack_end(self.status, False, False, 0)
        self.text_access = TableTextAccess(
            self.tree, {self.columns[i]: i for i in self.DISPLAY_ORDER},
            [('Process details…', self._inspect_selected), ('Related service logs…', self._related_logs)],
            on_select=self._hold_for_selection, cell_data=self._state_cell)
        self.socket_scroll.set_margin_bottom(12)
        selectable_readouts(self)
        self.connect('map', self._on_map)
        self.connect('unmap', self._on_unmap)
        self.connect('destroy', self._on_destroy)

    def _hold_for_selection(self):
        if self.live.get_active():
            self.live.set_active(False)

    def _on_map(self, *_):
        if self._live_allowed():
            self.refresh(automatic=True)
        elif not self.live.get_active() and not self._loaded_once:
            self.refresh()
        self._update_status()

    def _on_unmap(self, *_):
        # Discard an in-flight automatic result too, leaving a stable hidden view.
        self._generation += 1
        self._cancel_live_timer()
        if self._snapshot is None:
            self._loaded_once = False

    def _cancel_live_timer(self):
        if self._live_source:
            GLib.source_remove(self._live_source)
            self._live_source = 0

    def stop_live(self):
        self._generation += 1
        self._cancel_live_timer()

    def _on_destroy(self, *_):
        self._destroyed = True
        self.text_access._destroy()
        self.column_sizing.dispose()
        self.stop_live()
        if self._reflow_source:
            GLib.source_remove(self._reflow_source)
            self._reflow_source = 0

    def _live_allowed(self):
        return (not self._destroyed and self.live.get_active()
                and self.get_mapped())

    def _on_live(self, button):
        self.stop_live()
        active = button.get_active()
        button.set_label('Live' if active else 'Paused')
        button.set_image(Gtk.Image.new_from_icon_name('media-playback-start-symbolic' if active else 'media-playback-pause-symbolic', Gtk.IconSize.BUTTON))
        ctx = button.get_style_context()
        (ctx.add_class if active else ctx.remove_class)('active-live')
        (ctx.remove_class if active else ctx.add_class)('paused-live')
        if self._live_allowed():
            self.refresh(automatic=True)
        self._update_status()

    def toggle_pause(self):
        self.live.set_active(not self.live.get_active())

    def _process_changed(self, *_):
        self._layout_key = None
        if hasattr(self, 'store'):
            self._process_columns()
            self._filter()
            self._layout_key = None
            self._resize(self.socket_scroll, self.socket_scroll.get_allocation())

    def _process_columns(self):
        visible = bool(self._socket_processes and self.process_details.get_active_id() != 'off')
        changed = self.columns[7].get_visible() != visible
        if changed:
            self.columns[6].set_visible(visible)
            self.columns[7].set_visible(visible)
            self._resize(self.socket_scroll, self.socket_scroll.get_allocation())

    def _schedule_live(self, immediate=False):
        self._cancel_live_timer()
        if self._busy or not self._live_allowed():
            return
        if immediate:
            self.refresh(automatic=True)
            return
        # Completion-based scheduling prevents overlapping reads. Back off on failure.
        seconds = min(30, self.LIVE_SECONDS * (2 ** min(self._failures, 4)))
        self._live_source = GLib.timeout_add_seconds(seconds, self._live_tick)

    def _live_tick(self):
        self._live_source = 0
        if self._live_allowed():
            self.refresh(automatic=True)
        return False

    def _compare_rows(self, model, left, right, column):
        # Fetch only the fields needed to decide the order. Most endpoint sorts
        # finish after one pair of GTK reads, without copying nine-column rows.
        for index in self.SORT_FIELDS[column]:
            left_raw = model.get_value(left, 8) if index == 7 else ''
            right_raw = model.get_value(right, 8) if index == 7 else ''
            result = compare(network_field_key(model.get_value(left, index), index, left_raw),
                             network_field_key(model.get_value(right, index), index, right_raw))
            if result:
                return result
        return 0

    def _state_cell(self, _col, cell, model, itr, index):
        state = model.get_value(itr, 1)
        if index in (3, 5):
            color = AMBER
        elif index == 6:
            color = BLUE if model.get_value(itr, index) != '—' else GRAY
        elif index == 7:
            color = PURPLE if model.get_value(itr, index) != '—' else GRAY
        else:
            color = STATE_COLORS.get(state, GRAY) if index in (0, 1) else STATE_TEXT_COLORS.get(state, GRAY)
        set_cell_style(cell, color, Pango.Weight.SEMIBOLD if index in (1, 6) else Pango.Weight.NORMAL)


    @staticmethod
    def _interface_color(item):
        state = item.get('operstate', 'UNKNOWN')
        if state == 'UP':
            return BLUE
        if 'UP' not in item.get('flags', []):
            return GRAY
        return RED if state == 'DOWN' else AMBER if state == 'DORMANT' else GRAY

    @staticmethod
    def _colored_line(text, color):
        return f'<span foreground="{color}">{GLib.markup_escape_text(text)}</span>'

    def _export(self, *_):
        from ..export_ui import open_export
        open_export(self)

    def _related_logs(self, *_):
        self._inspect_selected(show_logs=True)

    def _inspect_selected(self, *_, show_logs=False):
        values = self._selected_key()
        if not values:
            self.app.window.toast('Select a connection first', 'info')
            return
        from ..process_details import owners
        if not owners(values):
            self.app.window.toast('No visible process owner. Choose Basic or Extended and Refresh. Closed connections may have no owner.', 'info')
            return
        self._hold_for_selection()
        from ..process_ui import ProcessDialog
        dialog = ProcessDialog(self, values, show_logs=show_logs)
        dialog.show_all()
        dialog.start()
        try:
            dialog.run()
        finally:
            dialog.destroy()

    def _save_view(self, *_):
        from ..saved_ui import ask_name
        from ..investigations import save_view
        name = ask_name(self, 'Save view')
        if name is None:
            return
        try:
            save_view(self.host, name, {'page': 'network', 'kind': self.kind.get_active(),
                      'search': self.search.get_text(), 'hide_time_wait': self.hide_time_wait.get_active(),
                      'processes': self.process_details.get_active_id(),
                      'application': self.application_filter.get_text(), 'pid': self.pid_filter.get_text(),
                      'port': self.port_filter.get_text(), 'port_side': self.port_side.get_active_id()})
            self.app.window.toast('Network view saved for this host', 'ok')
        except (OSError, ValueError) as exc:
            self.app.window.toast(str(exc), 'error')

    def _saved_items(self, *_):
        from ..saved_ui import SavedDialog
        try:
            dialog = SavedDialog(self)
        except (OSError, ValueError) as exc:
            self.app.window.toast(str(exc), 'error')
            return
        dialog.show_all()
        try:
            dialog.run()
        finally:
            dialog.destroy()

    def _apply_saved_view(self, item):
        from ..investigations import host_identity, view_settings
        if item.get('host') != host_identity(self.host)[0]:
            self.app.window.toast('This view belongs to another host', 'info')
            return
        values = view_settings(item.get('settings', {}))
        if values['page'] != 'network':
            return
        self.live.set_active(False)
        self.kind.set_active(values['kind'])
        self.hide_time_wait.set_active(values['hide_time_wait'])
        self.search.set_text(values['search'])
        self.process_details.set_active_id(values['processes'])
        self.application_filter.set_text(values['application'])
        self.pid_filter.set_text(values['pid'])
        self.port_filter.set_text(values['port'])
        self.port_side.set_active_id(values['port_side'])
        self.connection_filters.set_expanded(bool(values['application'] or values['pid'] or values['port']))
        self._filter()
        self.app.window.toast('View applied · Refresh to update collected process details', 'info')

    def _refresh_clicked(self, *_):
        self.refresh()

    def refresh(self, automatic=False):
        if self._busy or self._destroyed:
            return
        self._cancel_live_timer()
        self._busy = True
        self._loaded_once = True
        if not automatic:
            self.refresh_btn.set_sensitive(False)
        if self._snapshot is None:
            self._update_status()
        # Read GTK values here; the worker never touches GTK widgets.
        processes = self.process_details.get_active_id() != 'off'
        generation = self._generation
        cached = self._snapshot if automatic and time.monotonic() - self._details_updated < self.DETAILS_SECONDS else None
        kwargs = {'host': self.host} if self.host else {}
        if cached is not None:
            kwargs['cached'] = cached
        self.app.run_async(lambda: snapshot(processes, **kwargs),
                           lambda result, error: self._loaded(result, error, generation, automatic))

    def _loaded(self, result, error, generation=None, automatic=False):
        if self._destroyed:
            return False
        self._busy = False
        if not self.refresh_btn.get_sensitive():
            self.refresh_btn.set_sensitive(True)
        if generation is not None and generation != self._generation:
            # A pause/hide invalidates the read. Resume waits for it to finish,
            # then starts a fresh read without overlapping the old worker.
            if not automatic and self.get_mapped() and self._snapshot is None and not self.live.get_active():
                self.refresh()
            else:
                self._schedule_live(immediate=True)
            return False
        if automatic and not self._live_allowed():
            return False
        self._last_error = str(error) if error else None
        if error:
            self._failures += 1
            self._update_status()
            self._schedule_live()
            return False
        self._failures = self._failures + 1 if result['errors'] else 0
        self._snapshot = result
        if result.get('details_refreshed', True):
            self._details_updated = time.monotonic()
        preferred = getattr(self.host, 'profile', {}).get('hostname') if self.host else None
        address = host_lan_ip(result['interfaces'], result['routes'], preferred)
        ip_text = 'IP: ' + (address or 'unavailable')
        if self.host_ip_label.get_text() != ip_text:
            color = BLUE if address else AMBER
            value = GLib.markup_escape_text(address or 'unavailable')
            self.host_ip_label.set_markup(f'IP: <span foreground="{color}" weight="bold">{value}</span>')
        if result['sockets'] is not None:
            # Empty is a successful read; None means collection failed. Keep the
            # previous socket rows and their metadata together on partial failure.
            self._rows = result['sockets']
            self._socket_success_time = result['time']
            self._socket_processes = result['processes']
            self._socket_limited = result['limited']
            self._socket_error = None
            self._remote_stale = False
            if self.host and hasattr(self.app.window, 'remote_fresh'):
                self.app.window.remote_fresh('network', self.host)
        else:
            self._socket_error = next((message for message in result['errors']
                                       if message.startswith('Sockets:')), 'Socket data unavailable')
        lines = []
        count = len(result['interfaces']) if result['interfaces'] is not None else 'unavailable'
        title = f'Interfaces & routes ({count})'
        if self.overview_expander.get_label() != title:
            self.overview_expander.set_label(title)
        if result['interfaces'] is None:
            lines.append(self._colored_line("Interfaces: couldn't check", RED))
        else:
            for item in result['interfaces']:
                addresses = ', '.join(f"{addr.get('local', '?')}/{addr.get('prefixlen', '?')}"
                                      for addr in item.get('addr_info', [])) or 'no address'
                flags = item.get('flags', [])
                state = item.get('operstate', 'UNKNOWN')
                # UNKNOWN is common on tunnels/loopback; don't call it disconnected.
                admin = 'up' if 'UP' in flags else 'down'
                lines.append(self._colored_line(
                    f"{item.get('ifname', '?')}  {state} (admin {admin})  {addresses}", self._interface_color(item)))
        for route in result['routes']:
            lines.append(self._colored_line(f"default via {route.get('gateway', 'direct')} dev {route.get('dev', '?')}", BLUE))
        markup = '\n'.join(lines) or 'No interfaces reported'
        if markup != self.overview.get_label():
            self.overview.set_markup(markup)
        self._process_columns()
        self._filter()
        self._schedule_live()
        return False

    def _connection_filter_values(self):
        return dict(application=self.application_filter.get_text(), pid=self.pid_filter.get_text(),
                    port=self.port_filter.get_text(), side=self.port_side.get_active_id())

    def _clear_connection_filters(self, *_):
        self.application_filter.set_text('')
        self.pid_filter.set_text('')
        self.port_filter.set_text('')
        self.port_side.set_active_id('either')
        self._filter()

    def _update_filter_notice(self, filters):
        self.connection_filters.set_label('Connection filters' + (f' · {filters.count} active' if filters.count else ''))
        missing = filters.needs_owners and not self._socket_processes
        text = filters.error or ('App/PID filters need collected owner data. Choose Basic or Extended and Refresh.' if missing else
                                'App/PID filters use collected owners; visibility depends on host permissions.' if filters.needs_owners else
                                'Filters apply to loaded connections; no additional scan.')
        if self.filter_notice.get_text() != text:
            self.filter_notice.set_text(text)
        context = self.filter_notice.get_style_context()
        (context.add_class if filters.error or missing else context.remove_class)('stale-data')

    def _filter(self):
        if self._destroyed:
            return
        needle = self.search.get_text().strip().lower()
        kind = self.kind.get_active()
        hide_time_wait = self.hide_time_wait.get_active()
        extended = self.process_details.get_active_id() == 'extended'
        filters = ConnectionFilter(**self._connection_filter_values())
        self._update_filter_notice(filters)
        values_to_show = []
        for row in self._rows:
            if hide_time_wait and row['state'] == 'TIME-WAIT':
                continue
            idle = row['state'] in ('LISTEN', 'UNCONN')
            if (kind == 1 and idle) or (kind == 2 and not idle):
                continue
            if not filters.matches(row):
                continue
            values = network_display_row(row, extended=extended)
            if needle and needle not in ' '.join(values).lower():
                continue
            values_to_show.append(values)
        # Socket enumeration order can change without any actual data change.
        # Avoid rebuilding and repainting an unchanged sorted table.
        signature = tuple(sorted(values_to_show))
        if signature != self._display_signature:
            self._column_chars = [max([max(map(len, header.split()))] +
                                      [len(values[index]) for values in values_to_show])
                                  for index, header in enumerate(self.HEADERS)]
            if not self._has_fitted_snapshot:
                self._has_fitted_snapshot = True
                self._layout_key = None
            self._resize(self.socket_scroll, self.socket_scroll.get_allocation())
            selected = self._selected_key()
            adjustment = self.socket_scroll.get_vadjustment()
            scroll = adjustment.get_value()
            # Keep stable GTK rows; a small socket change should not replace
            # and re-sort the whole table. Counts preserve duplicate sockets.
            needed = Counter(values_to_show)
            obsolete = []
            for row in self.store:
                values = tuple(row)
                if needed[values]:
                    needed[values] -= 1
                else:
                    obsolete.append(row.iter)
            # Bulk snapshots sort once after mutation; small changes retain
            # incremental sorting and stable GTK rows.
            column, order = self.store.get_sort_column_id()
            bulk = column is not None and len(obsolete) + sum(needed.values()) > 64
            if bulk:
                self.store.set_sort_column_id(Gtk.TREE_SORTABLE_UNSORTED_SORT_COLUMN_ID, order)
            try:
                # Add replacements before removing expired rows: the view never
                # collapses to zero height between two non-empty snapshots.
                for values in values_to_show:
                    if needed[values]:
                        itr = self.store.append(values)
                        needed[values] -= 1
                        if selected and self._row_identity(values) == self._row_identity(selected):
                            self.tree.get_selection().select_iter(itr)
                for itr in obsolete:
                    self.store.remove(itr)
            finally:
                if bulk:
                    self.store.set_sort_column_id(column, order)
            adjustment.set_value(scroll)
            self._display_signature = signature
        self._update_status()

    def _update_status(self):
        if self._destroyed:
            return
        if self.live.get_active():
            mode = 'LIVE' if self.get_mapped() else 'LIVE · hidden'
        else:
            mode = 'paused'
        failure = self._last_error or self._socket_error
        context = self.status.get_style_context()
        (context.add_class if failure else context.remove_class)('stale-data')
        if self._last_error:
            if self._socket_success_time is not None:
                text = (f"{mode} · Stale connections · last successful update {self._socket_success_time}"
                        f" · {len(self.store)} shown / {len(self._rows)} loaded"
                        f" · Couldn't refresh: {self._last_error}. Previous snapshot retained.")
            else:
                text = f"{mode} · Connections unavailable · no successful socket read · Couldn't refresh: {self._last_error}"
            self.status.set_text(text)
            return
        if not self._snapshot:
            self.status.set_text(f"{mode} · no snapshot loaded" if not self._busy else f"{mode} · reading snapshot…")
            return
        snap = self._snapshot
        if self._socket_error:
            if self._socket_success_time is not None:
                text = (f"{mode} · Stale connections · last successful update {self._socket_success_time}"
                        f" · {len(self.store)} shown / {len(self._rows)} loaded")
            else:
                text = f"{mode} · Connections unavailable · no successful socket read"
        else:
            text = f"{mode} · {len(self.store)} shown / {len(self._rows)} loaded  ·  snapshot {self._socket_success_time}"
        if self._failures and self.live.get_active():
            text += ' · refresh slowed after collection errors'
        text += ' · interfaces/routes ' + snap.get('details_time', snap['time'])
        if snap['limited'] or self._socket_limited:
            text += '  ·  snapshot limited'
        if self._socket_processes:
            text += '  ·  process visibility depends on permissions'
        if snap['errors']:
            text += '  ·  ' + ' | '.join(snap['errors'])
        elif self._socket_error:
            text += ' · ' + self._socket_error
        self.status.set_text(text)

    @staticmethod
    def _row_identity(values):
        return tuple(values[:6]) + (values[8],)

    def _selected_key(self):
        model, itr = self.tree.get_selection().get_selected()
        return tuple(model[itr]) if itr is not None else None

    def _selected(self, *_):
        if self._destroyed:
            return
        values = self._selected_key()
        self.copy.set_sensitive(values is not None)
        if hasattr(self, 'inspect_btn'):
            from ..process_details import owners
            available = bool(values and owners(values))
            self.inspect_btn.set_sensitive(available)
            self.logs_btn.set_sensitive(available)

    def _copy(self, *_):
        values = self._selected_key()
        if values:
            text = '\t'.join(values[index] for index in self.DISPLAY_ORDER
                             if self.columns[index].get_visible())
            if values[8] and values[8] != values[7]:
                text += '\nSocket details: ' + values[8]
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
            self.app.window.toast('Socket copied')

    def _resize(self, _scroll, allocation):
        # Wait for a real viewport; unallocated GTK widgets start at one pixel.
        if allocation.width <= 1:
            return
        key = (allocation.width, self.columns[7].get_visible())
        if key == self._layout_key:
            return
        self._layout_key = key
        # Keep widths stable between snapshots; fit again only for a changed
        # viewport, process mode, first data, or an explicit Fit columns action.
        # Equal rules for both endpoints: content-fit fields, bounded widths,
        # and a trailing blank area instead of stretching the last port.
        usable = max(500, allocation.width - 12)
        process = self.columns[7].get_visible()
        metrics = self.tree.get_pango_context().get_metrics(None, None)
        char_width = max(metrics.get_approximate_char_width(),
                         metrics.get_approximate_digit_width()) / Pango.SCALE
        desired = [int(count * char_width) + 24 for count in self._column_chars]
        proto = min(64, max(52, desired[0]))
        state = min(96 if usable >= 850 else 76, max(68, desired[1]))
        port = min(72, max(64, desired[3], desired[5]))
        pid = min(100 if usable >= 850 else 60, max(60, desired[6])) if process else 0
        widths = [proto, state, 0, port, 0, port, pid, 0]
        flexible = [2, 4, 7] if process else [2, 4]
        minima = {2: 80, 4: 80, 7: 88}
        caps = {2: 360, 4: 360, 7: 240}
        targets = {index: min(caps[index], max(minima[index], desired[index])) for index in flexible}
        budget = usable - sum(widths) - 16
        if sum(targets.values()) <= budget:
            for index in flexible:
                widths[index] = targets[index]
        else:
            extra = max(0, budget - sum(minima[index] for index in flexible))
            weights = {index: targets[index] - minima[index] for index in flexible}
            total_weight = sum(weights.values()) or 1
            for index in flexible:
                widths[index] = minima[index] + extra * weights[index] // total_weight
        self.column_sizing.apply_deferred(widths)

    def _fit_columns(self, *_):
        self._layout_key = None
        self.column_sizing.reset()
        self._resize(self.socket_scroll, self.socket_scroll.get_allocation())

    def _schedule_reflow(self):
        if self._destroyed:
            return
        if self._reflow_source:
            GLib.source_remove(self._reflow_source)
        self._reflow_source = GLib.timeout_add(50, self._reflow)

    def _reflow(self):
        self._reflow_source = 0
        if self._destroyed:
            return False
        for row in self.store:
            self.store.row_changed(row.path, row.iter)
        return False
