# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import shutil

from gi.repository import Gtk

from ..services import run_command, run_maintenance_command
from ..widgets import SectionCard, confirm_dialog


class MaintenancePage(Gtk.ScrolledWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._busy = False
        self._buttons = []
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.set_border_width(22)
        self.add(root)

        title = Gtk.Label(label="Maintenance", xalign=0)
        title.get_style_context().add_class("page-title")
        subtitle = Gtk.Label(label="Explicit system maintenance actions with confirmation before changes.", xalign=0)
        subtitle.set_line_wrap(True)
        subtitle.set_max_width_chars(55)
        subtitle.get_style_context().add_class("page-subtitle")
        root.pack_start(title, False, False, 0)
        root.pack_start(subtitle, False, False, 0)

        note = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        note.get_style_context().add_class("info-banner")
        note.set_border_width(12)
        note.pack_start(Gtk.Image.new_from_icon_name("dialog-information-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
        txt = Gtk.Label(label="Administrative actions use PolicyKit (pkexec) when elevated privileges are required. SysLogApp does not collect or store your password.", xalign=0)
        txt.set_line_wrap(True)
        note.pack_start(txt, True, True, 0)
        root.pack_start(note, False, False, 0)

        grid = Gtk.FlowBox()
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_min_children_per_line(1)
        grid.set_max_children_per_line(2)
        grid.set_column_spacing(14)
        grid.set_row_spacing(14)

        cleanup = SectionCard("System Cleanup", "Reduce accumulated caches and old journal data.", "edit-clear-all-symbolic")
        cleanup.content.pack_start(self._action_row(
            "Vacuum old journal logs", "Permanently remove archived journal files older than 7 days.",
            ["journalctl", "--vacuum-time=7d"], elevated=True
        ), False, False, 0)
        cleanup.content.pack_start(self._action_row(
            "Clean APT package cache", "Remove downloaded package archives from the local cache.",
            ["apt-get", "clean"], elevated=True
        ), False, False, 0)
        grid.add(cleanup)

        system = SectionCard("System Services", "Reload or recover commonly used system components.", "emblem-system-symbolic")
        system.content.pack_start(self._action_row(
            "Reload systemd", "Reload unit files after service configuration changes.",
            ["systemctl", "daemon-reload"], elevated=True
        ), False, False, 0)
        system.content.pack_start(self._action_row(
            "Restart NetworkManager", "Restart network management. Active connections may be interrupted.",
            ["systemctl", "restart", "NetworkManager.service"], elevated=True, warning=True
        ), False, False, 0)
        grid.add(system)

        packages = SectionCard("Package Recovery", "Repair interrupted Debian package configuration.", "system-software-install-symbolic")
        packages.content.pack_start(self._action_row(
            "Configure pending packages", "Finish interrupted package setup. This can take several minutes; packages requiring interactive input may need a terminal.",
            ["dpkg", "--configure", "-a"], elevated=True, warning=True
        ), False, False, 0)
        grid.add(packages)

        logs = SectionCard("Journal", "Inspect current journal storage consumption.", "text-x-generic-symbolic")
        logs.content.pack_start(self._action_row(
            "Show journal disk usage", "Read-only: display how much disk space the journal currently uses.",
            ["journalctl", "--disk-usage"], elevated=False
        ), False, False, 0)
        grid.add(logs)

        root.pack_start(grid, False, False, 0)

    def _action_row(self, title, description, command, elevated=False, warning=False):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row.get_style_context().add_class("maintenance-row")
        row.set_border_width(8)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        name = Gtk.Label(label=title, xalign=0)
        name.get_style_context().add_class("action-title")
        desc = Gtk.Label(label=description, xalign=0)
        desc.get_style_context().add_class("muted")
        desc.set_line_wrap(True)
        text.pack_start(name, False, False, 0)
        text.pack_start(desc, False, False, 0)
        row.pack_start(text, True, True, 0)
        btn = Gtk.Button(label="Run")
        btn.get_style_context().add_class("danger-soft" if warning else "secondary-button")
        btn.connect("clicked", lambda *_: self._run_action(title, description, command, elevated))
        available = bool(shutil.which(command[0])) and (not elevated or bool(shutil.which("pkexec")))
        btn.set_sensitive(available)
        if not available:
            btn.set_tooltip_text("Unavailable: required command or pkexec is not installed")
        self._buttons.append((btn, available))
        row.pack_end(btn, False, False, 0)
        return row

    def _run_action(self, title, description, command, elevated):
        if self._busy:
            self.app.window.toast("A maintenance action is already running", "info")
            return
        program = shutil.which(command[0])
        if not program:
            self.app.window.toast(f"Required command is unavailable: {command[0]}", "error")
            return
        if not confirm_dialog(self.app.window, title, description + "\n\nRun this action now?"):
            return
        cmd = [program, *command[1:]]
        if elevated:
            if not shutil.which("pkexec"):
                self.app.window.toast("pkexec is not available on this system", "error")
                return
            cmd = [shutil.which("pkexec"), *cmd]
        self._busy = True
        for button, _available in self._buttons:
            button.set_sensitive(False)
        self.app.window.toast(f"Running: {title}", "info")
        # Administrative operations may legitimately exceed two minutes.
        collect = (lambda: run_maintenance_command(cmd)) if elevated else (lambda: run_command(cmd, timeout=15))
        try:
            self.app.run_async(collect, lambda result, err: self._done(title, result, err))
        except Exception as exc:
            self._done(title, None, exc)

    def _done(self, title, result, error):
        self._busy = False
        for button, available in self._buttons:
            button.set_sensitive(available)
        if error:
            self.app.window.toast(f"{title} failed: {error}", "error")
            return
        rc, out, err = result
        if rc == 126:
            self.app.window.toast(f"{title} cancelled", "info")
            return
        if rc == 0:
            self.app.window.toast(f"{title} completed", "ok")
        else:
            self.app.window.toast(f"{title} returned exit code {rc}", "error")
        self._output_dialog(title, ("\n".join(part for part in (out, err) if part) or "No command output").strip())

    def _output_dialog(self, title, text):
        dlg = Gtk.Dialog(title=title, transient_for=self.app.window, flags=Gtk.DialogFlags.MODAL)
        dlg.add_button("Close", Gtk.ResponseType.CLOSE)
        dlg.set_default_size(760, 430)
        area = dlg.get_content_area()
        area.set_border_width(12)
        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_monospace(True)
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.get_buffer().set_text(text)
        sc = Gtk.ScrolledWindow()
        sc.add(tv)
        area.pack_start(sc, True, True, 0)
        dlg.show_all()
        dlg.run()
        dlg.destroy()
