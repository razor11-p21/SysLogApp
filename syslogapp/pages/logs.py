# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import csv
import json
import subprocess
import threading
from collections import deque
from datetime import datetime
from functools import lru_cache

from gi.repository import Gtk, GLib, Gdk, Pango

from ..widgets import CommandBar, action_menu, ColumnSizing, TableTextAccess, selectable_readouts
from ..config import column_widths
from ..config import log_capacity
from ..sorting import log_sort_key, compare, natural_key, timestamp_key

from ..services import load_logs, PRIORITY_LABELS


SEVERITY_COLORS = {0: '#ff4d57', 1: '#ff5962', 2: '#ff6b73', 3: '#ff8188',
                   4: '#ffb34c', 5: '#b69cff', 6: '#6aa8ff', 7: '#9aa8b7'}
MESSAGE_COLORS = {0: '#ff7a82', 1: '#ff858c', 2: '#ff8f96', 3: '#ff9da3',
                  4: '#f6bd67', 5: '#c2afff', 6: '#c6d4c9', 7: '#9aa8b7'}


class LogsPage(Gtk.Box):
    COL_TIME = 0
    COL_UNIT = 1
    COL_LEVEL = 2
    COL_MESSAGE = 3
    COL_PRIORITY = 4
    COL_RAW = 5

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.app = app
        self.host = getattr(app, "host", None)
        self._live_proc = None
        self._live_thread = None
        self._busy = False
        self._pending_reload = False
        self._suspend_controls = False
        self._all_rows = []
        self._last_pane_width = 0
        self._live_generation = 0
        self._destroyed = False
        self.max_rows = log_capacity(app.config)
        self._pending_lock = threading.Lock()
        self._pending_rows = deque(maxlen=self.max_rows)
        self._drain_source = 0
        self._dropped_pending = 0
        self._stream_dropped = 0
        self._mapped_once = False
        self._reflow_source = 0
        self.set_border_width(0)

        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        top.set_border_width(8)
        self.count_label = Gtk.Label(label="0 entries")
        self.count_label.get_style_context().add_class("muted")

        self.command_bar = CommandBar()
        toolbar = self.command_bar.primary
        toolbar.set_border_width(2)

        self.live = Gtk.ToggleButton(label="Paused")
        self.live.set_image(Gtk.Image.new_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.BUTTON))
        self.live.get_style_context().add_class("paused-live")
        self.live.set_tooltip_text("Pause or resume live journal updates (F6 / F7)")
        self.live.set_always_show_image(True)
        self.live.connect("toggled", self._on_live)
        toolbar.add(self.live)

        self.scope = Gtk.ComboBoxText()
        self.scope.append("boot", "Current Boot")
        self.scope.append("all", "Recent History")
        self.scope.set_active_id("boot")
        self.scope.connect("changed", self._filter_changed)
        toolbar.add(self.scope)

        self.priority = Gtk.ComboBoxText()
        for item in ("All", "Critical", "Error", "Warning", "Notice", "Info", "Debug"):
            self.priority.append_text(item)
        self.priority.set_active(0)
        self.priority.connect("changed", self._filter_changed)
        toolbar.add(self.priority)

        self.unit = Gtk.Entry()
        self.unit.set_placeholder_text("Service/unit (optional)")
        self.unit.set_width_chars(13)
        self.unit.connect("activate", self._unit_activate)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search loaded logs…")
        self.search.set_hexpand(True)
        self.search.connect("search-changed", self._search_changed)
        self.search.set_width_chars(12)
        self.command_bar.secondary.pack_start(self.search, True, True, 0)
        self.command_bar.secondary.pack_start(self.unit, False, False, 0)

        refresh = Gtk.Button()
        refresh.add(Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON))
        refresh.set_tooltip_text("Reload logs")
        refresh.connect("clicked", self._refresh_clicked)
        self.command_bar.secondary.pack_start(refresh, False, False, 0)

        self.more_actions = action_menu([('Export logs…', self._export), ('Fit columns', self._fit_columns)])
        self.command_bar.secondary.pack_start(self.more_actions, False, False, 0)
        toolbar.add(self.count_label)
        top.pack_start(self.command_bar, False, False, 0)

        self.pack_start(top, False, False, 0)

        self.pane = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.pane.set_wide_handle(True)
        self.pane.set_margin_start(10)
        self.pane.set_margin_end(10)
        self.pane.set_margin_bottom(8)
        self.pane.connect("size-allocate", self._resize_pane)

        # Native TreeView paints visible rows without a widget per event.
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.get_style_context().add_class("section-card")
        self.store = Gtk.ListStore(str, str, str, str, int, object)
        for column in range(4):
            self.store.set_sort_func(column, self._compare_rows, column)
        self.store.set_sort_column_id(self.COL_TIME, Gtk.SortType.ASCENDING)
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.set_headers_visible(True)
        self.tree.set_enable_search(False)
        self.tree.set_grid_lines(Gtk.TreeViewGridLines.NONE)
        # Wrapped messages need variable heights; history remains bounded.
        self.tree.set_fixed_height_mode(False)
        # Do not use Gtk.TreeView.set_tooltip_column() here. GTK3 feeds that
        # value to Pango as markup, so legitimate journal text containing '&'
        # or '<...>' can trigger markup parser warnings. Provide a plain-text
        # tooltip ourselves instead.
        self.tree.set_has_tooltip(True)
        self.tree.connect("query-tooltip", self._query_log_tooltip)
        self.tree.get_selection().connect("changed", self._selection_changed)
        self.tree.connect("button-press-event", self._tree_button_press)
        self.tree.connect("row-activated", self._activate_event)
        # The log table uses the *viewport* width, not the TreeView's natural
        # request, as the source of truth for column sizing.  This is important
        # in GTK3: a TreeView containing long text may otherwise keep reporting
        # a large natural width even when its ScrolledWindow has become narrow.
        self.tree_columns = {}
        self.tree_renderers = {}

        # A dedicated severity marker makes important events scannable without
        # turning the entire table into a wall of color.
        self.severity_renderer = Gtk.CellRendererText()
        self.severity_renderer.set_property("xalign", 0.5)
        self.severity_renderer.set_property("yalign", 0.0)
        self.severity_renderer.set_property("ypad", 0)
        severity_col = Gtk.TreeViewColumn("", self.severity_renderer)
        severity_col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        severity_col.set_fixed_width(28)
        severity_col.set_min_width(28)
        severity_col.set_max_width(-1)
        severity_col.set_cell_data_func(self.severity_renderer, self._severity_indicator_cell_data)
        self.tree.append_column(severity_col)

        specs = [
            ("Time", self.COL_TIME),
            ("Source", self.COL_UNIT),
            ("Level", self.COL_LEVEL),
            ("Message", self.COL_MESSAGE),
        ]
        for title_text, idx in specs:
            renderer = Gtk.CellRendererText()
            renderer.set_property("ypad", 0)
            renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
            renderer.set_property("single-paragraph-mode", True)
            renderer.set_property("yalign", 0.0)
            if idx == self.COL_MESSAGE:
                renderer.set_property("ellipsize", Pango.EllipsizeMode.NONE)
                renderer.set_property("single-paragraph-mode", False)
                renderer.set_property("wrap-mode", Pango.WrapMode.WORD_CHAR)
                renderer.set_property("wrap-width", 420)

            col = Gtk.TreeViewColumn(title_text, renderer, text=idx)
            if idx == self.COL_TIME:
                col.set_cell_data_func(renderer, self._time_cell_data)
            elif idx == self.COL_LEVEL:
                col.set_cell_data_func(renderer, self._severity_level_cell_data)
            elif idx == self.COL_MESSAGE:
                col.set_cell_data_func(renderer, self._message_cell_data)
            col.set_sort_column_id(idx)
            col.set_resizable(True)
            col.set_min_width(55)
            col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            self.tree.append_column(col)
            self.tree_columns[idx] = col
            self.tree_renderers[idx] = renderer

        self.column_sizing = ColumnSizing(
            [severity_col] + [self.tree_columns[i] for i in range(4)],
            [None, None, None, None, self.tree_renderers[self.COL_MESSAGE]],
            self._schedule_reflow, column_widths(getattr(app, 'config', {}), 'logs'))
        self.log_scroll = Gtk.ScrolledWindow()
        # Automatic horizontal policy lets GTK shrink the viewport below the
        # table's previous natural width when the window becomes narrower.
        self.log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.log_scroll.set_min_content_width(0)
        self.log_scroll.set_hexpand(True)
        self.log_scroll.connect("size-allocate", self._resize_columns)
        self.log_scroll.add(self.tree)
        left.set_hexpand(True)
        left.pack_start(self.log_scroll, True, True, 0)
        self.pane.pack1(left, resize=True, shrink=True)

        # Details panel. It is allowed to resize/shrink too, and its text wraps.
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.details_panel = details
        details.set_no_show_all(True)
        details.get_style_context().add_class("section-card")
        details.set_border_width(8)
        details.set_size_request(280, -1)
        dtitle = Gtk.Label(label="Event Details", xalign=0)
        dtitle.get_style_context().add_class("section-title")
        detail_heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        detail_heading.pack_start(dtitle, True, True, 0)
        close_details = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.BUTTON)
        close_details.set_relief(Gtk.ReliefStyle.NONE)
        close_details.set_tooltip_text("Close event details")
        close_details.connect("clicked", lambda *_: self.tree.get_selection().unselect_all())
        detail_heading.pack_end(close_details, False, False, 0)
        details.pack_start(detail_heading, False, False, 0)
        self.detail_meta = Gtk.Label(label="Select a log entry to inspect it.", xalign=0)
        self.detail_meta.get_style_context().add_class("muted")
        self.detail_meta.set_line_wrap(True)
        details.pack_start(self.detail_meta, False, False, 0)
        self.detail_message = Gtk.TextView()
        self.detail_message.set_editable(False)
        self.detail_message.set_cursor_visible(False)
        self.detail_message.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.detail_message.get_style_context().add_class("detail-text")
        dscroll = Gtk.ScrolledWindow()
        dscroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        dscroll.set_min_content_height(72)
        dscroll.add(self.detail_message)
        details.pack_start(dscroll, True, True, 0)
        detail_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        only_service_btn = Gtk.Button(label="Only This Service")
        only_service_btn.set_image(Gtk.Image.new_from_icon_name("view-filter-symbolic", Gtk.IconSize.BUTTON))
        only_service_btn.set_always_show_image(True)
        only_service_btn.connect("clicked", self._show_selected_service)
        detail_actions.pack_start(only_service_btn, True, True, 0)
        copy_btn = Gtk.Button(label="Copy Event")
        copy_btn.set_image(Gtk.Image.new_from_icon_name("edit-copy-symbolic", Gtk.IconSize.BUTTON))
        copy_btn.set_always_show_image(True)
        copy_btn.connect("clicked", self._copy_selected)
        detail_actions.pack_start(copy_btn, True, True, 0)
        details.pack_start(detail_actions, False, False, 0)
        self.pane.pack2(details, resize=False, shrink=False)
        self.pack_start(self.pane, True, True, 0)

        self.text_access = TableTextAccess(
            self.tree, {self.tree_columns[i]: i for i in range(4)},
            [('Copy Event', self._copy_selected), ('Copy Message', self._copy_message),
             ('Show Only This Service', self._show_selected_service),
             ('Show This Severity', self._show_selected_severity),
             ('Clear Filters', self._clear_log_filters)], connect=False,
            on_select=self._hold_for_selection, cell_data=self._selection_cell_data,
            format_value=lambda index, value: self._friendly_time(value) if index == 0 else value)
        self.log_scroll.set_margin_bottom(12)
        self.detail_message.set_bottom_margin(16)
        selectable_readouts(self)
        self.connect("map", self._on_map)
        self.connect("destroy", self._on_destroy)

    def _selection_cell_data(self, column, cell, model, itr, index):
        callback = {self.COL_TIME: self._time_cell_data,
                    self.COL_LEVEL: self._severity_level_cell_data,
                    self.COL_MESSAGE: self._message_cell_data}.get(index)
        if callback:
            callback(column, cell, model, itr)

    def _hold_for_selection(self):
        if self.live.get_active():
            self.live.set_active(False)

    @staticmethod
    def _clamp(value, low, high):
        return max(low, min(high, value))

    @staticmethod
    @lru_cache(maxsize=2048)
    def _parse_timestamp(value):
        """Parse SysLogApp's canonical local journal timestamp."""
        try:
            return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    def _friendly_time(self, value):
        """Return a compact timestamp optimized for scanning log rows.

        The canonical value remains unchanged in ``_all_rows``/journal data;
        only the TreeView presentation is shortened.
        """
        dt = self._parse_timestamp(value)
        if dt is None:
            return str(value or "—")

        now = datetime.now()
        if dt.date() == now.date():
            return dt.strftime("%H:%M:%S")
        return dt.strftime("%m-%d %H:%M:%S" if dt.year == now.year else "%Y-%m-%d %H:%M:%S")

    def _primary_sort_key(self, model, itr, column):
        if column == self.COL_TIME:
            raw = model.get_value(itr, self.COL_RAW)
            if isinstance(raw, dict) and '__REALTIME_TIMESTAMP' in raw:
                value = raw['__REALTIME_TIMESTAMP']
            else:
                value = model.get_value(itr, self.COL_TIME)
            return timestamp_key(str(value))
        if column == self.COL_LEVEL:
            return int(model.get_value(itr, self.COL_PRIORITY))
        return natural_key(model.get_value(itr, column))

    def _compare_rows(self, model, left, right, column):
        # Most comparisons finish with the selected field. Fetch the remaining
        # GTK columns and compute detailed tie-breaks only for equal primaries.
        primary = compare(self._primary_sort_key(model, left, column),
                          self._primary_sort_key(model, right, column))
        if primary:
            return primary
        return compare(log_sort_key(tuple(model[left]), column), log_sort_key(tuple(model[right]), column))

    def _exact_time(self, raw=None, fallback=None):
        """Recover the precise local timestamp from a journal record."""
        if isinstance(raw, dict):
            ts = raw.get("__REALTIME_TIMESTAMP")
            try:
                if ts:
                    return datetime.fromtimestamp(int(ts) / 1_000_000).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        # ``fallback`` can be canonical (historical data) or already friendly.
        if self._parse_timestamp(fallback):
            return str(fallback)
        return str(fallback or "—")

    def _severity_color(self, priority):
        try:
            return SEVERITY_COLORS.get(int(priority), SEVERITY_COLORS[6])
        except (ValueError, TypeError):
            return SEVERITY_COLORS[6]

    def _time_cell_data(self, _column, cell, model, itr, _data=None):
        """Use the event's severity palette for its timestamp too."""
        cell.set_property("text", self._friendly_time(model.get_value(itr, self.COL_TIME)))
        cell.set_property("weight", Pango.Weight.SEMIBOLD)
        cell.set_property("foreground", self._severity_color(model.get_value(itr, self.COL_PRIORITY)))

    def _severity_indicator_cell_data(self, _column, cell, model, itr, _data=None):
        priority = model.get_value(itr, self.COL_PRIORITY)
        cell.set_property("text", "●")
        cell.set_property("foreground", self._severity_color(priority))

    def _severity_level_cell_data(self, _column, cell, model, itr, _data=None):
        priority = model.get_value(itr, self.COL_PRIORITY)
        level = model.get_value(itr, self.COL_LEVEL)
        cell.set_property("text", level)
        cell.set_property("foreground", self._severity_color(priority))
        cell.set_property("weight", Pango.Weight.BOLD if int(priority) <= 4 else Pango.Weight.NORMAL)

    def _message_color(self, priority):
        try:
            return MESSAGE_COLORS.get(int(priority), MESSAGE_COLORS[6])
        except (ValueError, TypeError):
            return MESSAGE_COLORS[6]

    def _message_cell_data(self, _column, cell, model, itr, _data=None):
        priority = model.get_value(itr, self.COL_PRIORITY)
        cell.set_property("foreground", self._message_color(priority))
        cell.set_property("weight", Pango.Weight.BOLD if int(priority) <= 3 else Pango.Weight.NORMAL)

    def _resize_pane(self, _pane, allocation):
        """Keep the inspector below the journal so messages retain full width."""
        height = int(allocation.height)
        if not self.details_panel.get_visible():
            self._last_pane_width = 0
            return
        if height <= 0 or abs(height - self._last_pane_width) < 18:
            return
        self._last_pane_width = height
        self.pane.set_position(max(80, int(height * 0.60)))

    def _resize_columns(self, _scroll, allocation):
        # Fit columns to the viewport and wrap the message in its remaining width.
        usable = max(360, int(allocation.width) - 8)
        widths = {self.COL_TIME: 112, self.COL_UNIT: min(168, max(92, usable // 5)),
                  self.COL_LEVEL: 70}
        widths[self.COL_MESSAGE] = max(100, usable - sum(widths.values()) - 38)
        self.column_sizing.apply_deferred([28] + [widths[i] for i in range(4)])

    def _fit_columns(self, *_):
        self.column_sizing.reset()
        self._resize_columns(self.log_scroll, self.log_scroll.get_allocation())

    def _schedule_reflow(self):
        # One coalesced pass after resizing, never an idle polling timer.
        if self._destroyed:
            return
        if self._reflow_source:
            GLib.source_remove(self._reflow_source)
        self._reflow_source = GLib.timeout_add(100, self._reflow_rows)

    def _reflow_rows(self):
        self._reflow_source = 0
        if self._destroyed:
            return False
        # Invalidate GTK's cached heights so expanding also shrinks old wraps.
        for row in self.store:
            self.store.row_changed(row.path, row.iter)
        self.tree.queue_resize()
        if self.live.get_active():
            self._scroll_to_latest()
        return False

    def _on_map(self, *_):
        if not self._mapped_once:
            self._mapped_once = True
            self.reload()

    def _filter_changed(self, *_):
        if self._suspend_controls:
            return
        if self.live.get_active():
            # Rehydrate matching history first, then keep following.  Using
            # journalctl -f -n <limit> avoids the old behavior where selecting a
            # filter emptied the view and showed only events created afterward.
            self.start_live(reset_view=True, include_history=True)
        else:
            self.reload()

    def _unit_activate(self, *_):
        if self.live.get_active():
            self.start_live(reset_view=True, include_history=True)
        else:
            self.reload()

    def _refresh_clicked(self, *_):
        if self.live.get_active():
            self.start_live(reset_view=False)
            self.app.window.toast("Live journal follower restarted", "info")
        else:
            self.reload()

    def _search_changed(self, *_):
        if not self._suspend_controls:
            self._apply_filter()
            if self.live.get_active():
                GLib.idle_add(self._scroll_to_latest)

    def navigate(self, priority=None, unit=None, search=None, scope=None):
        """Apply journal filters in one historical query."""
        if self.live.get_active():
            self.live.set_active(False)
        self._suspend_controls = True
        try:
            if scope in ("boot", "all"):
                self.scope.set_active_id(scope)
            if priority in ("All", "Critical", "Error", "Warning", "Notice", "Info", "Debug"):
                values = ("All", "Critical", "Error", "Warning", "Notice", "Info", "Debug")
                self.priority.set_active(values.index(priority))
            if unit is not None:
                self.unit.set_text(unit)
            if search is not None:
                self.search.set_text(search)
        finally:
            self._suspend_controls = False
        self.reload()

    def reload(self):
        if self.live.get_active():
            return
        if self._busy:
            self._pending_reload = True
            return
        self._busy = True
        self.count_label.set_text("Loading…")
        limit = self.max_rows
        boot_only = self.scope.get_active_id() == "boot"
        prio = self.priority.get_active_text() or "All"
        unit = self.unit.get_text().strip() or None
        self.app.run_async(lambda: load_logs(limit, boot_only, prio, unit, host=self.host) if self.host else load_logs(limit, boot_only, prio, unit), self._loaded)

    def _loaded(self, result, error):
        if self._destroyed:
            return False
        self._busy = False
        if self._pending_reload:
            self._pending_reload = False
            self.reload()
            return False
        if error:
            self.count_label.set_text("Load failed")
            self.app.window.toast(str(error), "error")
            return False
        # A historical load may finish just after Live was enabled.  Do not let
        # that stale result replace a stream that is already running.
        if self.live.get_active():
            return False
        self._all_rows = list(result)[-self.max_rows:]
        self._apply_filter()
        GLib.idle_add(self._scroll_to_latest)
        return False

    def _apply_filter(self):
        """Apply the client-side text search to the already-loaded journal set.

        Severity, boot scope and unit are server-side journal filters.  Search is
        intentionally local so typing never restarts journalctl or loses context.
        """
        if self._destroyed:
            return
        needle = self.search.get_text().strip().lower()
        column, order = self.store.get_sort_column_id()
        self.store.clear()
        if column is not None:
            self.store.set_sort_column_id(Gtk.TREE_SORTABLE_UNSORTED_SORT_COLUMN_ID, order)
        try:
            for item in self._all_rows:
                if needle and needle not in self._search_text(item):
                    continue
                self.store.append(self._display_row(item))
        finally:
            # Sort a completed snapshot once, rather than on every insertion.
            if column is not None:
                self.store.set_sort_column_id(column, order)

        self._schedule_reflow()
        if self.live.get_active():
            self._update_live_status()
        else:
            shown = len(self.store)
            loaded = len(self._all_rows)
            if shown != loaded:
                self.count_label.set_text(f"{shown} shown · {loaded} loaded")
            else:
                self.count_label.set_text(f"{loaded} loaded")

    def _selected_values(self):
        model, itr = self.tree.get_selection().get_selected()
        if not itr:
            return None
        return [model.get_value(itr, i) for i in range(6)]

    def _copy_message(self, *_):
        values = self._selected_values()
        if not values:
            return
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(values[self.COL_MESSAGE], -1)
        self.app.window.toast("Message copied to clipboard", "ok")

    def _show_selected_service(self, *_):
        values = self._selected_values()
        if not values:
            return
        unit = values[self.COL_UNIT]
        if not unit or unit == "system":
            return
        self.unit.set_text(unit)
        if self.live.get_active():
            self.start_live(reset_view=True, include_history=True)
        else:
            self.reload()

    def _show_selected_severity(self, *_):
        values = self._selected_values()
        if not values:
            return
        level = values[self.COL_LEVEL]
        values_list = ("All", "Critical", "Error", "Warning", "Notice", "Info", "Debug")
        # The Critical UI category intentionally groups Emergency + Alert + Critical.
        if level in ("Emergency", "Alert", "Critical"):
            level = "Critical"
        if level in values_list:
            self.priority.set_active(values_list.index(level))

    def _clear_log_filters(self, *_):
        self._suspend_controls = True
        try:
            self.priority.set_active(0)
            self.unit.set_text("")
            self.search.set_text("")
        finally:
            self._suspend_controls = False
        if self.live.get_active():
            self.start_live(reset_view=True, include_history=True)
        else:
            self.reload()

    def _tree_button_press(self, tree, event):
        handled = self.text_access.button_press(tree, event)
        if event.button == 1 and event.type == Gdk.EventType._2BUTTON_PRESS:
            hit = tree.get_path_at_pos(int(event.x), int(event.y))
            if hit:
                self._activate_event(tree, hit[0], hit[1])
                return True
        return handled

    def _activate_event(self, tree, path, _column):
        tree.get_selection().select_path(path)
        self._selection_changed(tree.get_selection(), reveal=True)

    def _query_log_tooltip(self, tree, x, y, keyboard_mode, tooltip):
        """Show journal messages as literal text, never as Pango markup."""
        try:
            if keyboard_mode:
                model, itr = tree.get_selection().get_selected()
                if not itr:
                    return False
            else:
                hit = tree.get_path_at_pos(int(x), int(y))
                if not hit:
                    return False
                path, column = hit[0], hit[1]
                model = tree.get_model()
                itr = model.get_iter(path)
                if column is self.tree_columns.get(self.COL_TIME):
                    raw = model.get_value(itr, self.COL_RAW)
                    tooltip.set_text(self._exact_time(raw, model.get_value(itr, self.COL_TIME)))
                    return True
            message = model.get_value(itr, self.COL_MESSAGE)
            if not message:
                return False
            tooltip.set_text(str(message))
            return True
        except Exception:
            return False

    def _selection_changed(self, selection, reveal=False):
        model, itr = selection.get_selected()
        if not itr:
            self.details_panel.set_no_show_all(True)
            self.details_panel.hide()
            self.detail_meta.set_text("Select a log entry to inspect it.")
            self.detail_message.get_buffer().set_text("")
            self._last_pane_width = 0
            return
        if not reveal and not self.details_panel.get_visible():
            return
        when, unit, level, message, _priority, raw = [model.get_value(itr, i) for i in range(6)]
        exact_when = self._exact_time(raw, when)
        self.detail_meta.set_text(f"{exact_when}\n{unit}  •  {level}")
        meta_ctx = self.detail_meta.get_style_context()
        message_ctx = self.detail_message.get_style_context()
        severity_classes = ("severity-critical", "severity-error", "severity-warning", "severity-notice", "severity-info", "severity-debug")
        for cls in severity_classes:
            meta_ctx.remove_class(cls)
            message_ctx.remove_class(cls)
        if int(_priority) <= 2:
            severity_class = "severity-critical"
        elif int(_priority) == 3:
            severity_class = "severity-error"
        elif int(_priority) == 4:
            severity_class = "severity-warning"
        elif int(_priority) == 5:
            severity_class = "severity-notice"
        elif int(_priority) == 6:
            severity_class = "severity-info"
        else:
            severity_class = "severity-debug"
        meta_ctx.add_class(severity_class)
        message_ctx.add_class(severity_class)
        raw_text = str(raw.get("MESSAGE", message)) if isinstance(raw, dict) else message
        if isinstance(raw, dict):
            pid = raw.get("_PID")
            comm = raw.get("_COMM")
            extra = []
            if pid:
                extra.append(f"PID: {pid}")
            if comm:
                extra.append(f"Process: {comm}")
            if extra:
                raw_text += "\n\n" + "   ".join(extra)
        self.detail_message.get_buffer().set_text(raw_text)
        if not self.details_panel.get_visible():
            self.details_panel.set_no_show_all(False)
            self.details_panel.show_all()
            self._last_pane_width = 0
            self.pane.queue_resize()

    def _copy_selected(self, *_):
        sel = self.tree.get_selection()
        model, itr = sel.get_selected()
        if not itr:
            return
        exact_when = self._exact_time(model[itr][self.COL_RAW], model[itr][self.COL_TIME])
        text = f"{exact_when}  {model[itr][1]}  {model[itr][2]}\n{model[itr][3]}"
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        self.app.window.toast("Event copied to clipboard", "ok")

    def _export(self, *_):
        dialog = Gtk.FileChooserDialog(
            title="Export Logs", parent=self.app.window,
            action=Gtk.FileChooserAction.SAVE,
            buttons=("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        )
        dialog.set_current_name("syslogapp-logs.csv")
        response = dialog.run()
        path = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Time", "Source", "Level", "Message"])
                for row in self.store:
                    exact_when = self._exact_time(row[self.COL_RAW], row[self.COL_TIME])
                    writer.writerow([exact_when, row[1], row[2], row[3]])
            self.app.window.toast(f"Exported {len(self.store)} entries", "ok")
        except Exception as exc:
            self.app.window.toast(f"Export failed: {exc}", "error")

    def _sync_live_button(self):
        active = self.live.get_active()
        self.live.set_label('Live' if active else 'Paused')
        self.live.set_image(Gtk.Image.new_from_icon_name(
            'media-playback-start-symbolic' if active else 'media-playback-pause-symbolic', Gtk.IconSize.BUTTON))
        context = self.live.get_style_context()
        (context.add_class if active else context.remove_class)('active-live')
        (context.remove_class if active else context.add_class)('paused-live')

    def _on_live(self, button):
        self._sync_live_button()
        if button.get_active():
            self.store.set_sort_column_id(self.COL_TIME, Gtk.SortType.ASCENDING)
            self.start_live()
        else:
            self.stop_live()

    def toggle_pause(self):
        self.live.set_active(not self.live.get_active())

    def _update_live_status(self):
        if self._destroyed or not self.live.get_active():
            return
        shown = len(self.store)
        loaded = len(self._all_rows)
        counts = f"{shown} shown" if shown == loaded else f"{shown} shown · {loaded} loaded"
        if self._stream_dropped:
            counts += f" · {self._stream_dropped} skipped during bursts"
        self.count_label.set_text(f"LIVE • listening • {counts}")

    def start_live(self, reset_view=False, include_history=False):
        """Start or restart the live journal follower.

        Normal Live activation preserves the already-loaded history and follows
        only new events.  A server-side filter change uses ``include_history``
        so the matching historical entries are emitted first and the process
        then continues following new entries.  This keeps useful context on
        screen instead of leaving an empty table until another event occurs.
        """
        if self._destroyed:
            return
        # If the initial snapshot is still in flight, let the follower supply
        # history atomically instead of discarding it when that read completes.
        if self._busy and not self._all_rows:
            include_history = True
        self.stop_live(update_button=False)
        self._live_generation += 1
        generation = self._live_generation

        if reset_view:
            self._all_rows = []
            self.store.clear()

        line_count = self.max_rows if include_history else 0
        args = ["journalctl", "--follow", "-n", str(line_count), "--no-pager", "--output=json", "--output-fields=__REALTIME_TIMESTAMP,PRIORITY,_SYSTEMD_UNIT,SYSLOG_IDENTIFIER,_COMM,_PID,MESSAGE"]
        if not include_history and self._all_rows:
            cursor = self._all_rows[-1]["raw"].get("__CURSOR")
            if cursor:
                args += ["--after-cursor", cursor]
        if self.scope.get_active_id() == "boot":
            args += ["-b", "0"]
        unit = self.unit.get_text().strip()
        if unit:
            args += ["-u", unit]
        prio = self.priority.get_active_text() or "All"
        pmap = {
            # journalctl treats a single priority as cumulative.  Ranges make
            # these UI filters exact; Critical intentionally groups 0..2.
            "Critical": "emerg..crit",
            "Error": "err..err",
            "Warning": "warning..warning",
            "Notice": "notice..notice",
            "Info": "info..info",
            "Debug": "debug..debug",
        }
        if prio in pmap:
            args += ["-p", pmap[prio]]

        try:
            self._live_proc = (self.host.popen if self.host else subprocess.Popen)(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                start_new_session=True,
            )
        except Exception as exc:
            self.app.window.toast(f"Unable to start live journal: {exc}", "error")
            self.live.set_active(False)
            return

        self._sync_live_button()

        if include_history:
            self.count_label.set_text("LIVE • loading matching history…")
        else:
            self._update_live_status()

        self._live_thread = threading.Thread(
            target=self._live_reader, args=(self._live_proc, generation), daemon=True
        )
        self._live_thread.start()
        GLib.idle_add(self._scroll_to_latest)

    def _live_reader(self, proc, generation):
        if not proc or not proc.stdout:
            return
        diagnostic = None
        try:
            for line in proc.stdout:
                if proc is not self._live_proc or generation != self._live_generation:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    # stderr is merged into the pipe so journalctl diagnostics
                    # can be shown if the follower exits unexpectedly.
                    diagnostic = line[:500]
                    continue

                if not isinstance(obj, dict):
                    diagnostic = "Invalid journal record"
                    continue
                ts = obj.get("__REALTIME_TIMESTAMP")
                try:
                    when = datetime.fromtimestamp(int(ts) / 1_000_000).strftime("%Y-%m-%d %H:%M:%S") if ts else "—"
                except Exception:
                    when = "—"
                pri_s = str(obj.get("PRIORITY", "6"))
                pri = int(pri_s) if pri_s.isdigit() else 6
                unit = obj.get("_SYSTEMD_UNIT") or obj.get("SYSLOG_IDENTIFIER") or obj.get("_COMM") or "system"
                msg = str(obj.get("MESSAGE", "")).replace("\x00", " ").replace("\n", " ").strip()
                row = {
                    "time": when,
                    "unit": unit,
                    "level": PRIORITY_LABELS.get(pri_s, "Info"),
                    "priority": pri,
                    "message": msg,
                    "raw": obj,
                }
                self._queue_live(row, generation)
        finally:
            proc.stdout.close()
            try:
                rc = proc.poll()
            except Exception:
                rc = None
            GLib.idle_add(self._live_exited, proc, generation, rc, diagnostic)

    def _queue_live(self, item, generation):
        """A bounded inbox, with one demand-driven UI wakeup per batch."""
        with self._pending_lock:
            if self._destroyed or generation != self._live_generation:
                return
            if len(self._pending_rows) == self.max_rows:
                self._dropped_pending += 1
            self._pending_rows.append(item)
            if not self._drain_source:
                self._drain_source = GLib.timeout_add(100, self._drain_live, generation)

    def _drain_live(self, generation):
        with self._pending_lock:
            self._drain_source = 0
            if self._destroyed or generation != self._live_generation:
                return False
            batch = list(self._pending_rows)
            self._pending_rows.clear()
            self._stream_dropped += self._dropped_pending
            self._dropped_pending = 0
        if not self.live.get_active():
            return False
        if not batch:
            return False
        # Update the model incrementally; never rebuild the table per event.
        overflow = max(0, len(self._all_rows) + len(batch) - self.max_rows)
        self._all_rows.extend(batch)
        del self._all_rows[:-self.max_rows]
        needle = self.search.get_text().strip().lower()
        if overflow:
            # Sorted rows can put expired history anywhere in the model.
            retained = {id(item["raw"]) for item in self._all_rows}
            for index in range(len(self.store) - 1, -1, -1):
                itr = self.store.iter_nth_child(None, index)
                if id(self.store.get_value(itr, self.COL_RAW)) not in retained:
                    self.store.remove(itr)
        shown = 0
        for item in batch:
            if needle and needle not in self._search_text(item):
                continue
            self.store.append(self._display_row(item))
            shown += 1
        while len(self.store) > self.max_rows:
            self.store.remove(self.store.get_iter_first())
        if shown:
            self._scroll_to_latest()
        self._update_live_status()
        return False

    @staticmethod
    def _search_text(item):
        return f"{item['time']} {item['unit']} {item['level']} {item['message']}".lower()

    def _display_row(self, item):
        return [item["time"], item["unit"], item["level"],
                item["message"], item["priority"], item["raw"]]

    def _scroll_to_latest(self):
        if self._destroyed or len(self.store) <= 0:
            return False
        column, order = self.store.get_sort_column_id()
        # Respect a user's source/severity/message sort without jumping the view.
        if column != self.COL_TIME:
            return False
        index = 0 if order == Gtk.SortType.DESCENDING else len(self.store) - 1
        itr = self.store.iter_nth_child(None, index)
        if itr:
            path = self.store.get_path(itr)
            self.tree.scroll_to_cell(path, None, True, 1.0, 0.0)
        return False

    def _live_exited(self, proc, generation, rc, diagnostic):
        if self._destroyed:
            return False
        # An intentional stop invalidates the process/generation before this
        # callback runs, so only unexpected exits reach the user.
        if generation != self._live_generation or proc is not self._live_proc:
            return False
        with self._pending_lock:
            pending = bool(self._pending_rows)
            if self._drain_source:
                GLib.source_remove(self._drain_source)
                self._drain_source = 0
        if pending:
            self._drain_live(generation)
        self._live_proc = None
        if self.live.get_active():
            self.live.set_active(False)
        detail = diagnostic or (f"journalctl exited with status {rc}" if rc is not None else "journalctl stopped")
        self.count_label.set_text("Live feed stopped")
        self.app.window.toast(f"Live feed stopped: {detail}", "error", seconds=6)
        return False

    def _terminate_live_process(self):
        """Stop the follower without touching GTK widgets.

        This is safe to call from the page destroy handler, where child widgets
        may already be invalid GObjects.
        """
        proc = self._live_proc
        self._live_proc = None
        with self._pending_lock:
            self._live_generation += 1
            if self._drain_source:
                GLib.source_remove(self._drain_source)
                self._drain_source = 0
            self._pending_rows.clear()
            self._dropped_pending = 0
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass

    def _on_destroy(self, *_):
        # Never update labels/buttons from a destroy callback: GTK may already
        # have finalized those child GObjects.  Just invalidate callbacks and
        # stop the subprocess.
        self._destroyed = True
        self.column_sizing.cancel_pending()
        if self._reflow_source:
            GLib.source_remove(self._reflow_source)
            self._reflow_source = 0
        self._terminate_live_process()

    def stop_live(self, update_button=True):
        self._terminate_live_process()
        if self._destroyed:
            return

        if update_button and self.live.get_active():
            self.live.set_active(False)
        self._sync_live_button()
        if update_button:
            shown = len(self.store)
            loaded = len(self._all_rows)
            self.count_label.set_text(f"{shown} shown · {loaded} loaded" if shown != loaded else f"{loaded} loaded")
