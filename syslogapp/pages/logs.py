# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import csv
import json
import subprocess
import threading
from datetime import datetime

from gi.repository import Gtk, GLib, Gdk, Pango

from ..widgets import WrappingToolbar

from ..services import load_logs, PRIORITY_LABELS


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
        self._live_proc = None
        self._live_thread = None
        self._busy = False
        self._pending_reload = False
        self._suspend_controls = False
        self._all_rows = []
        self._last_pane_width = 0
        self._live_generation = 0
        self._live_error_line = None
        self._live_paused = False
        self._paused_new_count = 0
        self._destroyed = False
        self._row_reflow_source = 0
        self.set_border_width(0)

        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        top.set_border_width(22)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        titlebox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label="Logs", xalign=0)
        title.get_style_context().add_class("page-title")
        sub = Gtk.Label(label="Explore, filter, and follow the system journal.", xalign=0)
        sub.set_line_wrap(True)
        sub.set_max_width_chars(55)
        sub.get_style_context().add_class("page-subtitle")
        titlebox.pack_start(title, False, False, 0)
        titlebox.pack_start(sub, False, False, 0)
        header.pack_start(titlebox, True, True, 0)
        self.count_label = Gtk.Label(label="0 entries")
        self.count_label.get_style_context().add_class("muted")
        header.pack_end(self.count_label, False, False, 0)
        top.pack_start(header, False, False, 0)

        toolbar = WrappingToolbar()
        toolbar.get_style_context().add_class("toolbar-card")
        toolbar.set_border_width(10)

        self.live = Gtk.ToggleButton(label="Live")
        self.live.set_image(Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON))
        self.live.set_always_show_image(True)
        self.live.connect("toggled", self._on_live)
        toolbar.add(self.live)

        self.pause_live = Gtk.ToggleButton(label="Pause")
        self.pause_live.set_image(Gtk.Image.new_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.BUTTON))
        self.pause_live.set_always_show_image(True)
        self.pause_live.set_sensitive(False)
        self.pause_live.set_tooltip_text("Pause automatic scrolling while Live continues collecting events")
        self.pause_live.connect("toggled", self._on_pause_live)
        toolbar.add(self.pause_live)

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
        self.unit.set_width_chars(17)
        self.unit.connect("activate", self._unit_activate)
        toolbar.add(self.unit)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search loaded logs…")
        self.search.set_hexpand(True)
        self.search.connect("search-changed", self._search_changed)
        toolbar.add(self.search)

        refresh = Gtk.Button()
        refresh.add(Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON))
        refresh.set_tooltip_text("Reload logs")
        refresh.connect("clicked", self._refresh_clicked)
        toolbar.add(refresh)

        export = Gtk.Button(label="Export")
        export.set_image(Gtk.Image.new_from_icon_name("document-save-symbolic", Gtk.IconSize.BUTTON))
        export.set_always_show_image(True)
        export.connect("clicked", self._export)
        toolbar.add(export)
        top.pack_start(toolbar, False, False, 0)

        self.pack_start(top, False, False, 0)

        self.pane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.pane.set_wide_handle(True)
        self.pane.set_margin_start(22)
        self.pane.set_margin_end(22)
        self.pane.set_margin_bottom(22)
        self.pane.connect("size-allocate", self._resize_pane)

        # Log list. The column widths are recalculated from the actual
        # TreeView width so the message column grows and shrinks with the window.
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.get_style_context().add_class("section-card")
        self.store = Gtk.ListStore(str, str, str, str, int, object)
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.set_headers_visible(True)
        self.tree.set_enable_search(False)
        self.tree.set_grid_lines(Gtk.TreeViewGridLines.HORIZONTAL)
        # Wrapped cells need variable row heights.  GTK3 defaults to this, but
        # keep it explicit because fixed-height mode will clip wrapped messages.
        self.tree.set_fixed_height_mode(False)
        # Do not use Gtk.TreeView.set_tooltip_column() here. GTK3 feeds that
        # value to Pango as markup, so legitimate journal text containing '&'
        # or '<...>' can trigger markup parser warnings. Provide a plain-text
        # tooltip ourselves instead.
        self.tree.set_has_tooltip(True)
        self.tree.connect("query-tooltip", self._query_log_tooltip)
        self.tree.get_selection().connect("changed", self._selection_changed)
        self.tree.connect("button-press-event", self._tree_button_press)
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
        self.severity_renderer.set_property("ypad", 6)
        severity_col = Gtk.TreeViewColumn("", self.severity_renderer)
        severity_col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        severity_col.set_fixed_width(28)
        severity_col.set_min_width(28)
        severity_col.set_max_width(28)
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
            renderer.set_property("ypad", 6)
            if idx == self.COL_MESSAGE:
                # True responsive text: long messages wrap and the TreeView row
                # grows vertically as its column becomes narrower.
                renderer.set_property("ellipsize", Pango.EllipsizeMode.NONE)
                renderer.set_property("wrap-mode", Pango.WrapMode.WORD_CHAR)
                renderer.set_property("wrap-width", 420)
            else:
                renderer.set_property("ellipsize", Pango.EllipsizeMode.END)

            col = Gtk.TreeViewColumn(title_text, renderer, text=idx)
            if idx == self.COL_TIME:
                col.set_cell_data_func(renderer, self._time_cell_data)
            elif idx == self.COL_LEVEL:
                col.set_cell_data_func(renderer, self._severity_level_cell_data)
            elif idx == self.COL_MESSAGE:
                col.set_cell_data_func(renderer, self._message_cell_data)
            col.set_resizable(False)
            col.set_min_width(55)
            col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            self.tree.append_column(col)
            self.tree_columns[idx] = col
            self.tree_renderers[idx] = renderer

        self.log_scroll = Gtk.ScrolledWindow()
        # No horizontal scrollbar is needed: the message cell wraps instead.
        self.log_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.log_scroll.set_min_content_width(0)
        self.log_scroll.set_hexpand(True)
        self.log_scroll.connect("size-allocate", self._resize_columns)
        self.log_scroll.add(self.tree)
        left.set_hexpand(True)
        left.pack_start(self.log_scroll, True, True, 0)
        self.pane.pack1(left, resize=True, shrink=True)

        # Details panel. It is allowed to resize/shrink too, and its text wraps.
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.details_panel = details
        details.set_no_show_all(True)
        details.get_style_context().add_class("section-card")
        details.set_border_width(18)
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
        dscroll.set_min_content_height(250)
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
        self.pane.pack2(details, resize=True, shrink=True)
        self.pack_start(self.pane, True, True, 0)

        self.connect("map", lambda *_: self.reload())
        self.connect("destroy", self._on_destroy)

    @staticmethod
    def _clamp(value, low, high):
        return max(low, min(high, value))

    @staticmethod
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

        today = datetime.now().date()
        delta_days = (today - dt.date()).days
        clock = dt.strftime("%H:%M:%S")
        if delta_days == 0:
            return f"{clock} · Today"
        if delta_days == 1:
            return f"{clock} · Yesterday"
        if dt.year == datetime.now().year:
            return f"{clock} · {dt.strftime('%b')} {dt.day}"
        return f"{clock} · {dt.strftime('%b')} {dt.day}, {dt.year}"

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

    def _is_dark_theme(self):
        settings = Gtk.Settings.get_default()
        try:
            return bool(settings.get_property("gtk-application-prefer-dark-theme")) if settings else False
        except Exception:
            return False

    def _severity_color(self, priority):
        # Journal priorities: 0 emergency ... 7 debug.  Use a darker palette in
        # light mode and a brighter palette on dark backgrounds.
        dark = self._is_dark_theme()
        if dark:
            palette = {
                0: "#ff4d57", 1: "#ff5962", 2: "#ff6b73", 3: "#ff8188",
                4: "#ffb34c", 5: "#b69cff", 6: "#6aa8ff", 7: "#9aa8b7",
            }
        else:
            palette = {
                0: "#912018", 1: "#b42318", 2: "#c4322a", 3: "#d92d20",
                4: "#b54708", 5: "#6941c6", 6: "#175cd3", 7: "#667085",
            }
        try:
            return palette.get(int(priority), palette[6])
        except Exception:
            return palette[6]

    def _time_cell_data(self, _column, cell, model, itr, _data=None):
        """Give the compact time value enough contrast to scan quickly."""
        cell.set_property("text", model.get_value(itr, self.COL_TIME))
        cell.set_property("weight", Pango.Weight.SEMIBOLD)
        cell.set_property("foreground", "#b8c7dc" if self._is_dark_theme() else "#344054")

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
        # Message text gets a softer version of the severity palette so the
        # content itself is scannable without overwhelming the whole table.
        dark = self._is_dark_theme()
        if dark:
            palette = {
                0: "#ff7a82", 1: "#ff858c", 2: "#ff8f96", 3: "#ff9da3",
                4: "#f6bd67", 5: "#c2afff", 6: "#8fbcff", 7: "#9aa8b7",
            }
        else:
            palette = {
                0: "#8f1d16", 1: "#a9241d", 2: "#b92d25", 3: "#c4322a",
                4: "#9a5200", 5: "#5f46a8", 6: "#245ea8", 7: "#667085",
            }
        try:
            return palette.get(int(priority), palette[6])
        except Exception:
            return palette[6]

    def _message_cell_data(self, _column, cell, model, itr, _data=None):
        priority = model.get_value(itr, self.COL_PRIORITY)
        cell.set_property("foreground", self._message_color(priority))
        cell.set_property("weight", Pango.Weight.BOLD if int(priority) <= 3 else Pango.Weight.NORMAL)

    def _resize_pane(self, _pane, allocation):
        """Keep the log/details split useful as the window changes size."""
        width = int(allocation.width)
        if not self.details_panel.get_visible():
            self._last_pane_width = 0
            return
        if width <= 0 or abs(width - self._last_pane_width) < 18:
            return
        self._last_pane_width = width
        # Roughly 67/33, while preserving a usable details inspector.
        target = int(width * 0.67)
        target = max(360, min(target, max(360, width - 285)))
        if abs(self.pane.get_position() - target) > 10:
            self.pane.set_position(target)

    def _resize_columns(self, _scroll, allocation):
        """Resize and reflow log rows from the visible viewport width.

        Time, Source and Level stay compact.  Message receives all remaining
        space and its CellRenderer wrap-width is changed with the window.
        Changing wrap-width makes GTK recalculate each row's natural height.
        """
        usable = max(360, int(allocation.width) - 8)

        # At narrower sizes the metadata columns give up space first so the
        # actual log message always remains useful.
        if usable < 650:
            time_w = self._clamp(int(usable * 0.24), 125, 150)
            source_w = self._clamp(int(usable * 0.23), 100, 145)
            level_w = self._clamp(int(usable * 0.12), 68, 82)
        elif usable < 900:
            time_w = self._clamp(int(usable * 0.19), 135, 165)
            source_w = self._clamp(int(usable * 0.23), 125, 185)
            level_w = self._clamp(int(usable * 0.11), 72, 92)
        else:
            time_w = self._clamp(int(usable * 0.15), 145, 175)
            source_w = self._clamp(int(usable * 0.21), 150, 225)
            level_w = self._clamp(int(usable * 0.09), 78, 100)

        # Leave a few pixels for TreeView separators / scrollbar allocation.
        message_w = max(120, usable - 28 - time_w - source_w - level_w - 10)
        widths = {
            self.COL_TIME: time_w,
            self.COL_UNIT: source_w,
            self.COL_LEVEL: level_w,
            self.COL_MESSAGE: message_w,
        }

        changed = False
        for idx, width in widths.items():
            col = self.tree_columns.get(idx)
            if col and abs(col.get_fixed_width() - width) > 2:
                col.set_fixed_width(width)
                changed = True

        message_renderer = self.tree_renderers.get(self.COL_MESSAGE)
        if message_renderer is not None:
            wrap_width = max(90, message_w - 18)
            if message_renderer.get_property("wrap-width") != wrap_width:
                message_renderer.set_property("wrap-width", wrap_width)
                changed = True

        if changed:
            # GTK3 caches TreeView row heights aggressively.  queue_resize()
            # alone is not sufficient for rows that were first measured before
            # the Message column wrapped.  Debounce a full model row-change pass
            # so every wrapped row is measured again at the new width.
            self.tree.queue_resize()
            self._schedule_row_height_reflow()

    def _schedule_row_height_reflow(self):
        """Re-measure variable-height log rows after a width change.

        Gtk.TreeView can keep the old one-line height for rows that later wrap
        to two or more lines.  Emitting row_changed invalidates that cached
        geometry.  A short debounce avoids doing this repeatedly while the user
        is actively dragging the window or the paned divider.
        """
        if self._destroyed:
            return
        if self._row_reflow_source:
            try:
                GLib.source_remove(self._row_reflow_source)
            except Exception:
                pass
        self._row_reflow_source = GLib.timeout_add(90, self._reflow_row_heights)

    def _reflow_row_heights(self):
        self._row_reflow_source = 0
        if self._destroyed:
            return False

        # ListStore is flat, so integer paths are the safest way to walk it
        # across PyGObject versions (iter_next() has differing Python binding
        # semantics across GTK releases).
        for index in range(len(self.store)):
            path = Gtk.TreePath.new_from_indices([index])
            try:
                itr = self.store.get_iter(path)
                self.store.row_changed(path, itr)
            except Exception:
                continue

        self.tree.queue_resize()
        self.tree.queue_draw()
        return False

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
            if self.live.get_active() and not self._live_paused:
                GLib.idle_add(self._scroll_to_latest)

    def navigate(self, priority=None, unit=None, search=None, scope=None):
        """Apply dashboard-provided filters and display the relevant logs."""
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
        limit = int(self.app.config.get("log_lines", 400))
        boot_only = self.scope.get_active_id() == "boot"
        prio = self.priority.get_active_text() or "All"
        unit = self.unit.get_text().strip() or None
        self.app.run_async(lambda: load_logs(limit, boot_only, prio, unit), self._loaded)

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
        self._all_rows = list(result)
        self._apply_filter()
        return False

    def _apply_filter(self):
        """Apply the client-side text search to the already-loaded journal set.

        Severity, boot scope and unit are server-side journal filters.  Search is
        intentionally local so typing never restarts journalctl or loses context.
        """
        if self._destroyed:
            return
        needle = self.search.get_text().strip().lower()
        self.store.clear()
        for item in self._all_rows:
            hay = f"{item['time']} {item['unit']} {item['level']} {item['message']}".lower()
            if needle and needle not in hay:
                continue
            self.store.append([
                self._friendly_time(item["time"]), item["unit"], item["level"], item["message"],
                item["priority"], item["raw"]
            ])
        # Initial data may be loaded before the final viewport width is known.
        # Re-measure rows once GTK has had a chance to allocate the log pane.
        self._schedule_row_height_reflow()

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
        if event.button != 3:
            return False
        hit = tree.get_path_at_pos(int(event.x), int(event.y))
        if not hit:
            return False
        path = hit[0]
        tree.get_selection().select_path(path)
        menu = Gtk.Menu()
        actions = [
            ("Copy Event", self._copy_selected),
            ("Copy Message", self._copy_message),
            (None, None),
            ("Show Only This Service", self._show_selected_service),
            ("Show This Severity", self._show_selected_severity),
            ("Clear Filters", self._clear_log_filters),
        ]
        for label, callback in actions:
            if label is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            item = Gtk.MenuItem(label=label)
            item.connect("activate", callback)
            menu.append(item)
        menu.show_all()
        try:
            menu.popup_at_pointer(event)
        except Exception:
            menu.popup(None, None, None, None, event.button, event.time)
        return True

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

    def _selection_changed(self, selection):
        model, itr = selection.get_selected()
        if not itr:
            self.details_panel.set_no_show_all(True)
            self.details_panel.hide()
            self.detail_meta.set_text("Select a log entry to inspect it.")
            self.detail_message.get_buffer().set_text("")
            self._last_pane_width = 0
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
        raw_text = message
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

    def _on_live(self, button):
        if button.get_active():
            self.start_live()
        else:
            self.stop_live()

    def _on_pause_live(self, button):
        if not self.live.get_active():
            if button.get_active():
                button.set_active(False)
            return
        self._live_paused = bool(button.get_active())
        ctx = button.get_style_context()
        if self._live_paused:
            self._paused_new_count = 0
            button.set_label("Resume")
            button.set_image(Gtk.Image.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON))
            ctx.add_class("paused-live")
        else:
            button.set_label("Pause")
            button.set_image(Gtk.Image.new_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.BUTTON))
            ctx.remove_class("paused-live")
            self._paused_new_count = 0
            GLib.idle_add(self._scroll_to_latest)
        self._update_live_status()

    def _update_live_status(self):
        if self._destroyed or not self.live.get_active():
            return
        shown = len(self.store)
        loaded = len(self._all_rows)
        counts = f"{shown} shown" if shown == loaded else f"{shown} shown · {loaded} loaded"
        if self._live_paused:
            suffix = f" • {self._paused_new_count} new" if self._paused_new_count else ""
            self.count_label.set_text(f"LIVE • paused • {counts}{suffix}")
        else:
            self.count_label.set_text(f"LIVE • listening • {counts}")

    def start_live(self, reset_view=False, include_history=False, preserve_pause=False):
        """Start or restart the live journal follower.

        Normal Live activation preserves the already-loaded history and follows
        only new events.  A server-side filter change uses ``include_history``
        so the matching historical entries are emitted first and the process
        then continues following new entries.  This keeps useful context on
        screen instead of leaving an empty table until another event occurs.
        """
        if self._destroyed:
            return
        paused_before = bool(preserve_pause and self._live_paused)
        self.stop_live(update_button=False)
        self._live_generation += 1
        generation = self._live_generation
        self._live_error_line = None
        self._paused_new_count = 0

        if reset_view:
            self._all_rows = []
            self.store.clear()

        line_count = int(self.app.config.get("log_lines", 400)) if include_history else 0
        args = ["journalctl", "--follow", "-n", str(line_count), "--no-pager", "--output=json"]
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
            self._live_proc = subprocess.Popen(
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

        self.live.get_style_context().add_class("active-live")
        self.live.set_label("Live ●")
        self.pause_live.set_sensitive(True)
        self._live_paused = False
        if self.pause_live.get_active():
            self.pause_live.set_active(False)
        self.pause_live.set_label("Pause")
        self.pause_live.set_image(Gtk.Image.new_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.BUTTON))
        self.pause_live.get_style_context().remove_class("paused-live")
        if paused_before:
            self.pause_live.set_active(True)

        if include_history:
            self.count_label.set_text("LIVE • loading matching history…")
        else:
            self._update_live_status()

        self._live_thread = threading.Thread(
            target=self._live_reader, args=(self._live_proc, generation), daemon=True
        )
        self._live_thread.start()
        if not self._live_paused:
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
                GLib.idle_add(self._append_live, row, generation)
        finally:
            try:
                rc = proc.poll()
            except Exception:
                rc = None
            GLib.idle_add(self._live_exited, proc, generation, rc, diagnostic)

    def _append_live(self, item, generation):
        if self._destroyed:
            return False
        if generation != self._live_generation or not self.live.get_active():
            return False
        self._all_rows.append(item)
        if len(self._all_rows) > 1500:
            self._all_rows = self._all_rows[-1200:]

        needle = self.search.get_text().strip().lower()
        hay = f"{item['time']} {item['unit']} {item['level']} {item['message']}".lower()
        if not needle or needle in hay:
            itr = self.store.append([
                self._friendly_time(item["time"]), item["unit"], item["level"], item["message"],
                item["priority"], item["raw"],
            ])
            if len(self.store) > 1200:
                first = self.store.get_iter_first()
                if first:
                    self.store.remove(first)

            # Ensure a newly appended wrapped message receives its natural
            # multi-line height even if TreeView geometry is currently cached.
            path = self.store.get_path(itr)
            if path is not None:
                self.store.row_changed(path, itr)

            if self._live_paused:
                self._paused_new_count += 1
                self._update_live_status()
            else:
                self._update_live_status()
                path = self.store.get_path(itr)
                if path is not None:
                    self.tree.scroll_to_cell(path, None, True, 1.0, 0.0)
        else:
            self._update_live_status()
        return False

    def _scroll_to_latest(self):
        if self._destroyed or len(self.store) <= 0:
            return False
        itr = self.store.iter_nth_child(None, len(self.store) - 1)
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
        self._live_proc = None
        self.live.get_style_context().remove_class("active-live")
        self.live.set_label("Live")
        self.pause_live.set_sensitive(False)
        if self.pause_live.get_active():
            self.pause_live.set_active(False)
        self._live_paused = False
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
        self._live_generation += 1
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
        if self._row_reflow_source:
            try:
                GLib.source_remove(self._row_reflow_source)
            except Exception:
                pass
            self._row_reflow_source = 0
        self._terminate_live_process()

    def stop_live(self, update_button=True):
        self._terminate_live_process()
        if self._destroyed:
            return

        self.live.get_style_context().remove_class("active-live")
        self.live.set_label("Live")
        self.pause_live.set_sensitive(False)
        self._live_paused = False
        self._paused_new_count = 0
        if self.pause_live.get_active():
            self.pause_live.set_active(False)
        self.pause_live.set_label("Pause")
        self.pause_live.set_image(Gtk.Image.new_from_icon_name("media-playback-pause-symbolic", Gtk.IconSize.BUTTON))
        self.pause_live.get_style_context().remove_class("paused-live")
        if update_button and self.live.get_active():
            self.live.set_active(False)
        if update_button:
            shown = len(self.store)
            loaded = len(self._all_rows)
            self.count_label.set_text(f"{shown} shown · {loaded} loaded" if shown != loaded else f"{loaded} loaded")
