# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
from gi.repository import Gtk

from ..services import run_diagnostics, run_command
from ..widgets import SectionCard, DiagnosticRow


class DiagnosticsPage(Gtk.ScrolledWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._busy = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        root.set_border_width(22)
        self.add(root)

        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        titlebox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label="Diagnostics", xalign=0)
        title.get_style_context().add_class("page-title")
        sub = Gtk.Label(label="A concise health report for the most common Linux problems.", xalign=0)
        sub.set_line_wrap(True)
        sub.set_max_width_chars(55)
        sub.get_style_context().add_class("page-subtitle")
        titlebox.pack_start(title, False, False, 0)
        titlebox.pack_start(sub, False, False, 0)
        heading.pack_start(titlebox, True, True, 0)
        self.run_btn = Gtk.Button(label="Run Diagnostics")
        self.run_btn.set_image(Gtk.Image.new_from_icon_name("system-run-symbolic", Gtk.IconSize.BUTTON))
        self.run_btn.set_always_show_image(True)
        self.run_btn.get_style_context().add_class("primary-button")
        self.run_btn.connect("clicked", lambda *_: self.run())
        heading.pack_end(self.run_btn, False, False, 0)
        root.pack_start(heading, False, False, 0)

        self.summary = SectionCard("System Health Report", "Checks are read-only unless an action is explicitly offered.", "security-high-symbolic")
        self.results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        placeholder = Gtk.Label(label="Run diagnostics to check services, storage, network, DNS, memory, and recent journal errors.", xalign=0)
        placeholder.set_line_wrap(True)
        placeholder.get_style_context().add_class("empty-text")
        placeholder.set_margin_top(22)
        placeholder.set_margin_bottom(22)
        self.results_box.pack_start(placeholder, False, False, 0)
        self.summary.content.pack_start(self.results_box, True, True, 0)
        root.pack_start(self.summary, False, False, 0)

        grid = Gtk.FlowBox()
        grid.set_selection_mode(Gtk.SelectionMode.NONE)
        grid.set_min_children_per_line(1)
        grid.set_max_children_per_line(2)
        grid.set_column_spacing(14)
        grid.set_row_spacing(14)

        services = SectionCard("Services", "Inspect failed systemd units.", "emblem-system-symbolic")
        b1 = Gtk.Button(label="Show Failed Services")
        b1.connect("clicked", lambda *_: self._show_command("Failed services", ["systemctl", "--failed", "--no-pager"]))
        services.content.pack_start(b1, False, False, 0)
        grid.add(services)

        boot = SectionCard("Boot", "Review high-priority messages from this boot.", "system-reboot-symbolic")
        b2 = Gtk.Button(label="Show Boot Errors")
        b2.connect("clicked", lambda *_: self._show_command("Boot errors", ["journalctl", "-b", "0", "-p", "err", "-n", "120", "--no-pager", "-o", "short-iso"]))
        boot.content.pack_start(b2, False, False, 0)
        grid.add(boot)

        network = SectionCard("Network", "Inspect current addressing and routes.", "network-wired-symbolic")
        b3 = Gtk.Button(label="Show Network State")
        b3.connect("clicked", lambda *_: self._show_multiple("Network state", [
            ("Addresses", ["ip", "-brief", "address"]),
            ("Routes", ["ip", "route"]),
            ("DNS", ["cat", "/etc/resolv.conf"]),
        ]))
        network.content.pack_start(b3, False, False, 0)
        grid.add(network)

        kernel = SectionCard("Kernel", "Review recent kernel warnings and errors.", "utilities-terminal-symbolic")
        b4 = Gtk.Button(label="Show Kernel Warnings")
        b4.connect("clicked", lambda *_: self._show_command("Kernel warnings", ["journalctl", "-k", "-p", "warning", "-n", "150", "--no-pager", "-o", "short-iso"]))
        kernel.content.pack_start(b4, False, False, 0)
        grid.add(kernel)

        root.pack_start(grid, False, False, 0)
        self.connect("map", lambda *_: self.run())

    def run(self):
        if self._busy:
            return
        self._busy = True
        self.run_btn.set_sensitive(False)
        self.run_btn.set_label("Checking…")
        self.app.run_async(run_diagnostics, self._complete)

    def _complete(self, result, error):
        self._busy = False
        self.run_btn.set_sensitive(True)
        self.run_btn.set_label("Run Diagnostics")
        for child in self.results_box.get_children():
            self.results_box.remove(child)
        if error:
            self.results_box.pack_start(DiagnosticRow("error", "Diagnostics failed", str(error)), False, False, 0)
        else:
            for state, title, detail in result:
                self.results_box.pack_start(DiagnosticRow(state, title, detail), False, False, 0)
        self.results_box.show_all()

    def _show_command(self, title, cmd):
        self.app.run_async(lambda: run_command(cmd, timeout=15), lambda result, err: self._command_dialog(title, result, err))

    def _show_multiple(self, title, blocks):
        def collect():
            chunks = []
            for name, cmd in blocks:
                rc, out, err = run_command(cmd, timeout=10)
                chunks.append(f"== {name} ==\n{out or err or '(no output)'}")
            return "\n\n".join(chunks)
        self.app.run_async(collect, lambda result, err: self._text_dialog(title, result if not err else str(err)))

    def _command_dialog(self, title, result, error):
        if error:
            self._text_dialog(title, str(error))
            return
        rc, out, err = result
        self._text_dialog(title, (out or err or "(no output)").strip())

    def _text_dialog(self, title, text):
        dlg = Gtk.Dialog(title=title, transient_for=self.app.window, flags=Gtk.DialogFlags.MODAL)
        dlg.add_button("Close", Gtk.ResponseType.CLOSE)
        dlg.set_default_size(850, 520)
        box = dlg.get_content_area()
        box.set_border_width(12)
        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_monospace(True)
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.get_buffer().set_text(text)
        sc = Gtk.ScrolledWindow()
        sc.add(tv)
        box.pack_start(sc, True, True, 0)
        dlg.show_all()
        dlg.run()
        dlg.destroy()
