# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
from collections import deque
from datetime import datetime

from gi.repository import Gtk, GLib, Gdk, Pango

from ..services import network_overview, human_bytes
from ..widgets import MetricCard, SectionCard, StatusPill, ResponsiveColumns, WrappingToolbar


def human_rate(value):
    try:
        value = max(0.0, float(value))
    except Exception:
        value = 0.0
    units = ("B/s", "KB/s", "MB/s", "GB/s")
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit in ("MB/s", "GB/s"):
                return f"{value:.1f} {unit}"
            if unit == "KB/s":
                return f"{value:.0f} {unit}"
            return f"{value:.0f} {unit}"
        value /= 1024.0
    return "0 B/s"


class TrafficGraph(Gtk.DrawingArea):
    """Small dynamic RX/TX traffic graph with an adaptive scale."""

    def __init__(self, max_points=60):
        super().__init__()
        self.rx = deque([0.0] * max_points, maxlen=max_points)
        self.tx = deque([0.0] * max_points, maxlen=max_points)
        self.set_size_request(-1, 180)
        self.connect("draw", self._draw)

    def add_values(self, rx, tx):
        try:
            rx = max(0.0, float(rx))
        except Exception:
            rx = 0.0
        try:
            tx = max(0.0, float(tx))
        except Exception:
            tx = 0.0
        self.rx.append(rx)
        self.tx.append(tx)
        self.queue_draw()

    def _rgba(self, name, fallback):
        found, color = self.get_style_context().lookup_color(name)
        return color if found else fallback

    def _draw_series(self, cr, values, color, x0, y0, width, height, maximum):
        vals = list(values)
        if len(vals) < 2:
            return
        step = width / max(1, len(vals) - 1)
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        cr.set_line_width(2.0)
        for idx, val in enumerate(vals):
            x = x0 + idx * step
            y = y0 + height - min(1.0, val / maximum) * height
            if idx == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()

    def _draw(self, _widget, cr):
        alloc = self.get_allocation()
        width, height = max(1, alloc.width), max(1, alloc.height)
        left, right, top, bottom = 76, 14, 12, 26
        gw = max(1, width - left - right)
        gh = max(1, height - top - bottom)

        grid = self._rgba("graph_grid", Gdk.RGBA(0.45, 0.5, 0.56, 0.3))
        text = self._rgba("graph_text", Gdk.RGBA(0.55, 0.6, 0.66, 1.0))
        rx_color = self._rgba("graph_rx", Gdk.RGBA(0.35, 0.64, 1.0, 1.0))
        tx_color = self._rgba("graph_tx", Gdk.RGBA(0.35, 0.82, 0.52, 1.0))

        maximum = max(max(self.rx, default=0.0), max(self.tx, default=0.0), 1024.0)
        # Add headroom and round to a stable binary-ish scale.
        maximum *= 1.15
        step = 1024.0
        while step < maximum:
            step *= 2.0
        maximum = step

        cr.set_line_width(1)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = top + gh - frac * gh
            cr.set_source_rgba(grid.red, grid.green, grid.blue, grid.alpha)
            cr.move_to(left, y)
            cr.line_to(left + gw, y)
            cr.stroke()
            cr.set_source_rgba(text.red, text.green, text.blue, text.alpha)
            cr.move_to(2, y + 4)
            cr.show_text(human_rate(maximum * frac))

        self._draw_series(cr, self.rx, rx_color, left, top, gw, gh, maximum)
        self._draw_series(cr, self.tx, tx_color, left, top, gw, gh, maximum)
        return False


class NetworkPage(Gtk.ScrolledWindow):
    COL_KEY = 0
    COL_PROTOCOL = 1
    COL_PROCESS = 2
    COL_LOCAL = 3
    COL_REMOTE = 4
    COL_STATE = 5
    COL_PID = 6
    COL_FAMILY = 7
    COL_LISTENING = 8
    COL_SCOPE = 9
    COL_INTERFACE = 10
    COL_USER = 11
    COL_EXE = 12
    COL_LOCAL_IP = 13
    COL_LOCAL_PORT = 14
    COL_REMOTE_IP = 15
    COL_REMOTE_PORT = 16

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.get_style_context().add_class("page-scroll")

        self._timer = None
        self._busy = False
        self._paused = False
        self._refresh_serial = 0
        self._snapshot = None
        self._previous_io = None
        self._rx_rate = 0.0
        self._tx_rate = 0.0
        self._selected_key = None
        self._detail_row = None
        self._column_resize_source = {}
        self._tree_layout = {}

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.set_border_width(22)
        self.add(root)

        root.pack_start(self._build_heading(), False, False, 0)
        root.pack_start(self._build_metrics(), False, False, 0)
        root.pack_start(self._build_traffic(), False, False, 0)
        root.pack_start(self._build_explorer(), True, True, 0)

        self.updated_label = Gtk.Label(label="", xalign=1)
        self.updated_label.get_style_context().add_class("footer-text")
        root.pack_start(self.updated_label, False, False, 0)

        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)
        self.connect("destroy", self._on_destroy)

    def _build_heading(self):
        heading = ResponsiveColumns()
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label="Network", xalign=0)
        title.get_style_context().add_class("page-title")
        subtitle = Gtk.Label(label="Monitor interfaces, traffic, active connections, and listening ports.", xalign=0)
        subtitle.set_line_wrap(True)
        subtitle.set_max_width_chars(55)
        subtitle.get_style_context().add_class("page-subtitle")
        text.pack_start(title, False, False, 0)
        text.pack_start(subtitle, False, False, 0)
        heading.pack_start(text, True, True, 0)

        # Fixed-width controls prevent live state changes from moving the header.
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pause_btn = Gtk.Button(label="Pause")
        self.pause_btn.set_size_request(104, -1)
        self.pause_btn.get_style_context().add_class("secondary-button")
        self.pause_btn.set_image(Gtk.Image.new_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.BUTTON))
        self.pause_btn.set_always_show_image(True)
        self.pause_btn.connect("clicked", self._toggle_pause)
        controls.pack_start(self.pause_btn, False, False, 0)

        self.refresh_btn = Gtk.Button(label="Refresh Now")
        self.refresh_btn.set_size_request(136, -1)
        self.refresh_btn.get_style_context().add_class("secondary-button")
        self.refresh_btn.set_image(Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON))
        self.refresh_btn.set_always_show_image(True)
        self.refresh_btn.connect("clicked", lambda *_: self.refresh(force=True))
        controls.pack_start(self.refresh_btn, False, False, 0)

        self.live_pill = StatusPill("Live • 2s", "ok")
        self.live_pill.set_size_request(112, -1)
        controls.pack_start(self.live_pill, False, False, 0)
        heading.pack_start(controls, False, False, 0)
        return heading

    def _build_metrics(self):
        grid = Gtk.FlowBox()
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_homogeneous(True)
        grid.set_min_children_per_line(1)
        grid.set_max_children_per_line(5)
        grid.set_column_spacing(12)
        grid.set_row_spacing(12)
        self.cards = {
            "interface": MetricCard("Primary Interface", "network-wired-symbolic", "blue"),
            "download": MetricCard("Download", "go-down-symbolic", "blue"),
            "upload": MetricCard("Upload", "go-up-symbolic", "green"),
            "connections": MetricCard("Established", "network-transmit-receive-symbolic", "purple"),
            "listening": MetricCard("Listening", "network-server-symbolic", "orange"),
        }
        for idx, key in enumerate(("interface", "download", "upload", "connections", "listening")):
            grid.add(self.cards[key])
        return grid

    def _build_traffic(self):
        card = SectionCard("Live Traffic", "Receive and transmit rates over the last two minutes.", "network-transmit-receive-symbolic")
        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.rx_legend = Gtk.Label(label="● RX 0 B/s")
        self.rx_legend.get_style_context().add_class("network-rx")
        self.tx_legend = Gtk.Label(label="● TX 0 B/s")
        self.tx_legend.get_style_context().add_class("network-tx")
        legend.pack_start(self.rx_legend, False, False, 0)
        legend.pack_start(self.tx_legend, False, False, 0)
        card.header_extra.pack_start(legend, False, False, 0)
        self.traffic_graph = TrafficGraph(max_points=60)
        card.content.pack_start(self.traffic_graph, True, True, 0)
        return card

    def _build_explorer(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        toolbar.get_style_context().add_class("toolbar-card")
        toolbar.set_border_width(10)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search process, IP address, port, PID, user, or interface…")
        self.search.set_hexpand(True)
        self.search.connect("search-changed", lambda *_: self._render_tables())
        search_row.pack_start(self.search, True, True, 0)
        self.count_label = Gtk.Label(label="Loading…", xalign=1)
        self.count_label.set_size_request(170, -1)
        self.count_label.get_style_context().add_class("muted")
        search_row.pack_end(self.count_label, False, False, 4)
        toolbar.pack_start(search_row, False, False, 0)

        filter_row = WrappingToolbar()
        self.protocol = Gtk.ComboBoxText()
        for value in ("All Protocols", "TCP", "UDP"):
            self.protocol.append_text(value)
        self.protocol.set_active(0)
        self.protocol.connect("changed", lambda *_: self._render_tables())
        filter_row.add(self.protocol)

        self.scope = Gtk.ComboBoxText()
        for value in ("All Scopes", "Local", "LAN", "Internet", "Unknown"):
            self.scope.append_text(value)
        self.scope.set_active(0)
        self.scope.connect("changed", lambda *_: self._render_tables())
        filter_row.add(self.scope)

        self.state = Gtk.ComboBoxText()
        for value in ("All States", "ESTABLISHED", "SYN_SENT", "SYN_RECV", "CLOSE_WAIT", "TIME_WAIT"):
            self.state.append_text(value)
        self.state.set_active(0)
        self.state.connect("changed", lambda *_: self._render_tables())
        filter_row.add(self.state)

        clear_btn = Gtk.Button(label="Clear Filters")
        clear_btn.get_style_context().add_class("secondary-button")
        clear_btn.connect("clicked", self._clear_filters)
        filter_row.add(clear_btn)
        toolbar.pack_start(filter_row, False, False, 0)
        outer.pack_start(toolbar, False, False, 0)

        self.view_stack = Gtk.Stack()
        self.view_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.view_stack.set_transition_duration(120)
        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self.view_stack)
        switcher.set_halign(Gtk.Align.START)
        switcher.get_style_context().add_class("network-switcher")
        outer.pack_start(switcher, False, False, 0)

        self.view_stack.add_titled(self._build_connections_view(), "connections", "Live Connections")
        self.view_stack.add_titled(self._build_listeners_view(), "listeners", "Listening Ports")
        self.view_stack.add_titled(self._build_interfaces_view(), "interfaces", "Interfaces")
        self.view_stack.connect("notify::visible-child-name", self._view_changed)
        outer.pack_start(self.view_stack, True, True, 0)
        return outer

    def _new_connection_store(self):
        return Gtk.ListStore(
            str, str, str, str, str, str, int, str, bool,
            str, str, str, str, str, int, str, int,
        )

    def _build_tree(self, store, listening=False):
        tree = Gtk.TreeView(model=store)
        tree.set_headers_visible(True)
        tree.set_enable_search(False)
        tree.set_grid_lines(Gtk.TreeViewGridLines.HORIZONTAL)
        tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        tree.connect("cursor-changed", self._selection_changed)
        tree.connect("button-press-event", self._tree_button_press, listening)

        specs = [
            ("Process", self.COL_PROCESS, "process"),
            ("Proto", self.COL_PROTOCOL, "proto"),
            ("Local Address", self.COL_LOCAL, "local"),
        ]
        if not listening:
            specs.extend([
                ("Remote Address", self.COL_REMOTE, "remote"),
                ("Scope", self.COL_SCOPE, "scope"),
                ("State", self.COL_STATE, "state"),
            ])
        else:
            specs.append(("Family", self.COL_FAMILY, "family"))
        specs.append(("PID", self.COL_PID, "pid"))

        columns = {}
        for title, model_col, key in specs:
            renderer = Gtk.CellRendererText()
            renderer.set_property("ypad", 6)
            renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
            col = Gtk.TreeViewColumn(title, renderer, text=model_col)
            col.set_resizable(False)
            col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            col.set_min_width(36)
            # Native ListStore sorting keeps the user's sort choice active across
            # live refreshes without us reordering the raw snapshot.
            col.set_sort_column_id(model_col)
            if model_col == self.COL_STATE:
                col.set_cell_data_func(renderer, self._state_cell_data)
            elif model_col == self.COL_SCOPE:
                col.set_cell_data_func(renderer, self._scope_cell_data)
            elif model_col == self.COL_PROCESS:
                col.set_cell_data_func(renderer, self._process_cell_data)
            elif model_col == self.COL_PID:
                col.set_cell_data_func(renderer, self._pid_cell_data)
            tree.append_column(col)
            columns[key] = col

        self._tree_layout[id(tree)] = {
            "tree": tree,
            "columns": columns,
            "listening": listening,
            "last_width": 0,
        }
        return tree

    def _bind_tree_viewport(self, tree, scroll):
        # TreeView natural widths are affected by long IPv6 addresses, so size
        # against the actual viewport instead. Debounce allocations during drag.
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.connect("size-allocate", self._tree_viewport_allocated, tree)
        GLib.idle_add(self._resize_tree_to_viewport, tree, scroll)

    def _tree_viewport_allocated(self, scroll, allocation, tree):
        width = max(1, int(allocation.width))
        layout = self._tree_layout.get(id(tree))
        if not layout or abs(width - layout.get("last_width", 0)) < 3:
            return
        layout["last_width"] = width
        old = self._column_resize_source.pop(id(tree), None)
        if old:
            try:
                GLib.source_remove(old)
            except Exception:
                pass
        self._column_resize_source[id(tree)] = GLib.timeout_add(35, self._resize_tree_to_viewport, tree, scroll)

    def _resize_tree_to_viewport(self, tree, scroll):
        self._column_resize_source.pop(id(tree), None)
        layout = self._tree_layout.get(id(tree))
        if not layout:
            return False
        width = max(1, int(scroll.get_allocated_width()) - 4)
        if width < 120:
            return False
        cols = layout["columns"]

        # Responsive compact columns.  At narrow sizes, process/state/PID give
        # up space first so endpoints stay useful; full values remain in Details.
        if layout["listening"]:
            proto = 58 if width < 760 else 68
            family = 66 if width < 760 else 82
            pid = 48 if width < 760 else 62
            process = max(84, min(165, int(width * 0.20)))
            local = max(90, width - process - proto - family - pid - 8)
            sizes = {"process": process, "proto": proto, "local": local, "family": family, "pid": pid}
        else:
            proto = 54 if width < 820 else 66
            scope = 72 if width < 820 else 86
            state = 78 if width < 820 else 102
            pid = 44 if width < 820 else 58
            process = max(78, min(160, int(width * 0.15)))
            remaining = max(150, width - process - proto - scope - state - pid - 8)
            local = remaining // 2
            remote = remaining - local
            sizes = {
                "process": process, "proto": proto, "local": local,
                "remote": remote, "scope": scope, "state": state, "pid": pid,
            }

        for key, size in sizes.items():
            col = cols.get(key)
            if col is not None:
                col.set_fixed_width(max(36, int(size)))
        tree.queue_resize()
        return False

    def _build_connections_view(self):
        pane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        pane.set_wide_handle(True)
        self.connection_pane = pane
        self._pane_position_initialized = False
        pane.connect("size-allocate", self._connection_pane_allocated)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.connection_store = self._new_connection_store()
        self.connection_tree = self._build_tree(self.connection_store, listening=False)
        scroll = Gtk.ScrolledWindow()
        self.connection_scroll = scroll
        scroll.set_min_content_height(360)
        scroll.add(self.connection_tree)
        self._bind_tree_viewport(self.connection_tree, scroll)
        left.pack_start(scroll, True, True, 0)
        pane.pack1(left, resize=True, shrink=True)

        details = SectionCard("Connection Details", "Select a live socket to inspect it.", "dialog-information-symbolic")
        details.set_size_request(310, -1)
        self.detail = Gtk.TextView()
        self.detail.set_editable(False)
        self.detail.set_cursor_visible(False)
        self.detail.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.detail.get_style_context().add_class("detail-text")
        self.detail.get_buffer().set_text("Select a connection to inspect its endpoints and process information.")
        dscroll = Gtk.ScrolledWindow()
        dscroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        dscroll.set_min_content_height(290)
        dscroll.add(self.detail)
        details.content.pack_start(dscroll, True, True, 0)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        copy_btn = Gtk.Button(label="Copy Details")
        copy_btn.set_image(Gtk.Image.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON))
        copy_btn.set_always_show_image(True)
        copy_btn.connect("clicked", self._copy_details)
        actions.pack_start(copy_btn, False, False, 0)
        self.filter_process_btn = Gtk.Button(label="Filter Process")
        self.filter_process_btn.get_style_context().add_class("secondary-button")
        self.filter_process_btn.set_sensitive(False)
        self.filter_process_btn.connect("clicked", lambda *_: self._filter_detail_process())
        actions.pack_start(self.filter_process_btn, False, False, 0)
        self.filter_remote_btn = Gtk.Button(label="Filter Remote")
        self.filter_remote_btn.get_style_context().add_class("secondary-button")
        self.filter_remote_btn.set_sensitive(False)
        self.filter_remote_btn.connect("clicked", lambda *_: self._filter_detail_remote())
        actions.pack_start(self.filter_remote_btn, False, False, 0)
        details.content.pack_start(actions, False, False, 0)
        note = Gtk.Label(label="Process, username and executable are best-effort without root privileges.", xalign=0)
        note.set_line_wrap(True)
        note.get_style_context().add_class("muted")
        details.content.pack_start(note, False, False, 0)
        pane.pack2(details, resize=True, shrink=True)
        return pane

    def _connection_pane_allocated(self, pane, allocation):
        # Pick a proportional first position once. After that, respect manual
        # divider movement and let the responsive columns adapt around it.
        if self._pane_position_initialized or allocation.width < 500:
            return
        desired = int(allocation.width * 0.68)
        desired = max(360, min(desired, allocation.width - 300))
        pane.set_position(desired)
        self._pane_position_initialized = True

    def _build_listeners_view(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.listener_store = self._new_connection_store()
        self.listener_tree = self._build_tree(self.listener_store, listening=True)
        scroll = Gtk.ScrolledWindow()
        self.listener_scroll = scroll
        scroll.set_min_content_height(360)
        scroll.add(self.listener_tree)
        self._bind_tree_viewport(self.listener_tree, scroll)
        box.pack_start(scroll, True, True, 0)
        hint = Gtk.Label(
            label="Listening TCP sockets and unconnected UDP endpoints are shown here. Process ownership is best-effort without root privileges.",
            xalign=0,
        )
        hint.set_line_wrap(True)
        hint.get_style_context().add_class("muted")
        box.pack_start(hint, False, False, 4)
        return box

    def _build_interfaces_view(self):
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.interfaces_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.interfaces_box.set_border_width(2)
        scroll.add(self.interfaces_box)
        return scroll

    def _state_color(self, state):
        dark = self._is_dark_theme()
        palette = {
            "ESTABLISHED": "#45cf7a" if dark else "#14804a",
            "LISTEN": "#6aa8ff" if dark else "#175cd3",
            "SYN_SENT": "#ffb34c" if dark else "#b54708",
            "SYN_RECV": "#ffb34c" if dark else "#b54708",
            "CLOSE_WAIT": "#ff8a65" if dark else "#c2410c",
            "TIME_WAIT": "#9aa8b7" if dark else "#667085",
            "NONE": "#9aa8b7" if dark else "#667085",
        }
        return palette.get(state, palette["NONE"])

    def _is_dark_theme(self):
        settings = Gtk.Settings.get_default()
        try:
            return bool(settings.get_property("gtk-application-prefer-dark-theme")) if settings else False
        except Exception:
            return False

    def _state_cell_data(self, _column, cell, model, itr, _data=None):
        state = model.get_value(itr, self.COL_STATE)
        cell.set_property("text", state)
        cell.set_property("foreground", self._state_color(state))
        cell.set_property("weight", Pango.Weight.BOLD if state in ("ESTABLISHED", "CLOSE_WAIT", "SYN_SENT", "SYN_RECV") else Pango.Weight.NORMAL)

    def _scope_color(self, scope):
        dark = self._is_dark_theme()
        palette = {
            "Local": "#b69cff" if dark else "#6941c6",
            "LAN": "#6aa8ff" if dark else "#175cd3",
            "Internet": "#45cf7a" if dark else "#14804a",
            "Unknown": "#9aa8b7" if dark else "#667085",
        }
        return palette.get(scope, palette["Unknown"])

    def _scope_cell_data(self, _column, cell, model, itr, _data=None):
        scope = model.get_value(itr, self.COL_SCOPE) or "Unknown"
        cell.set_property("text", scope)
        cell.set_property("foreground", self._scope_color(scope))
        cell.set_property("weight", Pango.Weight.BOLD if scope in ("LAN", "Internet") else Pango.Weight.NORMAL)

    def _process_cell_data(self, _column, cell, model, itr, _data=None):
        process = model.get_value(itr, self.COL_PROCESS)
        cell.set_property("text", process)
        if process == "—":
            cell.set_property("foreground", "#9aa8b7" if self._is_dark_theme() else "#667085")
            cell.set_property("style", Pango.Style.ITALIC)
        else:
            cell.set_property("foreground-set", False)
            cell.set_property("style", Pango.Style.NORMAL)

    def _pid_cell_data(self, _column, cell, model, itr, _data=None):
        pid = model.get_value(itr, self.COL_PID)
        cell.set_property("text", str(pid) if pid else "—")
        cell.set_property("foreground-set", False)

    def _view_changed(self, *_):
        visible = self.view_stack.get_visible_child_name() or "connections"
        on_connections = visible == "connections"
        on_listeners = visible == "listeners"
        self.search.set_sensitive(on_connections or on_listeners)
        self.protocol.set_sensitive(on_connections or on_listeners)
        self.scope.set_sensitive(on_connections)
        self.state.set_sensitive(on_connections)
        self._render_tables()
        if visible == "interfaces":
            self._render_interfaces()

    def _on_map(self, *_):
        # Returning to a deliberately paused Network page must not silently
        # replace the frozen snapshot.  First use still gets an initial sample.
        if not self._paused or self._snapshot is None:
            self.refresh(force=True)
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(2, self._tick)

    def _on_unmap(self, *_):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _on_destroy(self, *_):
        self._on_unmap()
        for source_id in list(self._column_resize_source.values()):
            try:
                GLib.source_remove(source_id)
            except Exception:
                pass
        self._column_resize_source.clear()

    def _tick(self):
        if not self._paused:
            self.refresh()
        return True

    def _toggle_pause(self, *_):
        self._paused = not self._paused
        # Invalidate an already-running periodic sample so Pause freezes the
        # screen immediately when its callback eventually returns.
        self._refresh_serial += 1
        if self._paused:
            # Start paused/manual samples from a clean rate baseline rather than
            # averaging traffic across the entire paused interval.
            self._previous_io = None
            self.pause_btn.set_label("Resume")
            self.pause_btn.set_image(Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON))
            self.pause_btn.get_style_context().add_class("paused-live")
            self.live_pill.set_state("Paused", "warning")
            self.live_pill.set_tooltip_text("Live refresh is paused. Refresh Now still takes a one-shot sample.")
        else:
            self.pause_btn.set_label("Pause")
            self.pause_btn.set_image(Gtk.Image.new_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.BUTTON))
            self.pause_btn.get_style_context().remove_class("paused-live")
            self.live_pill.set_state("Live • 2s", "ok")
            self.live_pill.set_tooltip_text("Network data refreshes every 2 seconds.")
            # Avoid displaying a long pause interval as if it were an
            # instantaneous transfer rate. The following sample establishes a
            # fresh baseline and the next 2-second sample shows the live rate.
            self._previous_io = None
            self.refresh(force=True)

    def refresh(self, force=False):
        if self._paused and not force:
            return
        if self._busy:
            return
        self._busy = True
        self._refresh_serial += 1
        serial = self._refresh_serial
        manual_while_paused = bool(force and self._paused)
        self.app.run_async(
            network_overview,
            lambda snapshot, error, serial=serial, manual=manual_while_paused:
                self._apply_snapshot(snapshot, error, serial, manual),
        )

    def _apply_snapshot(self, snapshot, error, serial=None, manual_while_paused=False):
        self._busy = False
        if serial is not None and serial != self._refresh_serial:
            return False
        if self._paused and not manual_while_paused:
            return False
        if error:
            self.live_pill.set_state("Paused" if self._paused else "Live • 2s", "error")
            self.live_pill.set_tooltip_text(f"Network refresh failed: {error}")
            self.app.window.toast(f"Network refresh failed: {error}", "error")
            return False

        previous = self._previous_io
        now = snapshot.get("timestamp", 0.0)
        recv_total = snapshot.get("bytes_recv", 0)
        sent_total = snapshot.get("bytes_sent", 0)
        if previous:
            dt = max(0.05, now - previous[0])
            self._rx_rate = max(0.0, (recv_total - previous[1]) / dt)
            self._tx_rate = max(0.0, (sent_total - previous[2]) / dt)
        else:
            self._rx_rate = self._tx_rate = 0.0
        self._previous_io = (now, recv_total, sent_total)
        self._snapshot = snapshot

        connected = snapshot.get("connected", False)
        dns_ok = snapshot.get("dns_ok", False)
        net_state = "info" if connected is None else "ok" if connected and dns_ok else "warning"
        interface = snapshot.get("primary_interface", "—")
        ip = snapshot.get("primary_ipv4", "—")
        gateway = snapshot.get("gateway", "—")
        dns_servers = snapshot.get("dns_servers", [])
        self.cards["interface"].update(
            interface,
            "Couldn't check route" if connected is None else ("Route available • DNS OK" if dns_ok else "Route available • DNS issue") if connected else "No default route",
            snapshot.get("route_error") or f"{ip} • GW {gateway}",
            net_state,
        )
        self.cards["interface"].set_tooltip_text(
            "DNS: " + (", ".join(dns_servers) if dns_servers else "not detected")
        )
        self.cards["download"].update(
            human_rate(self._rx_rate), "Receiving", f"Total {human_bytes(recv_total)}",
            "ok" if connected else "warning",
        )
        self.cards["upload"].update(
            human_rate(self._tx_rate), "Transmitting", f"Total {human_bytes(sent_total)}",
            "ok" if connected else "warning",
        )
        self.cards["connections"].update(
            str(snapshot.get("established", 0)), "Established",
            f"{snapshot.get('tcp_count', 0)} TCP • {snapshot.get('udp_count', 0)} UDP", "ok",
        )
        self.cards["listening"].update(
            str(snapshot.get("listening", 0)), "Open endpoints", "Local listeners", "info",
        )

        self.rx_legend.set_text(f"● RX {human_rate(self._rx_rate)}")
        self.tx_legend.set_text(f"● TX {human_rate(self._tx_rate)}")
        self.traffic_graph.add_values(self._rx_rate, self._tx_rate)
        if self._paused:
            self.live_pill.set_state("Paused", "warning")
            self.live_pill.set_tooltip_text("Paused after a manual one-shot refresh.")
        else:
            self.live_pill.set_state("Live • 2s", "ok" if connected else "warning")
            self.live_pill.set_tooltip_text("Network data refreshes every 2 seconds.")
        self.updated_label.set_text("Last updated " + datetime.now().strftime("%H:%M:%S"))
        self._render_tables()
        if self.view_stack.get_visible_child_name() == "interfaces":
            self._render_interfaces()
        return False

    def _filtered_connections(self, listeners=False):
        if not self._snapshot:
            return []
        text = self.search.get_text().strip().lower()
        protocol = self.protocol.get_active_text() or "All Protocols"
        scope = self.scope.get_active_text() or "All Scopes"
        state = self.state.get_active_text() or "All States"
        rows = []
        for row in self._snapshot.get("connections", []):
            if bool(row.get("listening")) != bool(listeners):
                continue
            if protocol != "All Protocols" and row.get("protocol") != protocol:
                continue
            if not listeners and scope != "All Scopes" and row.get("scope") != scope:
                continue
            if not listeners and state != "All States" and row.get("state") != state:
                continue
            if text:
                haystack = " ".join((
                    row.get("process", ""), row.get("user", ""), row.get("exe", ""),
                    row.get("interface", ""), row.get("scope", ""),
                    row.get("protocol", ""), row.get("family", ""),
                    row.get("local", ""), row.get("remote", ""), row.get("state", ""),
                    str(row.get("pid", "")),
                )).lower()
                if text not in haystack:
                    continue
            rows.append(row)
        return rows

    def _append_row(self, store, row):
        store.append([
            row.get("key", ""),
            row.get("protocol", "—"),
            row.get("process", "—"),
            row.get("local", "—"),
            row.get("remote", "—"),
            row.get("state", "NONE"),
            int(row.get("pid") or 0),
            row.get("family", "—"),
            bool(row.get("listening")),
            row.get("scope", "Unknown"),
            row.get("interface", "—"),
            row.get("user", "—"),
            row.get("exe", "—"),
            row.get("local_ip", "*"),
            int(row.get("local_port") or 0),
            row.get("remote_ip", "*"),
            int(row.get("remote_port") or 0),
        ])

    def _scroll_value(self, scroll):
        try:
            return float(scroll.get_vadjustment().get_value())
        except Exception:
            return 0.0

    def _restore_scroll(self, scroll, value):
        try:
            adj = scroll.get_vadjustment()
            maximum = max(adj.get_lower(), adj.get_upper() - adj.get_page_size())
            adj.set_value(min(max(value, adj.get_lower()), maximum))
        except Exception:
            pass
        return False

    def _restore_selected_key(self, tree, key):
        if not key:
            return False
        model = tree.get_model()
        # Integer paths avoid iter_next() binding differences across GTK3 /
        # PyGObject versions and also work while ListStore sorting is active.
        for index in range(len(model)):
            try:
                itr = model.get_iter(Gtk.TreePath.new_from_indices([index]))
            except Exception:
                continue
            if model.get_value(itr, self.COL_KEY) == key:
                tree.get_selection().select_iter(itr)
                return False
        return False

    def _render_tables(self):
        if not hasattr(self, "connection_store"):
            return
        selected_key = self._selected_key
        conn_scroll = self._scroll_value(self.connection_scroll)
        listener_scroll = self._scroll_value(self.listener_scroll)
        connections = self._filtered_connections(listeners=False)
        listeners = self._filtered_connections(listeners=True)

        self.connection_store.clear()
        for row in connections:
            self._append_row(self.connection_store, row)
        self.listener_store.clear()
        for row in listeners:
            self._append_row(self.listener_store, row)

        GLib.idle_add(self._restore_selected_key, self.connection_tree, selected_key)
        GLib.idle_add(self._restore_scroll, self.connection_scroll, conn_scroll)
        GLib.idle_add(self._restore_scroll, self.listener_scroll, listener_scroll)

        visible = self.view_stack.get_visible_child_name() if hasattr(self, "view_stack") else "connections"
        all_rows = self._snapshot.get("connections", []) if self._snapshot else []
        total_connections = sum(1 for row in all_rows if not row.get("listening"))
        total_listeners = sum(1 for row in all_rows if row.get("listening"))
        if visible == "listeners":
            if len(listeners) != total_listeners:
                self.count_label.set_text(f"{len(listeners)} shown • {total_listeners} total")
            else:
                self.count_label.set_text(f"{len(listeners)} listening")
        elif visible == "interfaces":
            count = len(self._snapshot.get("interfaces", [])) if self._snapshot else 0
            self.count_label.set_text(f"{count} interfaces")
        else:
            if len(connections) != total_connections:
                self.count_label.set_text(f"{len(connections)} shown • {total_connections} total")
            else:
                self.count_label.set_text(f"{len(connections)} connections")

    def _render_interfaces(self):
        if not self._snapshot:
            return
        for child in self.interfaces_box.get_children():
            self.interfaces_box.remove(child)
        primary = self._snapshot.get("primary_interface")
        for item in self._snapshot.get("interfaces", []):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
            row.get_style_context().add_class("network-interface-row")
            row.set_border_width(12)

            icon = Gtk.Image.new_from_icon_name(
                "network-wired-symbolic" if item.get("up") else "network-offline-symbolic",
                Gtk.IconSize.LARGE_TOOLBAR,
            )
            icon.get_style_context().add_class("ok" if item.get("up") else "muted")
            row.pack_start(icon, False, False, 4)

            name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            name = item.get("name", "—")
            name_label = Gtk.Label(label=name + ("  •  Primary" if name == primary else ""), xalign=0)
            name_label.get_style_context().add_class("action-title")
            status = "Up" if item.get("up") else "Down"
            speed = item.get("speed_mbps", 0)
            meta = f"{status} • MTU {item.get('mtu', 0)}"
            if speed:
                meta += f" • {speed} Mb/s"
            meta_label = Gtk.Label(label=meta, xalign=0)
            meta_label.get_style_context().add_class("muted")
            name_box.pack_start(name_label, False, False, 0)
            name_box.pack_start(meta_label, False, False, 0)
            row.pack_start(name_box, False, False, 0)

            address_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            ipv4 = ", ".join(item.get("ipv4", [])) or "No IPv4 address"
            ipv6 = ", ".join(item.get("ipv6", [])[:2]) or "No IPv6 address"
            a4 = Gtk.Label(label=f"IPv4  {ipv4}", xalign=0)
            a6 = Gtk.Label(label=f"IPv6  {ipv6}", xalign=0)
            a4.set_ellipsize(Pango.EllipsizeMode.END)
            a6.set_ellipsize(Pango.EllipsizeMode.END)
            a6.get_style_context().add_class("muted")
            address_box.pack_start(a4, False, False, 0)
            address_box.pack_start(a6, False, False, 0)
            row.pack_start(address_box, True, True, 0)

            traffic = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            rx = Gtk.Label(label=f"↓ {human_bytes(item.get('bytes_recv', 0))}", xalign=1)
            tx = Gtk.Label(label=f"↑ {human_bytes(item.get('bytes_sent', 0))}", xalign=1)
            rx.get_style_context().add_class("network-rx")
            tx.get_style_context().add_class("network-tx")
            traffic.pack_start(rx, False, False, 0)
            traffic.pack_start(tx, False, False, 0)
            row.pack_end(traffic, False, False, 0)
            self.interfaces_box.pack_start(row, False, False, 0)

        if not self._snapshot.get("interfaces"):
            empty = Gtk.Label(label="No interface information is available.", xalign=0)
            empty.get_style_context().add_class("empty-text")
            self.interfaces_box.pack_start(empty, False, False, 12)
        self.interfaces_box.show_all()

    def _row_dict_from_model(self, model, itr):
        return {
            "key": model.get_value(itr, self.COL_KEY),
            "protocol": model.get_value(itr, self.COL_PROTOCOL),
            "process": model.get_value(itr, self.COL_PROCESS),
            "local": model.get_value(itr, self.COL_LOCAL),
            "remote": model.get_value(itr, self.COL_REMOTE),
            "state": model.get_value(itr, self.COL_STATE),
            "pid": model.get_value(itr, self.COL_PID),
            "family": model.get_value(itr, self.COL_FAMILY),
            "scope": model.get_value(itr, self.COL_SCOPE),
            "interface": model.get_value(itr, self.COL_INTERFACE),
            "user": model.get_value(itr, self.COL_USER),
            "exe": model.get_value(itr, self.COL_EXE),
            "local_ip": model.get_value(itr, self.COL_LOCAL_IP),
            "local_port": model.get_value(itr, self.COL_LOCAL_PORT),
            "remote_ip": model.get_value(itr, self.COL_REMOTE_IP),
            "remote_port": model.get_value(itr, self.COL_REMOTE_PORT),
        }

    def _selection_changed(self, tree):
        selection = tree.get_selection()
        model, itr = selection.get_selected()
        if itr is None:
            return
        row = self._row_dict_from_model(model, itr)
        if tree is self.connection_tree:
            self._selected_key = row["key"]
            self._detail_row = row
            self._set_details(row)

    def _set_details(self, row):
        pid = row.get("pid") or 0
        lines = [
            f"Process:      {row.get('process') or '—'}",
            f"PID:          {pid if pid else 'Unavailable'}",
            f"User:         {row.get('user') or '—'}",
            f"Executable:   {row.get('exe') or '—'}",
            "",
            f"Interface:    {row.get('interface') or '—'}",
            f"Protocol:     {row.get('protocol', '—')} / {row.get('family', '—')}",
            f"Scope:        {row.get('scope', 'Unknown')}",
            f"State:        {row.get('state', '—')}",
            "",
            f"Local:        {row.get('local', '—')}",
            f"Remote:       {row.get('remote', '—')}",
        ]
        self.detail.get_buffer().set_text("\n".join(lines))
        self.filter_process_btn.set_sensitive(row.get("process") not in (None, "", "—"))
        self.filter_remote_btn.set_sensitive(row.get("remote_ip") not in (None, "", "*", "—"))

    def _clipboard(self, text, message="Copied"):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(str(text or ""), -1)
        self.app.window.toast(message, "ok")

    def _copy_details(self, *_):
        buf = self.detail.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        self._clipboard(text, "Connection details copied")

    def _filter_detail_process(self):
        row = self._detail_row or {}
        value = row.get("process")
        if value and value != "—":
            self.search.set_text(value)

    def _filter_detail_remote(self):
        row = self._detail_row or {}
        value = row.get("remote_ip")
        if value and value not in ("—", "*"):
            self.search.set_text(value)

    def _set_combo_text(self, combo, text):
        model = combo.get_model()
        if model is None:
            return False
        for index in range(len(model)):
            try:
                itr = model.get_iter(Gtk.TreePath.new_from_indices([index]))
            except Exception:
                continue
            if model.get_value(itr, 0) == text:
                combo.set_active(index)
                return True
        return False

    def _clear_filters(self, *_):
        self.search.set_text("")
        self.protocol.set_active(0)
        self.scope.set_active(0)
        self.state.set_active(0)
        self._render_tables()

    def _context_row(self, tree, event):
        hit = tree.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return None
        path = hit[0]
        tree.get_selection().select_path(path)
        model = tree.get_model()
        itr = model.get_iter(path)
        return self._row_dict_from_model(model, itr)

    def _tree_button_press(self, tree, event, listening=False):
        if event.button != 3:
            return False
        row = self._context_row(tree, event)
        if not row:
            return False
        menu = Gtk.Menu()

        def item(label, callback, sensitive=True):
            entry = Gtk.MenuItem(label=label)
            entry.set_sensitive(bool(sensitive))
            entry.connect("activate", callback)
            menu.append(entry)
            return entry

        if listening:
            item("Copy Listener", lambda *_: self._clipboard(
                f"{row.get('protocol')} {row.get('local')} {row.get('process')} PID {row.get('pid') or '—'}",
                "Listener copied",
            ))
            item("Copy Local IP", lambda *_: self._clipboard(row.get("local_ip"), "Local IP copied"), row.get("local_ip") not in ("*", "—"))
            item("Copy Port", lambda *_: self._clipboard(row.get("local_port"), "Port copied"), bool(row.get("local_port")))
        else:
            item("Copy Connection", lambda *_: self._clipboard(
                f"{row.get('protocol')} {row.get('local')} → {row.get('remote')} {row.get('state')}",
                "Connection copied",
            ))
            item("Copy Remote IP", lambda *_: self._clipboard(row.get("remote_ip"), "Remote IP copied"), row.get("remote_ip") not in ("*", "—"))
            item("Copy Remote Port", lambda *_: self._clipboard(row.get("remote_port"), "Remote port copied"), bool(row.get("remote_port")))

        menu.append(Gtk.SeparatorMenuItem())
        process = row.get("process")
        item("Filter This Process", lambda *_: self.search.set_text(process), process not in (None, "", "—"))
        if not listening:
            remote_ip = row.get("remote_ip")
            item("Filter This Remote", lambda *_: self.search.set_text(remote_ip), remote_ip not in (None, "", "*", "—"))
            scope = row.get("scope") or "Unknown"
            item(f"Show Only {scope}", lambda *_: self._set_combo_text(self.scope, scope), scope in ("Local", "LAN", "Internet", "Unknown"))
        menu.append(Gtk.SeparatorMenuItem())
        item("Clear Filters", self._clear_filters)
        menu.show_all()
        try:
            menu.popup_at_pointer(event)
        except Exception:
            menu.popup(None, None, None, None, event.button, event.time)
        return True
