# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import time
from datetime import datetime

from gi.repository import Gtk, GLib, Gdk

from ..services import resource_snapshot, health_snapshot, human_bytes
from ..widgets import MetricCard, SectionCard, ActivityGraph, DiagnosticRow, StatusPill, ResponsiveColumns


class DashboardPage(Gtk.ScrolledWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.get_style_context().add_class("page-scroll")
        self._busy = False
        self._health_busy = False
        self._health_checked = None
        self._timer = None

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.set_border_width(22)
        self.add(root)

        # Page heading
        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label="Dashboard", xalign=0)
        title.get_style_context().add_class("page-title")
        subtitle = Gtk.Label(label="Overview of your system's health and recent activity.", xalign=0)
        subtitle.set_line_wrap(True)
        subtitle.set_max_width_chars(55)
        subtitle.get_style_context().add_class("page-subtitle")
        title_box.pack_start(title, False, False, 0)
        title_box.pack_start(subtitle, False, False, 0)
        heading.pack_start(title_box, True, True, 0)
        self.refresh_btn = Gtk.Button(label="Refresh Now")
        self.refresh_btn.get_style_context().add_class("secondary-button")
        self.refresh_btn.set_image(Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON))
        self.refresh_btn.set_always_show_image(True)
        self.refresh_btn.connect("clicked", lambda *_: self.refresh())
        heading.pack_end(self.refresh_btn, False, False, 0)
        root.pack_start(heading, False, False, 0)

        # Metric cards
        metrics = Gtk.FlowBox()
        metrics.set_selection_mode(Gtk.SelectionMode.NONE)
        metrics.set_homogeneous(True)
        metrics.set_min_children_per_line(1)
        metrics.set_max_children_per_line(6)
        metrics.set_column_spacing(12)
        metrics.set_row_spacing(12)
        self.cards = {
            "cpu": MetricCard("CPU", "cpu-symbolic", "blue"),
            "memory": MetricCard("Memory", "drive-harddisk-symbolic", "purple"),
            "disk": MetricCard("Disk", "drive-harddisk-symbolic", "green"),
            "services": MetricCard("Services", "emblem-system-symbolic", "orange"),
            "network": MetricCard("Network", "network-wireless-signal-excellent-symbolic", "blue"),
            "logs": MetricCard("Logs (24h)", "text-x-generic-symbolic", "red"),
        }
        for idx, key in enumerate(("cpu", "memory", "disk", "services", "network", "logs")):
            metrics.add(self.cards[key])
        root.pack_start(metrics, False, False, 0)

        # Every top card now works as navigation.
        for key in ("cpu", "memory", "disk", "services"):
            self._bind_click(
                self.cards[key],
                self._open_diagnostics,
                "Open Diagnostics",
                hover_widget=self.cards[key],
            )
        self._bind_click(
            self.cards["network"],
            self._open_network,
            "Open Network monitor",
            hover_widget=self.cards["network"],
        )
        self._bind_click(
            self.cards["logs"],
            lambda: self._open_logs(priority="Error", scope="all"),
            "Open error logs",
            hover_widget=self.cards["logs"],
        )

        # Middle row
        middle = ResponsiveColumns()

        self.health_card = SectionCard(
            "System Health",
            "Essential host information at a glance.",
            "security-high-symbolic",
        )
        self.health_pill = StatusPill("Checking…", "info")
        self.health_card.header_extra.pack_start(self.health_pill, False, False, 0)
        self.health_grid = Gtk.Grid(column_spacing=18, row_spacing=8)
        self.health_grid.set_column_homogeneous(False)
        self.health_labels = {}
        fields = [
            ("Hostname", "hostname"),
            ("Operating System", "os"),
            ("Kernel", "kernel"),
            ("Uptime", "uptime"),
            ("Last Boot", "last_boot"),
            ("CPU Model", "cpu_model"),
            ("Disk Space", "disk_space"),
        ]
        for row, (label, key) in enumerate(fields):
            l = Gtk.Label(label=label, xalign=0)
            l.get_style_context().add_class("muted")
            v = Gtk.Label(label="—", xalign=0)
            v.set_line_wrap(True)
            self.health_grid.attach(l, 0, row, 1, 1)
            self.health_grid.attach(v, 1, row, 1, 1)
            self.health_labels[key] = v
        self.health_card.content.pack_start(self.health_grid, True, True, 0)
        middle.add_card(self._wrap_clickable(self.health_card, self._open_diagnostics, "Open full diagnostics"))

        self.issues_card = SectionCard(
            "Recent Issues",
            "Latest important events from the journal.",
            "dialog-warning-symbolic",
        )
        view_logs = Gtk.Button(label="View All Logs")
        view_logs.get_style_context().add_class("secondary-button")
        view_logs.connect("clicked", lambda *_: self._open_logs(priority="Warning", scope="boot"))
        self.issues_card.header_extra.pack_start(view_logs, False, False, 0)
        self.issues_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.issues_card.content.pack_start(self.issues_list, True, True, 0)
        middle.add_card(self.issues_card)
        root.pack_start(middle, False, False, 0)

        # Lower row
        lower = ResponsiveColumns()

        activity = SectionCard(
            "System Activity",
            "Live CPU usage over the last 60 refreshes.",
            "utilities-system-monitor-symbolic",
        )
        self.graph = ActivityGraph(60)
        activity.content.pack_start(self.graph, True, True, 0)
        lower.add_card(self._wrap_clickable(activity, self._open_diagnostics, "Open resource diagnostics"))

        quick = SectionCard(
            "Quick Diagnostics",
            "Key system checks at a glance.",
            "system-run-symbolic",
        )
        run_full = Gtk.Button(label="Run Full Diagnostics")
        run_full.get_style_context().add_class("secondary-button")
        run_full.connect("clicked", lambda *_: self._open_diagnostics())
        quick.header_extra.pack_start(run_full, False, False, 0)
        self.quick_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        quick.content.pack_start(self.quick_box, True, True, 0)
        lower.add_card(self._wrap_clickable(quick, self._open_diagnostics, "Open full diagnostics"))
        root.pack_start(lower, False, False, 0)

        self.health_updated = Gtk.Label(label="Health checks: waiting for first result", xalign=1)
        self.health_updated.get_style_context().add_class("footer-text")
        root.pack_start(self.health_updated, False, False, 0)

        self.last_updated = Gtk.Label(label="", xalign=1)
        self.last_updated.get_style_context().add_class("footer-text")
        root.pack_start(self.last_updated, False, False, 0)

        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

    def _set_hand_cursor(self, widget):
        def apply_cursor(w):
            try:
                window = w.get_window()
                display = Gdk.Display.get_default()
                if window and display:
                    window.set_cursor(Gdk.Cursor.new_for_display(display, Gdk.CursorType.HAND2))
            except Exception:
                pass
        widget.connect("realize", apply_cursor)

    def _bind_click(self, target, callback, tooltip=None, hover_widget=None):
        target.set_can_focus(True)
        target.add_events(
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.KEY_PRESS_MASK |
            Gdk.EventMask.ENTER_NOTIFY_MASK |
            Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        if tooltip:
            target.set_tooltip_text(tooltip)
        self._set_hand_cursor(target)

        def clicked(_widget, event):
            if getattr(event, "button", 0) == 1:
                callback()
                return True
            return False

        def key_pressed(_widget, event):
            if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
                callback()
                return True
            return False

        def entered(*_args):
            if hover_widget is not None:
                hover_widget.get_style_context().add_class("clickable-hover")
            return False

        def left(*_args):
            if hover_widget is not None:
                hover_widget.get_style_context().remove_class("clickable-hover")
            return False

        target.connect("button-release-event", clicked)
        target.connect("key-press-event", key_pressed)
        target.connect("enter-notify-event", entered)
        target.connect("leave-notify-event", left)
        target.get_style_context().add_class("clickable-card")

    def _wrap_clickable(self, card, callback, tooltip):
        wrapper = Gtk.EventBox()
        wrapper.set_visible_window(True)
        wrapper.add(card)
        self._bind_click(wrapper, callback, tooltip, hover_widget=card)
        return wrapper

    def _open_diagnostics(self):
        self.app.window.show_page("diagnostics")

    def _open_network(self):
        self.app.window.show_page("network")

    def _open_logs(self, priority="All", unit="", scope="boot"):
        self.app.window.show_page("logs")
        logs = self.app.window.pages.get("logs")
        if logs and hasattr(logs, "navigate"):
            logs.navigate(priority=priority, unit=unit, search="", scope=scope)

    def _open_issue(self, item):
        try:
            priority_num = int(item.get("priority", "4"))
        except Exception:
            priority_num = 4
        priority = "Error" if priority_num <= 3 else "Warning"
        unit = item.get("unit") or ""
        if unit == "system":
            unit = ""
        self._open_logs(priority=priority, unit=unit, scope="boot")

    def _on_map(self, *_):
        self.refresh(force_health=False)
        if self._timer is None:
            self._timer = GLib.timeout_add_seconds(
                max(2, int(self.app.config.get("refresh_interval", 5))),
                self._tick,
            )

    def _on_unmap(self, *_):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None

    def _tick(self):
        self.refresh(force_health=False)
        return True

    def refresh(self, force_health=True):
        if not self._busy:
            self._busy = True
            self.refresh_btn.set_sensitive(False)
            self.app.run_async(resource_snapshot, self._apply_resources)
        due = self._health_checked is None or time.monotonic() - self._health_checked >= 60
        if not self._health_busy and (force_health or due):
            self._health_busy = True
            self._health_checked = time.monotonic()
            self.health_updated.set_text("Health checks: checking…")
            self.app.run_async(health_snapshot, self._apply_health)

    def _apply_resources(self, snap, error):
        self._busy = False
        self.refresh_btn.set_sensitive(True)
        if error:
            for key in ("cpu", "memory", "disk"):
                self.cards[key].update("—", "Couldn't check", str(error), "info")
            self.last_updated.set_text("Live metrics unavailable; previous host information may be stale")
            return False
        for key, field, threshold in (("cpu", "cpu", 85), ("memory", "mem_pct", 85), ("disk", "disk_pct", 85)):
            value = snap[field]
            if value is None:
                self.cards[key].update("—", "Couldn't check", "Metric unavailable", "info")
                continue
            state = "error" if key == "disk" and value >= 95 else "warning" if value >= threshold else "ok"
            text = f"{value:.0f}%"
            detail = f"Load: {snap['load']:.2f}"
            if key == "memory":
                text = f"{human_bytes(snap['mem_used'])} / {human_bytes(snap['mem_total'])}"
                detail = f"Swap: {human_bytes(snap['swap_used'])}"
            elif key == "disk":
                detail = f"{human_bytes(snap['disk_free'])} free"
            self.cards[key].update(text, "Critical" if state == "error" else "High" if state == "warning" else "Normal", detail, state)
        if snap["cpu"] is not None:
            self.graph.add_value(snap["cpu"])
        self.health_labels["hostname"].set_text(snap["hostname"])
        self.health_labels["os"].set_text(snap["os"])
        self.health_labels["kernel"].set_text(snap["kernel"])
        self.health_labels["uptime"].set_text(snap["uptime"])
        self.health_labels["last_boot"].set_text(snap["last_boot"])
        self.health_labels["cpu_model"].set_text(snap["cpu_model"])
        self.health_labels["disk_space"].set_text(
            f"{human_bytes(snap['disk_free'])} free of {human_bytes(snap['disk_total'])}"
        )

        self.last_updated.set_text("Live metrics updated " + datetime.now().strftime("%H:%M:%S"))
        self.show_all()
        return False

    def _apply_health(self, snap, error):
        self._health_busy = False
        if error:
            self.health_pill.set_state("Health unavailable", "info")
            self.health_updated.set_text("Health checks failed; previous results may be stale")
            for key in ("services", "network", "logs"):
                self.cards[key].update("—", "Couldn't check", str(error), "info")
            return False
        issues, diags = snap["issues"], snap["diagnostics"]
        failed = snap["failed_services"]
        if failed is None:
            self.cards["services"].update("—", "Couldn't check", snap["check_errors"].get("failed_services", "Unavailable"), "info")
        else:
            count = len(failed)
            self.cards["services"].update(f"{count} failed", "Attention needed" if count else "No failed units", "System service check", "warning" if count else "ok")
        net = snap["network"]
        if net is None or net["connected"] is None:
            self.cards["network"].update("—", "Couldn't check", net.get("route_error", "Network unavailable") if net else "Network unavailable", "info")
        else:
            self.cards["network"].update("Route available" if net["connected"] else "No default route", "DNS resolves" if net["dns"] else "Check DNS", "See Diagnostics for reachability", "ok" if net["connected"] and net["dns"] else "warning")
        errors, warnings = snap["error_count"], snap["warning_count"]
        self.cards["logs"].update("—" if errors is None else f"{errors} errors", "Couldn't check" if errors is None or warnings is None else "Attention needed" if errors or warnings else "No recent issues", "Warnings unavailable" if warnings is None else f"{warnings} warnings", "info" if errors is None or warnings is None else "warning" if errors or warnings else "ok")
        states = [state for state, _, _ in diags]
        incomplete = "info" in states or bool(snap["check_errors"]) or (net is not None and net["connected"] is None)
        if "error" in states:
            self.health_pill.set_state("Problems detected" + (" · partial checks" if incomplete else ""), "error")
        elif "warning" in states:
            self.health_pill.set_state("Warnings detected" + (" · partial checks" if incomplete else ""), "warning")
        elif incomplete:
            self.health_pill.set_state("Health checks incomplete", "info")
        else:
            self.health_pill.set_state("Checks passed", "ok")
        for child in self.issues_list.get_children():
            self.issues_list.remove(child)
        if issues is None:
            empty = Gtk.Label(label="Couldn't check recent issues: " + snap["check_errors"].get("issues", "Unavailable"), xalign=0)
            empty.set_line_wrap(True)
            self.issues_list.pack_start(empty, False, False, 0)
        elif not issues:
            empty = Gtk.Label(label="No recent warning or error events.", xalign=0)
            empty.get_style_context().add_class("empty-text")
            empty.set_margin_top(18)
            empty.set_margin_bottom(18)
            self.issues_list.pack_start(empty, False, False, 0)
        else:
            for item in issues:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
                row.get_style_context().add_class("issue-row")
                row.set_border_width(7)
                state = "error" if item["priority"] in ("0", "1", "2", "3") else "warning"
                icon_name = "dialog-error-symbolic" if state == "error" else "dialog-warning-symbolic"
                icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU)
                icon.get_style_context().add_class(state)
                row.pack_start(icon, False, False, 0)
                tm = Gtk.Label(label=item["time"], xalign=0)
                tm.get_style_context().add_class("muted")
                tm.set_size_request(48, -1)
                row.pack_start(tm, False, False, 0)
                unit = Gtk.Label(label=item["unit"], xalign=0)
                unit.set_ellipsize(3)
                unit.set_max_width_chars(18)
                row.pack_start(unit, False, False, 0)
                msg = Gtk.Label(label=item["message"], xalign=0)
                msg.set_ellipsize(3)
                msg.set_hexpand(True)
                row.pack_start(msg, True, True, 0)
                badge = Gtk.Label(label=item["level"])
                badge.get_style_context().add_class("level-badge")
                badge.get_style_context().add_class(state)
                row.pack_end(badge, False, False, 0)

                click_row = Gtk.EventBox()
                click_row.set_visible_window(True)
                click_row.get_style_context().add_class("issue-clickable")
                click_row.add(row)
                self._bind_click(
                    click_row,
                    lambda current=item: self._open_issue(current),
                    f"Open {item['unit']} logs",
                )
                self.issues_list.pack_start(click_row, False, False, 0)

        for child in self.quick_box.get_children():
            self.quick_box.remove(child)
        for state, title, detail in diags[:7]:
            self.quick_box.pack_start(DiagnosticRow(state, title, detail), False, False, 0)

        self.health_updated.set_text("Health checked " + datetime.now().strftime("%H:%M:%S") + " · refreshes every minute")
        self.show_all()
        return False
