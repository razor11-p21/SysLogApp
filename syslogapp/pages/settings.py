# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
from gi.repository import Gtk

from ..config import save_config
from ..widgets import SectionCard


class SettingsPage(Gtk.ScrolledWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.set_border_width(22)
        self.add(root)

        title = Gtk.Label(label="Settings", xalign=0)
        title.get_style_context().add_class("page-title")
        sub = Gtk.Label(label="Control appearance and refresh behavior.", xalign=0)
        sub.set_line_wrap(True)
        sub.set_max_width_chars(55)
        sub.get_style_context().add_class("page-subtitle")
        root.pack_start(title, False, False, 0)
        root.pack_start(sub, False, False, 0)

        appearance = SectionCard("Appearance", "Keep SysLogApp comfortable in light or dark environments.", "preferences-desktop-theme-symbolic")
        appearance.content.pack_start(self._theme_row(), False, False, 0)
        appearance.content.pack_start(self._compact_row(), False, False, 0)
        root.pack_start(appearance, False, False, 0)

        behavior = SectionCard("Behavior", "Choose sensible defaults without changing system state.", "preferences-system-symbolic")
        behavior.content.pack_start(self._refresh_row(), False, False, 0)
        behavior.content.pack_start(self._start_row(), False, False, 0)
        behavior.content.pack_start(self._log_limit_row(), False, False, 0)
        root.pack_start(behavior, False, False, 0)

        privacy = SectionCard("Privacy", "This release performs all analysis locally.", "security-high-symbolic")
        label = Gtk.Label(
            label="AI integration has been removed from SysLogApp v2. Logs and diagnostics are not sent to OpenRouter or any other external AI service.",
            xalign=0
        )
        label.set_line_wrap(True)
        privacy.content.pack_start(label, False, False, 0)
        root.pack_start(privacy, False, False, 0)

        location = Gtk.Label(label="Settings are stored in ~/.config/syslogapp/config.json", xalign=0)
        location.get_style_context().add_class("footer-text")
        root.pack_start(location, False, False, 0)

    def _setting_row(self, title, detail, widget):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        row.get_style_context().add_class("settings-row")
        row.set_border_width(8)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        name = Gtk.Label(label=title, xalign=0)
        name.get_style_context().add_class("action-title")
        desc = Gtk.Label(label=detail, xalign=0)
        desc.get_style_context().add_class("muted")
        desc.set_line_wrap(True)
        text.pack_start(name, False, False, 0)
        text.pack_start(desc, False, False, 0)
        row.pack_start(text, True, True, 0)
        row.pack_end(widget, False, False, 0)
        return row

    def _theme_row(self):
        combo = Gtk.ComboBoxText()
        combo.append("system", "System")
        combo.append("light", "Light")
        combo.append("dark", "Dark")
        combo.set_active_id(str(self.app.config.get("theme", "system")))
        combo.connect("changed", self._theme_changed)
        return self._setting_row("Theme", "Follow the desktop or force a light/dark SysLogApp theme.", combo)

    def _compact_row(self):
        switch = Gtk.Switch()
        switch.set_active(bool(self.app.config.get("compact_mode", False)))
        switch.connect("notify::active", self._compact_changed)
        return self._setting_row("Compact mode", "Reduce padding for smaller displays.", switch)

    def _refresh_row(self):
        combo = Gtk.ComboBoxText()
        for seconds in (3, 5, 10, 30):
            combo.append(str(seconds), f"Every {seconds} seconds")
        combo.set_active_id(str(self.app.config.get("refresh_interval", 5)))
        combo.connect("changed", self._refresh_changed)
        return self._setting_row("Dashboard refresh", "How often live dashboard metrics are refreshed.", combo)

    def _start_row(self):
        combo = Gtk.ComboBoxText()
        for key, label in (("dashboard", "Dashboard"), ("logs", "Logs"), ("network", "Network"), ("diagnostics", "Diagnostics")):
            combo.append(key, label)
        combo.set_active_id(str(self.app.config.get("start_page", "dashboard")))
        combo.connect("changed", self._start_changed)
        return self._setting_row("Start page", "Page shown when SysLogApp starts.", combo)

    def _log_limit_row(self):
        spin = Gtk.SpinButton.new_with_range(100, 2000, 100)
        spin.set_value(int(self.app.config.get("log_lines", 400)))
        spin.connect("value-changed", self._log_limit_changed)
        return self._setting_row("Log history size", "Maximum journal entries loaded when opening Logs.", spin)

    def _save(self):
        try:
            save_config(self.app.config)
        except Exception as exc:
            self.app.window.toast(f"Unable to save settings: {exc}", "error")

    def _theme_changed(self, combo):
        self.app.config["theme"] = combo.get_active_id() or "system"
        self._save()
        self.app.apply_theme()

    def _compact_changed(self, switch, _pspec):
        self.app.config["compact_mode"] = bool(switch.get_active())
        self._save()
        self.app.apply_theme()

    def _refresh_changed(self, combo):
        try:
            self.app.config["refresh_interval"] = int(combo.get_active_id())
        except Exception:
            return
        self._save()
        self.app.window.toast("Refresh interval saved; it applies on the next page visit", "ok")

    def _start_changed(self, combo):
        self.app.config["start_page"] = combo.get_active_id() or "dashboard"
        self._save()

    def _log_limit_changed(self, spin):
        self.app.config["log_lines"] = int(spin.get_value())
        self._save()
