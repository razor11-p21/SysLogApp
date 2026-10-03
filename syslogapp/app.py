# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import concurrent.futures
import traceback

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, Gio, GLib

from .config import load_config
from .styles import LIGHT, DARK
from .pages.dashboard import DashboardPage
from .pages.logs import LogsPage
from .pages.network import NetworkPage
from .pages.diagnostics import DiagnosticsPage
from .pages.maintenance import MaintenancePage
from .pages.settings import SettingsPage


class MainWindow(Gtk.ApplicationWindow):
    PAGE_META = {
        "dashboard": ("Dashboard", "view-grid-symbolic"),
        "logs": ("Logs", "text-x-generic-symbolic"),
        "network": ("Network", "network-wired-symbolic"),
        "diagnostics": ("Diagnostics", "system-run-symbolic"),
        "maintenance": ("Maintenance", "applications-engineering-symbolic"),
        "settings": ("Settings", "emblem-system-symbolic"),
    }

    def __init__(self, app):
        super().__init__(application=app, title="SysLogApp")
        self.app = app
        self.set_default_size(1280, 800)
        self.set_size_request(800, 580)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name("utilities-system-monitor")

        overlay = Gtk.Overlay()
        self.add(overlay)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.get_style_context().add_class("app-root")
        self.root = root
        overlay.add(root)

        sidebar = self._build_sidebar()
        self.sidebar = sidebar
        root.pack_start(sidebar, False, False, 0)
        self.connect("size-allocate", self._resize_navigation)

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.pack_start(main, True, True, 0)
        main.pack_start(self._build_topbar(), False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_hhomogeneous(False)
        self.stack.set_vhomogeneous(False)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(150)
        main.pack_start(self.stack, True, True, 0)

        self.pages = {
            "dashboard": DashboardPage(app),
            "logs": LogsPage(app),
            "network": NetworkPage(app),
            "diagnostics": DiagnosticsPage(app),
            "maintenance": MaintenancePage(app),
            "settings": SettingsPage(app),
        }
        for key, page in self.pages.items():
            self.stack.add_named(page, key)

        self.toast_revealer = Gtk.Revealer()
        self.toast_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.toast_revealer.set_halign(Gtk.Align.CENTER)
        self.toast_revealer.set_valign(Gtk.Align.START)
        self.toast_revealer.set_margin_top(76)
        self.toast_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.toast_box.get_style_context().add_class("status-pill")
        self.toast_label = Gtk.Label(label="")
        self.toast_box.pack_start(self.toast_label, False, False, 4)
        self.toast_revealer.add(self.toast_box)
        overlay.add_overlay(self.toast_revealer)
        self._toast_source = None

        self.show_page(app.config.get("start_page", "dashboard"))
        self._install_shortcuts()

    def _build_sidebar(self):
        self.sidebar_text = []
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        side.get_style_context().add_class("sidebar")
        side.set_size_request(245, -1)
        side.set_border_width(12)

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=11)
        brand.set_margin_top(5)
        brand.set_margin_bottom(14)
        pulse = Gtk.Image.new_from_icon_name("utilities-system-monitor-symbolic", Gtk.IconSize.DIALOG)
        pulse.get_style_context().add_class("ok")
        brand.pack_start(pulse, False, False, 2)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title = Gtk.Label(label="SysLogApp", xalign=0)
        title.get_style_context().add_class("sidebar-title")
        sub = Gtk.Label(label="System Insights for Linux", xalign=0)
        sub.get_style_context().add_class("sidebar-subtitle")
        texts.pack_start(title, False, False, 0)
        texts.pack_start(sub, False, False, 0)
        brand.pack_start(texts, True, True, 0)
        self.sidebar_text.append(texts)
        side.pack_start(brand, False, False, 0)

        self.nav_buttons = {}
        for key in ("dashboard", "logs", "network", "diagnostics", "maintenance", "settings"):
            label, icon_name = self.PAGE_META[key]
            btn = Gtk.Button()
            btn.get_style_context().add_class("nav-button")
            btn.set_relief(Gtk.ReliefStyle.NONE)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON), False, False, 3)
            nav_label = Gtk.Label(label=label, xalign=0)
            self.sidebar_text.append(nav_label)
            row.pack_start(nav_label, True, True, 0)
            btn.set_tooltip_text(label)
            btn.add(row)
            btn.connect("clicked", lambda _b, page=key: self.show_page(page))
            side.pack_start(btn, False, False, 0)
            self.nav_buttons[key] = btn

        spacer = Gtk.Box()
        side.pack_start(spacer, True, True, 0)

        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        footer.get_style_context().add_class("sidebar-footer")
        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dot = Gtk.Label(label="●")
        dot.get_style_context().add_class("ok")
        status_row.pack_start(dot, False, False, 0)
        status = Gtk.Label(label="Local Monitoring", xalign=0)
        status.set_markup("<b>Local Monitoring</b>")
        status_row.pack_start(status, True, True, 0)
        footer.pack_start(status_row, False, False, 0)
        self.uptime_label = Gtk.Label(label="Local diagnostics enabled", xalign=0)
        self.uptime_label.get_style_context().add_class("sidebar-subtitle")
        footer.pack_start(self.uptime_label, False, False, 0)
        side.pack_end(footer, False, False, 0)
        self.sidebar_text.append(footer)
        return side

    def _resize_navigation(self, _window, allocation):
        wide = allocation.width >= 1150
        for widget in self.sidebar_text:
            widget.set_no_show_all(not wide)
            widget.set_visible(wide)
        self.sidebar.set_size_request(245 if wide else 72, -1)

    def _build_topbar(self):
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top.get_style_context().add_class("topbar")

        self.global_search = Gtk.SearchEntry()
        self.global_search.set_placeholder_text("Search loaded logs…")
        self.global_search.set_tooltip_text("Search loaded journal entries; adjust history and filters on the Logs page")
        self.global_search.set_width_chars(20)
        self.global_search.set_hexpand(True)
        self.global_search.connect("activate", self._global_search_activate)
        search_shell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        search_shell.get_style_context().add_class("search-shell")
        self.search_target = Gtk.ComboBoxText()
        self.search_target.append("logs", "Logs")
        self.search_target.append("network", "Network")
        self.search_target.set_active_id("logs")
        self.search_target.set_tooltip_text("Choose where to search; existing page filters still apply")
        self.search_target.connect("changed", self._search_target_changed)
        search_shell.pack_start(self.search_target, False, False, 0)
        search_shell.pack_start(self.global_search, True, True, 0)
        top.pack_start(search_shell, True, True, 0)

        hint = Gtk.Label(label="Ctrl+K")
        hint.get_style_context().add_class("muted")
        top.pack_start(hint, False, False, 0)


        refresh = Gtk.Button()
        refresh.set_tooltip_text("Refresh current page")
        refresh.add(Gtk.Image.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON))
        refresh.connect("clicked", self._refresh_current)
        top.pack_end(refresh, False, False, 0)
        return top

    def _install_shortcuts(self):
        accel = Gtk.AccelGroup()
        self.add_accel_group(accel)
        key, mods = Gtk.accelerator_parse("<Control>k")
        accel.connect(key, mods, Gtk.AccelFlags.VISIBLE, lambda *_: self._focus_search())
        key, mods = Gtk.accelerator_parse("<Control>r")
        accel.connect(key, mods, Gtk.AccelFlags.VISIBLE, lambda *_: self._refresh_current())

    def _focus_search(self):
        self.global_search.grab_focus()
        return True

    def _global_search_activate(self, entry):
        text = entry.get_text().strip()
        if not text:
            return
        target = self.search_target.get_active_id() or "logs"
        self.show_page(target)
        page = self.pages[target]
        if target == "network":
            page.view_stack.set_visible_child_name("connections")
        page.search.set_text(text)
        page.search.grab_focus()

    def _search_target_changed(self, combo):
        network = combo.get_active_id() == "network"
        self.global_search.set_placeholder_text("Search network connections…" if network else "Search loaded logs…")
        self.global_search.set_tooltip_text("Search the current network snapshot" if network else "Search loaded journal entries; adjust history and filters on the Logs page")

    def _refresh_current(self, *_):
        key = self.stack.get_visible_child_name()
        page = self.pages.get(key)
        if key == "dashboard" and hasattr(page, "refresh"):
            page.refresh()
        elif key == "logs" and hasattr(page, "reload"):
            page.reload()
        elif key == "network" and hasattr(page, "refresh"):
            page.refresh(force=True)
        elif key == "diagnostics" and hasattr(page, "run"):
            page.run()

    def show_page(self, key):
        if key not in self.pages:
            key = "dashboard"
        self.stack.set_visible_child_name(key)
        for name, btn in self.nav_buttons.items():
            ctx = btn.get_style_context()
            if name == key:
                ctx.add_class("active")
            else:
                ctx.remove_class("active")

    def toast(self, text, state="info", seconds=3):
        self.toast_label.set_text(text)
        ctx = self.toast_box.get_style_context()
        for cls in ("ok", "warning", "error", "info"):
            ctx.remove_class(cls)
        ctx.add_class(state)
        self.toast_revealer.set_reveal_child(True)
        if self._toast_source:
            GLib.source_remove(self._toast_source)
        self._toast_source = GLib.timeout_add_seconds(seconds, self._hide_toast)

    def _hide_toast(self):
        self.toast_revealer.set_reveal_child(False)
        self._toast_source = None
        return False


class SysLogApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="gr.syslogapp.desktop", flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.config = load_config()
        self.window = None
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=5, thread_name_prefix="syslogapp")
        self.css_provider = None

    def do_activate(self):
        if self.window is None:
            self.window = MainWindow(self)
            self.apply_theme()
        self.window.show_all()
        self.window.present()

    def do_shutdown(self):
        try:
            if self.window and "logs" in self.window.pages:
                self.window.pages["logs"].stop_live()
        except Exception:
            pass
        self.executor.shutdown(wait=False, cancel_futures=True)
        Gtk.Application.do_shutdown(self)

    def run_async(self, func, callback):
        future = self.executor.submit(func)

        def done(fut):
            try:
                result = fut.result()
                error = None
            except Exception as exc:
                result = None
                error = exc
            GLib.idle_add(callback, result, error)

        future.add_done_callback(done)

    def apply_theme(self):
        screen = Gdk.Screen.get_default()
        if not screen:
            return
        if self.css_provider:
            Gtk.StyleContext.remove_provider_for_screen(screen, self.css_provider)

        choice = str(self.config.get("theme", "system"))
        settings = Gtk.Settings.get_default()
        if choice == "dark":
            dark = True
        elif choice == "light":
            dark = False
        else:
            theme_name = (settings.get_property("gtk-theme-name") or "").lower() if settings else ""
            dark = "dark" in theme_name

        if settings:
            settings.set_property("gtk-application-prefer-dark-theme", dark)

        provider = Gtk.CssProvider()
        css = DARK if dark else LIGHT
        try:
            provider.load_from_data(css.encode("utf-8"))
        except GLib.Error as exc:
            # A theme parse error should never prevent the application from starting.
            # Fall back to a deliberately conservative GTK3-compatible stylesheet.
            fallback = b"""
            window, .app-root { background: #f5f7fb; color: #131923; font-size: 13px; }
            .sidebar { background: #202832; color: #eef4fa; }
            .sidebar-title { color: #ffffff; font-size: 21px; font-weight: bold; }
            .sidebar-subtitle { color: #aeb9c6; }
            .nav-button { background: transparent; color: #e7edf4; border: 0; }
            .nav-button.active { background: #315f9e; color: #ffffff; }
            .metric-card, .section-card, .toolbar-card { background: #ffffff; border: 1px solid #e3e8ef; border-radius: 10px; }
            .page-title, .section-title, .metric-value { font-weight: bold; }
            .page-title { font-size: 32px; }
            .section-title { font-size: 18px; }
            .metric-value { font-size: 24px; }
            treeview { font-size: 13px; }
            .muted, .footer-text { color: #667085; }
            .ok { color: #17a75b; }
            .warning { color: #d98700; }
            .error { color: #d9363e; }
            .info { color: #2878e8; }
            """
            print("SysLogApp: theme CSS warning:", exc)
            provider = Gtk.CssProvider()
            provider.load_from_data(fallback)
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.css_provider = provider

        if self.window:
            ctx = self.window.root.get_style_context()
            if self.config.get("compact_mode"):
                ctx.add_class("compact")
            else:
                ctx.remove_class("compact")


def main(argv=None):
    app = SysLogApplication()
    return app.run(argv)
