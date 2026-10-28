# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import json
import subprocess
import threading
from collections import deque, defaultdict
from datetime import datetime, timedelta
from functools import lru_cache

from gi.repository import Gtk, GLib, Gdk, Pango

from ..widgets import set_cell_style, CommandBar, action_menu, ColumnSizing, TableTextAccess, selectable_readouts
from ..config import column_widths
from ..log_hover import LogHover
from ..log_view import LogFilter, groups, display_settings
from ..config import log_capacity
from ..sorting import log_sort_key, compare, natural_key, timestamp_key

from ..services import (load_logs, journal_row, bound_rows, row_bytes, bounded_lines,
                        MAX_RECORD_BYTES, MAX_HISTORY_BYTES, JOURNAL_OUTPUT_FIELDS)


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
    COL_EVENTS = 6

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
        self._history_query = {}
        self._before = None
        self._memory_omitted = 0
        self._log_error = None
        self._last_successful_read = None
        self._last_pane_width = 0
        self._live_generation = 0
        self._destroyed = False
        self.max_rows = log_capacity(app.config)
        self._pending_lock = threading.Lock()
        self._pending_rows = deque(maxlen=self.max_rows)
        self._pending_bytes = 0
        self._dropped_oversized = 0
        self._drain_source = 0
        self._dropped_pending = 0
        self._stream_dropped = 0
        self._mapped_once = False
        self._reflow_source = 0
        self._view_hidden = False
        self._view_dirty = False
        self._hidden_scroll = 0
        self.set_border_width(0)

        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        top.set_border_width(8)
        self.count_label = Gtk.Label(label="0 entries")
        self.count_label.get_style_context().add_class("muted")
        self.count_label.set_line_wrap(True)
        self.count_label.set_max_width_chars(42)

        self.command_bar = CommandBar()
        toolbar = self.command_bar.primary
        toolbar.set_border_width(2)

        self.live = Gtk.ToggleButton(label="Paused")
        self.live.set_image(Gtk.Image.new_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.BUTTON))
        self.live.get_style_context().add_class("paused-live")
        self.live.set_always_show_image(True)
        self.live.connect("toggled", self._on_live)
        toolbar.add(self.live)

        self.scope = Gtk.ComboBoxText()
        self.scope.append("boot", "Current Boot")
        self.scope.append("previous", "Previous Boot")
        self.scope.append("all", "Recent History")
        self.scope.set_active_id("boot")
        self.scope.connect("changed", self._filter_changed)
        toolbar.add(self.scope)
        history = Gtk.Button(label='History…')
        history.connect('clicked', self._history_dialog)
        toolbar.add(history)
        self.older = Gtk.Button(label='Older')
        self.older.connect('clicked', self._load_older)
        toolbar.add(self.older)

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
        refresh.connect("clicked", self._refresh_clicked)
        self.command_bar.secondary.pack_start(refresh, False, False, 0)

        self.more_actions = action_menu([('Save view…', self._save_view), ('Saved views & bookmarks…', self._saved_items), ('Bookmark selected event…', self._bookmark_selected), ('Return to recent logs', self._recent_logs), ('Export logs…', self._export), ('Fit columns', self._fit_columns)])
        self.command_bar.secondary.pack_start(self.more_actions, False, False, 0)
        self.history_limit = Gtk.SpinButton.new_with_range(100, 2000, 100)
        self.history_limit.set_numeric(True)
        self.history_limit.set_width_chars(4)
        self.history_limit.set_value(self.max_rows)
        limit_box = Gtk.Box(spacing=5)
        limit_box.pack_start(Gtk.Label(label='Log limit'), False, False, 0)
        limit_box.pack_start(self.history_limit, False, False, 0)
        toolbar.add(limit_box)
        self.history_limit.connect('value-changed', self._limit_changed)
        toolbar.add(self.count_label)
        top.pack_start(self.command_bar, False, False, 0)

        self.display_filters = Gtk.Expander(label='Display filters')
        filter_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.exclude_units = Gtk.Entry()
        self.exclude_units.set_placeholder_text('Hide services: exact names, comma-separated (up to 32)')
        self.exclude_units.set_max_length(8192)
        self.exclude_message = Gtk.SearchEntry()
        self.exclude_message.set_placeholder_text('Hide messages containing this text (literal, case-insensitive)')
        self.exclude_message.set_max_length(512)
        self.group_repeats = Gtk.CheckButton(label='Group consecutive repeats')
        self.exclude_units.connect('changed', self._display_filter_changed)
        self.exclude_message.connect('search-changed', self._display_filter_changed)
        self.group_repeats.connect('toggled', self._display_filter_changed)
        for label, entry in (('Hide services', self.exclude_units), ('Hide message text', self.exclude_message)):
            row = Gtk.Box(spacing=8)
            row.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
            row.pack_start(entry, True, True, 0)
            filter_box.pack_start(row, False, False, 0)
        actions = Gtk.Box(spacing=8)
        actions.pack_start(self.group_repeats, False, False, 0)
        clear = Gtk.Button(label='Clear display filters')
        clear.connect('clicked', self._clear_display_filters)
        actions.pack_start(clear, False, False, 0)
        filter_box.pack_start(actions, False, False, 0)
        self.display_filters.add(filter_box)
        top.pack_start(self.display_filters, False, False, 0)

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
        self.store = Gtk.ListStore(str, str, str, str, int, object, object)
        for column in range(4):
            self.store.set_sort_func(column, self._compare_rows, column)
        self.store.set_sort_column_id(self.COL_TIME, Gtk.SortType.ASCENDING)
        self.tree = Gtk.TreeView(model=self.store)
        # Column widths settle separately; only newly exposed areas need to
        # repaint during viewport resizing. Content changes still invalidate rows.
        self.tree.set_redraw_on_allocate(False)
        self.tree.set_headers_visible(True)
        self.tree.set_enable_search(False)
        self.tree.set_grid_lines(Gtk.TreeViewGridLines.NONE)
        # Wrapped messages need variable heights; history remains bounded.
        self.tree.set_fixed_height_mode(False)
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
        self.severity_renderer.set_property("text", "●")
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

            # Time text is formatted by its cell callback; avoid setting the
            # canonical value first and invalidating the layout twice.
            col = Gtk.TreeViewColumn(title_text, renderer, **({} if idx == self.COL_TIME else {'text': idx}))
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
        self.log_scroll.set_overlay_scrolling(False)
        # Automatic horizontal policy lets GTK shrink the viewport below the
        # table's previous natural width when the window becomes narrower.
        self.log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.log_scroll.set_min_content_width(0)
        self.log_scroll.set_hexpand(True)
        self.log_scroll.connect("size-allocate", self._resize_columns)
        self.log_scroll.add(self.tree)
        self.log_hover = LogHover(self.tree, self._hover_text)
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
             ('Bookmark event…', self._bookmark_selected),
             ('Show Only This Service', self._show_selected_service),
             ('Show This Severity', self._show_selected_severity),
             ('Hide This Service', self._hide_selected_service),
             ('Hide This Message', self._hide_selected_message),
             ('Clear Filters', self._clear_log_filters)], connect=False,
            on_select=self._hold_for_selection, cell_data=self._selection_cell_data,
            format_value=lambda index, value: self._friendly_time(value) if index == 0 else value)
        self.log_scroll.set_margin_bottom(12)
        self.detail_message.set_bottom_margin(16)
        selectable_readouts(self)
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)
        self.connect("destroy", self._on_destroy)

    def _selection_cell_data(self, column, cell, model, itr, index):
        if index == self.COL_TIME:
            self._time_cell_data(column, cell, model, itr)
        elif index == self.COL_LEVEL:
            self._severity_level_cell_data(column, cell, model, itr)
        elif index == self.COL_MESSAGE:
            self._message_cell_data(column, cell, model, itr)

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
        text = self._friendly_time(model.get_value(itr, self.COL_TIME))
        if cell.get_property('text') != text:
            cell.set_property('text', text)
        set_cell_style(cell, self._severity_color(model.get_value(itr, self.COL_PRIORITY)), Pango.Weight.SEMIBOLD)

    def _severity_indicator_cell_data(self, _column, cell, model, itr, _data=None):
        priority = model.get_value(itr, self.COL_PRIORITY)
        set_cell_style(cell, self._severity_color(priority), Pango.Weight.NORMAL)

    def _severity_level_cell_data(self, _column, cell, model, itr, _data=None):
        priority = model.get_value(itr, self.COL_PRIORITY)
        set_cell_style(cell, self._severity_color(priority), Pango.Weight.BOLD if int(priority) <= 4 else Pango.Weight.NORMAL)

    def _message_color(self, priority):
        try:
            return MESSAGE_COLORS.get(int(priority), MESSAGE_COLORS[6])
        except (ValueError, TypeError):
            return MESSAGE_COLORS[6]

    def _message_cell_data(self, _column, cell, model, itr, _data=None):
        priority = model.get_value(itr, self.COL_PRIORITY)
        set_cell_style(cell, self._message_color(priority), Pango.Weight.BOLD if int(priority) <= 3 else Pango.Weight.NORMAL)

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
        if self._destroyed or self._view_hidden:
            return
        if self._reflow_source:
            GLib.source_remove(self._reflow_source)
        self._reflow_source = GLib.timeout_add(50, self._reflow_rows)

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
        self._view_hidden = False
        if self._view_dirty:
            self._apply_filter()
            if self.live.get_active():
                self._scroll_to_latest()
            else:
                GLib.idle_add(self._restore_hidden_scroll)
        if not self._mapped_once:
            self._mapped_once = True
            self.reload()

    def _on_unmap(self, *_):
        if self._destroyed:
            return
        self._view_hidden = True
        self._view_dirty = True
        self._hidden_scroll = self.log_scroll.get_vadjustment().get_value()
        if self._reflow_source:
            GLib.source_remove(self._reflow_source)
            self._reflow_source = 0
        # Release model references to old entries; only bounded history remains.
        self.store.clear()

    def _restore_hidden_scroll(self):
        if not self._destroyed and not self._view_hidden and not self.live.get_active():
            self.log_scroll.get_vadjustment().set_value(self._hidden_scroll)
        return False

    def _display_settings(self):
        return display_settings(dict(exclude_units=self.exclude_units.get_text().split(','),
                                     exclude_message=self.exclude_message.get_text(),
                                     group_repeats=self.group_repeats.get_active()))

    def _log_filter(self):
        return LogFilter(search=self.search.get_text(), **self._display_settings())

    def _display_filter_changed(self, *_):
        if self._suspend_controls:
            return
        settings = self._display_settings()
        count = len(settings['exclude_units']) + bool(settings['exclude_message'])
        suffix = f' · {count} exclusions' if count else ''
        if settings['group_repeats']:
            suffix += ' · repeats grouped'
        if len([unit for unit in self.exclude_units.get_text().split(',') if unit.strip()]) > 32:
            suffix += ' · only first 32 services applied'
        self.display_filters.set_label('Display filters' + suffix)
        self._apply_filter()

    def _clear_display_filters(self, *_):
        self._suspend_controls = True
        self.exclude_units.set_text('')
        self.exclude_message.set_text('')
        self.group_repeats.set_active(False)
        self._suspend_controls = False
        self._display_filter_changed()

    def _hide_selected_service(self, *_):
        values = self._selected_values()
        if values:
            units = self._display_settings()['exclude_units']
            if values[self.COL_UNIT] not in units:
                if len(units) >= 32:
                    self.app.window.toast('Up to 32 service exclusions; clear one first.', 'info')
                    return
                self.exclude_units.set_text(', '.join(units + [values[self.COL_UNIT]]))

    def _hide_selected_message(self, *_):
        values = self._selected_values()
        if values:
            message = str(values[self.COL_RAW].get('MESSAGE', values[self.COL_MESSAGE]))
            if len(message) > 512 or '\n' in message or '\r' in message:
                self.display_filters.set_expanded(True)
                self.exclude_message.grab_focus()
                self.app.window.toast('Enter a single-line message fragment up to 512 characters.', 'info')
                return
            self.exclude_message.set_text(message)
            self._display_filter_changed()

    def _limit_changed(self, spin):
        value = max(100, min(2000, spin.get_value_as_int()))
        if value == self.max_rows:
            return
        self.max_rows = value
        self.app.config['log_lines'] = value
        with self._pending_lock:
            pending = list(self._pending_rows)
            self._dropped_pending += max(0, len(pending) - value)
            self._pending_rows = deque(pending[-value:], maxlen=value)
            self._pending_bytes = sum(row_bytes(row) for row in self._pending_rows)
        retained = bound_rows(self._all_rows, value)
        self._all_rows = list(retained)
        self._before = None
        self._apply_filter()
        if self.host and not getattr(self.host, 'connected', True):
            return
        if self.live.get_active():
            self.start_live(reset_view=True, include_history=True)
        else:
            self.reload()

    def _mark_fresh(self):
        self._log_error = None
        self._last_successful_read = datetime.now().astimezone().isoformat(timespec='seconds')
        self._remote_stale = False
        if self.host and hasattr(self.app.window, 'remote_fresh'):
            self.app.window.remote_fresh('logs', self.host)

    def _save_view(self, *_):
        from ..saved_ui import ask_name
        from ..investigations import save_view
        name = ask_name(self, 'Save view')
        if name is None:
            return
        try:
            save_view(self.host, name, {'scope': self.scope.get_active_id(),
                      'priority': self.priority.get_active_text(), 'unit': self.unit.get_text(),
                      'search': self.search.get_text(), 'history': self._history_query,
                      **self._display_settings()})
            self.app.window.toast('View saved for this host', 'ok')
        except (OSError, ValueError) as exc:
            self.app.window.toast(str(exc), 'error')

    def _bookmark_selected(self, *_):
        values = self._selected_values()
        if not values:
            self.app.window.toast('Select an event to bookmark', 'info')
            return
        self._hold_for_selection()
        from ..saved_ui import ask_name
        from ..investigations import bookmark
        name = ask_name(self, 'Bookmark event', str(values[self.COL_UNIT]))
        if name is None:
            return
        row = dict(zip(('time', 'unit', 'level', 'message', 'priority', 'raw'), values))
        try:
            bookmark(self.host, name, row)
            self.app.window.toast('Event bookmarked locally for this host', 'ok')
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
        if values['page'] != 'logs':
            return
        self.live.set_active(False)
        self._suspend_controls = True
        try:
            self.scope.set_active_id(values['scope'])
            self.priority.set_active(('All', 'Critical', 'Error', 'Warning', 'Notice', 'Info', 'Debug').index(values['priority']))
            self.unit.set_text(values['unit'])
            self.search.set_text(values['search'])
            self.exclude_units.set_text(', '.join(values['exclude_units']))
            self.exclude_message.set_text(values['exclude_message'])
            self.group_repeats.set_active(values['group_repeats'])
            self._history_query = values['history']
            self._before = None
        finally:
            self._suspend_controls = False
        self._display_filter_changed()
        self.reload()

    def _history_dialog(self, *_):
        dialog = Gtk.Dialog(title='Search journal history', transient_for=self.app.window,
                            modal=True)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Search', Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        note = Gtk.Label(label='Search runs on the selected host only when you press Search.\n'
                              'Results are bounded pages. Dates use this computer’s local timezone.\n'
                              'Boot scope: ' + (self.scope.get_active_text() or 'Current Boot') + '.', xalign=0)
        note.set_line_wrap(True)
        box.pack_start(note, False, False, 0)
        period = Gtk.ComboBoxText()
        for label in ('Last 15 minutes', 'Last hour', 'Last 24 hours', 'Last 7 days', 'Custom range', 'Any time'):
            period.append_text(label)
        period.set_active(2)
        box.pack_start(period, False, False, 0)
        start, end, message = Gtk.Entry(), Gtk.Entry(), Gtk.Entry()
        start.set_placeholder_text('From: YYYY-MM-DD HH:MM:SS')
        end.set_placeholder_text('Until: YYYY-MM-DD HH:MM:SS')
        message.set_placeholder_text('Message contains (optional, case insensitive)')
        message.set_text(self._history_query.get('match', ''))
        for entry in (start, end, message):
            entry.set_width_chars(38)
            box.pack_start(entry, False, False, 0)
        def change(*_):
            start.set_sensitive(period.get_active() == 4)
            end.set_sensitive(period.get_active() == 4)
        period.connect('changed', change)
        change()
        error = Gtk.Label(xalign=0)
        error.set_line_wrap(True)
        box.pack_start(error, False, False, 0)
        dialog.show_all()
        try:
            while dialog.run() == Gtk.ResponseType.OK:
                try:
                    index = period.get_active()
                    query = {'match': message.get_text().strip()}
                    if index == 4:
                        first = datetime.strptime(start.get_text().strip(), '%Y-%m-%d %H:%M:%S')
                        last = datetime.strptime(end.get_text().strip(), '%Y-%m-%d %H:%M:%S')
                        if first > last:
                            raise ValueError('From must be earlier than Until.')
                    elif index < 4:
                        last = datetime.now()
                        first = last - timedelta(minutes=(15, 60, 1440, 10080)[index])
                    if index != 5:
                        query.update(since='@' + str(int(first.timestamp())),
                                     until='@' + str(int(last.timestamp())))
                except ValueError:
                    error.set_text('Enter valid dates as YYYY-MM-DD HH:MM:SS, with From before Until.')
                    continue
                self._history_query = query
                self._before = None
                self.search.set_text('')
                self.live.set_active(False)
                self.reload()
                break
        finally:
            dialog.destroy()

    def _recent_logs(self, *_):
        self.live.set_active(False)
        self._history_query = {}
        self._before = None
        self._suspend_controls = True
        self.scope.set_active_id('boot')
        self._suspend_controls = False
        self.reload()

    def _load_older(self, *_):
        if self._busy or not self._all_rows:
            return
        cursor = self._all_rows[0]['raw'].get('__CURSOR')
        if not cursor:
            self.app.window.toast('No journal cursor available for this page', 'info')
            return
        self.live.set_active(False)
        self._before = cursor
        self.reload()

    def _budget_status(self):
        result = f' · {self._memory_omitted} omitted by byte limits' if self._memory_omitted else ''
        if self._log_error or getattr(self, '_remote_stale', False):
            result += ' · Stale remote data' if getattr(self, '_remote_stale', False) else ' · Stale data'
            if self._last_successful_read:
                result += ' · last read ' + self._last_successful_read[11:19]
        return result

    def _filter_changed(self, *_):
        if self._suspend_controls:
            return
        self._before = None
        if self.scope.get_active_id() == 'previous' and self.live.get_active():
            self.live.set_active(False)
        if self.live.get_active():
            # Rehydrate matching history first, then keep following.  Using
            # journalctl -f -n <limit> avoids the old behavior where selecting a
            # filter emptied the view and showed only events created afterward.
            self.start_live(reset_view=True, include_history=True)
        else:
            self.reload()

    def _unit_activate(self, *_):
        self._before = None
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
        self._history_query = {}
        self._before = None
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
        options = dict(self._history_query)
        if self.host:
            options['host'] = self.host
        if self._before:
            options['before'] = self._before
        if self.scope.get_active_id() == 'previous':
            options['boot'] = -1
        self.app.run_async(lambda: load_logs(limit, boot_only, prio, unit, **options), self._loaded)

    def _loaded(self, result, error):
        if self._destroyed:
            return False
        self._busy = False
        if self._pending_reload:
            self._pending_reload = False
            self.reload()
            return False
        # A historical load may finish just after Live was enabled.  Do not let
        # that stale result replace a stream that is already running.
        if self.live.get_active():
            return False
        if error:
            self._log_error = str(error)[:1000]
            self.count_label.set_text("Load failed" + self._budget_status())
            self.app.window.toast(str(error), "error")
            return False
        if self._before and not result:
            message = ('Older entries exceeded byte limits; narrow the filters.'
                       if getattr(result, 'omitted', 0) else 'No older entries match these filters')
            self.app.window.toast(message, 'info')
            self._apply_filter()
            return False
        self._mark_fresh()
        self._all_rows = bound_rows(result, self.max_rows, newest=not bool(self._before))
        self._memory_omitted = self._all_rows.omitted
        self._all_rows = list(self._all_rows)
        self._apply_filter()
        GLib.idle_add(self._scroll_to_latest)
        return False

    def _apply_filter(self, force=False):
        """Apply the client-side text search to the already-loaded journal set.

        Severity, boot scope and unit are server-side journal filters.  Search is
        intentionally local so typing never restarts journalctl or loses context.
        """
        if self._destroyed:
            return
        if self._view_hidden and not force:
            self._view_dirty = True
            return
        self._view_dirty = False
        filters = self._log_filter()
        column, order = self.store.get_sort_column_id()
        self.store.clear()
        if column is not None:
            self.store.set_sort_column_id(Gtk.TREE_SORTABLE_UNSORTED_SORT_COLUMN_ID, order)
        try:
            if self.group_repeats.get_active():
                for events in groups(self._all_rows, filters):
                    self.store.append(self._group_row(events))
            else:
                for item in self._all_rows:
                    if filters.matches(item):
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

        if not self.live.get_active():
            suffix = self._budget_status()
            if self._history_query:
                suffix += ' · history search'
            if self._before:
                suffix += ' · older page'
            self.count_label.set_text(self.count_label.get_text() + suffix)
        if self.group_repeats.get_active() and not self.live.get_active():
            self.count_label.set_text(f'{len(self.store)} rows · {self._shown_event_count()} events · '
                                     f'{len(self._all_rows)} loaded' + suffix)

    def _shown_event_count(self):
        return sum(len(row[self.COL_EVENTS]) if row[self.COL_EVENTS] else 1 for row in self.store)

    def _group_row(self, events):
        values = self._display_row(events[0])
        if len(events) > 1:
            values[self.COL_MESSAGE] = f'[×{len(events)}] ' + events[0]['message']
        values[self.COL_EVENTS] = events
        return values

    def _sync_grouped_view(self, filters):
        """Update changed repeat rows; do not rebuild the GTK model per batch."""
        existing = defaultdict(deque)
        for row in self.store:
            existing[id(row[self.COL_RAW])].append(row.iter)
        for events in groups(self._all_rows, filters):
            values = self._group_row(events)
            candidates = existing[id(values[self.COL_RAW])]
            if candidates:
                itr = candidates.popleft()
                old = self.store.get_value(itr, self.COL_EVENTS)
                if old is None or len(old) != len(events) or any(a is not b for a, b in zip(old, events)):
                    self.store.set(itr, self.COL_MESSAGE, values[self.COL_MESSAGE], self.COL_EVENTS, events)
            else:
                self.store.append(values)
        for candidates in existing.values():
            for itr in candidates:
                self.store.remove(itr)

    def _selected_values(self):
        model, itr = self.tree.get_selection().get_selected()
        if not itr:
            return None
        return [model.get_value(itr, i) for i in range(6)]

    def _copy_message(self, *_):
        values = self._selected_values()
        if not values:
            return
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(str(values[self.COL_RAW].get('MESSAGE', values[self.COL_MESSAGE])), -1)
        self.app.window.toast("Message copied to clipboard", "ok")

    def _show_selected_service(self, *_):
        values = self._selected_values()
        if not values:
            return
        unit = values[self.COL_UNIT]
        if not unit or unit == "system":
            return
        self.unit.set_text(unit)
        self._before = None
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
        self._history_query = {}
        self._before = None
        self._suspend_controls = True
        try:
            self.priority.set_active(0)
            self.unit.set_text("")
            self.search.set_text("")
            self.exclude_units.set_text('')
            self.exclude_message.set_text('')
            self.group_repeats.set_active(False)
        finally:
            self._suspend_controls = False
        self._display_filter_changed()
        if self.live.get_active():
            self.start_live(reset_view=True, include_history=True)
        else:
            self.reload()

    def _tree_button_press(self, tree, event):
        self.log_hover.dismiss()
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


    def _hover_text(self, model, itr):
        when = self._exact_time(model.get_value(itr, self.COL_RAW), model.get_value(itr, self.COL_TIME))
        unit = model.get_value(itr, self.COL_UNIT)
        level = model.get_value(itr, self.COL_LEVEL)
        message = model.get_value(itr, self.COL_MESSAGE)
        return f'{when}  ·  {level}\n{unit}\n\n{message}' if message else ''

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
        events = model.get_value(itr, self.COL_EVENTS)
        if events and len(events) > 1:
            raw_text = f'{len(events)} consecutive events (original timestamps):\n\n' + '\n\n'.join(
                f"{self._exact_time(event['raw'], event['time'])}\n{event['message']}" for event in events)
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
        events = model.get_value(itr, self.COL_EVENTS)
        if events and len(events) > 1:
            text = '\n\n'.join(f"{self._exact_time(event['raw'], event['time'])}  {event['unit']}  {event['level']}\n{event['message']}"
                                 for event in events)
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        self.app.window.toast("Event copied to clipboard", "ok")

    def _export(self, *_):
        from ..export_ui import open_export
        open_export(self)

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
            historical = bool(self._history_query or self._before or self.scope.get_active_id() == 'previous' or getattr(self, '_remote_stale', False))
            self._history_query = {}
            self._before = None
            if self.scope.get_active_id() == 'previous':
                self._suspend_controls = True
                self.scope.set_active_id('boot')
                self._suspend_controls = False
            self.store.set_sort_column_id(self.COL_TIME, Gtk.SortType.ASCENDING)
            if historical:
                self.start_live(reset_view=True, include_history=True)
            else:
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
        if self.group_repeats.get_active():
            counts = f'{shown} rows · {self._shown_event_count()} events · {loaded} loaded'
        if self._stream_dropped:
            counts += f" · {self._stream_dropped} skipped during bursts"
        self.count_label.set_text(f"LIVE • listening • {counts}" + self._budget_status())

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
            self._memory_omitted = 0
            self._all_rows = []
            self.store.clear()

        line_count = self.max_rows if include_history else 0
        args = ["journalctl", "--follow", "-n", str(line_count), "--no-pager", "--output=json", '--output-fields=' + JOURNAL_OUTPUT_FIELDS]
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
                bufsize=0,
                start_new_session=True,
            )
        except Exception as exc:
            self.app.window.toast(f"Unable to start live journal: {exc}", "error")
            self._log_error = str(exc)[:1000]
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
            for line in bounded_lines(proc.stdout):
                if proc is not self._live_proc or generation != self._live_generation:
                    break
                if line is None:
                    self._queue_live(None, generation)
                    continue
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
                row = journal_row(obj)
                self._queue_live(row, generation)
        finally:
            proc.stdout.close()
            try:
                rc = proc.poll()
            except Exception:
                rc = None
            if rc == 255 and self.host and hasattr(self.host, 'check_transport'):
                self.host.check_transport()
            GLib.idle_add(self._live_exited, proc, generation, rc, diagnostic)

    def _queue_live(self, item, generation):
        """A bounded inbox, with one demand-driven UI wakeup per batch."""
        with self._pending_lock:
            if self._destroyed or generation != self._live_generation:
                return
            if item is None:
                self._dropped_oversized += 1
            else:
                cost = row_bytes(item)
                if cost > MAX_RECORD_BYTES:
                    self._dropped_oversized += 1
                    item = None
            if item is not None and len(self._pending_rows) == self.max_rows:
                self._dropped_pending += 1
                self._pending_bytes -= row_bytes(self._pending_rows[0])
            if item is not None:
                self._pending_rows.append(item)
                self._pending_bytes += cost
                while self._pending_rows and self._pending_bytes > MAX_HISTORY_BYTES:
                    self._pending_bytes -= row_bytes(self._pending_rows.popleft())
                    self._dropped_oversized += 1
            if not self._drain_source:
                self._drain_source = GLib.timeout_add(100, self._drain_live, generation)

    def _drain_live(self, generation):
        with self._pending_lock:
            self._drain_source = 0
            if self._destroyed or generation != self._live_generation:
                return False
            batch = list(self._pending_rows)
            self._pending_rows.clear()
            self._pending_bytes = 0
            self._memory_omitted += self._dropped_oversized
            self._dropped_oversized = 0
            self._stream_dropped += self._dropped_pending
            self._dropped_pending = 0
        if not self.live.get_active():
            return False
        if not batch:
            self._update_live_status()
            return False
        self._mark_fresh()
        # Update the model incrementally; never rebuild the table per event.
        self._all_rows.extend(batch)
        trimmed = bound_rows(self._all_rows, self.max_rows)
        byte_evictions = max(0, len(self._all_rows) - self.max_rows)
        self._memory_omitted += max(0, trimmed.omitted - byte_evictions)
        overflow = len(self._all_rows) - len(trimmed)
        self._all_rows = list(trimmed)
        if self._view_hidden:
            self._view_dirty = True
            return False
        filters = self._log_filter()
        if self.group_repeats.get_active():
            self._sync_grouped_view(filters)
            self._scroll_to_latest()
            self._update_live_status()
            return False
        if overflow:
            # Sorted rows can put expired history anywhere in the model.
            retained = {id(item["raw"]) for item in self._all_rows}
            for index in range(len(self.store) - 1, -1, -1):
                itr = self.store.iter_nth_child(None, index)
                if id(self.store.get_value(itr, self.COL_RAW)) not in retained:
                    self.store.remove(itr)
        shown = 0
        retained = {id(item["raw"]) for item in self._all_rows}
        for item in batch:
            if id(item["raw"]) not in retained:
                continue
            if not filters.matches(item):
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
                item["message"], item["priority"], item["raw"], None]

    def _scroll_to_latest(self):
        if self._destroyed or self._view_hidden or len(self.store) <= 0:
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
            pending = bool(self._pending_rows) or bool(self._dropped_oversized)
            if self._drain_source:
                GLib.source_remove(self._drain_source)
                self._drain_source = 0
        if pending:
            self._drain_live(generation)
        self._live_proc = None
        if self.live.get_active():
            self.live.set_active(False)
        detail = diagnostic or (f"journalctl exited with status {rc}" if rc is not None else "journalctl stopped")
        self._log_error = detail[:1000]
        self.count_label.set_text("Live feed stopped" + self._budget_status())
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
            self._pending_bytes = 0
            self._dropped_oversized = 0
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
        self.text_access._destroy()
        self.column_sizing.dispose()
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
            self.count_label.set_text((f"{shown} shown · {loaded} loaded" if shown != loaded else f"{loaded} loaded") + self._budget_status())
