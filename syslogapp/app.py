# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Event-driven GTK journal and network viewer."""
import concurrent.futures
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, Gio, GLib, Pango

from .config import load_config, save_config, normalized
from .styles import TERMINAL
from .pages.logs import LogsPage


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="SysLogApp")
        self.app = app
        state = normalized(app.config)['window']
        width, height = state.get('width', 1100), state.get('height', 700)
        display = self.get_display()
        if display:
            monitor = display.get_primary_monitor()
            if monitor:
                area = monitor.get_workarea()
                width, height = min(width, max(640, area.width)), min(height, max(480, area.height))
        self._normal_size = (width, height)
        self._maximized = bool(state.get('maximized', False))
        self._fullscreen = False
        self._layout_saved = False
        self.set_default_size(width, height)
        if self._maximized:
            self.maximize()
        self.connect('configure-event', self._configured)
        self.connect('window-state-event', self._window_state)
        self.set_size_request(640, 480)
        self.set_icon_from_file(str(Path(__file__).with_name("assets") / "syslogapp.svg"))
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.root.get_style_context().add_class("app-root")
        self.add(self.root)
        self.active_host = None
        self._host_context = None
        self._connecting_host = None
        self._connect_cancelled = False
        self._host_selection_guard = False
        self._profile_index = None
        self.pages = {"logs": LogsPage(app)}
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.append_page(self.pages["logs"], Gtk.Label(label="System logs"))
        self.network_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.notebook.append_page(self.network_host, Gtk.Label(label="Network"))
        self._page_keys = ('logs', 'network', 'overview', 'maintenance', 'help')
        self._hosts = {'network': self.network_host}
        for key, title in (('overview', 'Overview'), ('maintenance', 'Maintenance'), ('help', 'Help')):
            host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self._hosts[key] = host
            self.notebook.append_page(host, Gtk.Label(label=title))
        self._visible_page_key = "logs"
        self.notebook.connect("switch-page", self._switch_page)
        self.notebook.connect_after("switch-page", self._finish_page_switch)
        self.connect('delete-event', self._delete_event)
        host_bar = Gtk.Box(spacing=8)
        host_bar.set_border_width(5)
        show_hosts = Gtk.ToggleButton(label='Hosts')
        self.show_hosts = show_hosts
        show_hosts.set_active(True)
        host_bar.pack_start(show_hosts, False, False, 0)
        self.host_label = Gtk.Label(label='Local host', xalign=0)
        self.host_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.host_label.get_style_context().add_class('terminal-title')
        host_bar.pack_start(self.host_label, True, True, 0)
        self.root.pack_start(host_bar, False, False, 0)
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.sidebar_revealer = Gtk.Revealer()
        self.sidebar_revealer.set_transition_type(Gtk.RevealerTransitionType.NONE)
        self.sidebar_revealer.set_reveal_child(True)
        self.sidebar_revealer.set_no_show_all(True)
        self.sidebar_revealer.show()
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.sidebar.set_size_request(160, -1)
        self.sidebar.set_border_width(6)
        self.sidebar.get_style_context().add_class('host-sidebar')
        self.host_list = Gtk.ListBox()
        self.host_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        host_scroll = Gtk.ScrolledWindow()
        host_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        host_scroll.add(self.host_list)
        self.sidebar.pack_start(host_scroll, True, True, 0)
        self.add_host_button = Gtk.Button(label='+ SSH host')
        self.add_host_button.connect('clicked', self._add_host)
        self.sidebar.pack_start(self.add_host_button, False, False, 0)
        self.connect_host_button = Gtk.Button(label='Connect')
        self.connect_host_button.connect('clicked', self._connect_clicked)
        self.sidebar.pack_start(self.connect_host_button, False, False, 0)
        self.disconnect_host_button = Gtk.Button(label='Disconnect')
        self.disconnect_host_button.connect('clicked', self._disconnect_clicked)
        self.sidebar.pack_start(self.disconnect_host_button, False, False, 0)
        self.edit_host_button = Gtk.Button(label='Edit host')
        self.edit_host_button.connect('clicked', self._edit_host)
        self.sidebar.pack_start(self.edit_host_button, False, False, 0)
        self.remove_host_button = Gtk.Button(label='Remove host')
        self.remove_host_button.connect('clicked', self._remove_host)
        self.sidebar.pack_start(self.remove_host_button, False, False, 0)
        self.sidebar_revealer.add(self.sidebar)
        self.sidebar.show_all()
        body.pack_start(self.sidebar_revealer, False, False, 0)
        body.pack_start(self.notebook, True, True, 0)
        self.root.pack_start(body, True, True, 0)
        show_hosts.connect('toggled', lambda button:self.sidebar_revealer.set_visible(button.get_active()))
        self.host_list.connect('row-selected', self._host_selected)
        self._rebuild_hosts()
        # Inline status avoids animated overlays and recurring status timers.
        self.status = Gtk.Label(label="F1 help  ·  F5 refresh  ·  Ctrl+F search  ·  F6 live  ·  F7 pause", xalign=0)
        self.status.set_ellipsize(Pango.EllipsizeMode.END)
        self.status.set_selectable(True)
        self.status.get_style_context().add_class("status-line")
        self.root.pack_end(self.status, False, False, 0)
        accel = Gtk.AccelGroup()
        self.add_accel_group(accel)
        for shortcut, callback in (("<Control>k", self._focus_search),
                                   ("<Control>f", self._focus_search),
                                   ("<Control>r", self._refresh_current),
                                   ("F1", lambda: self._select_tab(4)),
                                   ("F5", self._refresh_current),
                                   ("F6", self._toggle_live),
                                   ("F7", self._toggle_pause),
                                   ("<Control>c", self._copy_current),
                                   ("<Control>a", self._select_all_current),
                                   ("<Control>b", self._toggle_hosts),
                                   ("Escape", self._close_details)):
            key, mods = Gtk.accelerator_parse(shortcut)
            accel.connect(key, mods, Gtk.AccelFlags.VISIBLE, lambda *_, cb=callback: cb())
        for number in range(5):
            key, mods = Gtk.accelerator_parse(f'<Control>{number + 1}')
            accel.connect(key, mods, Gtk.AccelFlags.VISIBLE,
                          lambda *_, index=number: self._select_tab(index))

    def _switch_page(self, _notebook, _page, number):
        key = self._page_keys[number]
        previous = self.pages.get(self._visible_page_key)
        if key != self._visible_page_key and previous is not None:
            self._reset_page_selection(previous)
        self._visible_page_key = key
        if key in self.pages:
            return
        if key == 'network':
            from .pages.network import NetworkPage
            page = NetworkPage(self._host_context or self.app)
        elif key == 'overview':
            from .pages.overview import OverviewPage
            page = OverviewPage(self._host_context or self.app)
        elif key == 'maintenance':
            from .pages.maintenance import MaintenancePage
            page = MaintenancePage(self._host_context or self.app)
        elif key == 'help':
            from .pages.help import HelpPage
            page = HelpPage(self._host_context or self.app)
        else:
            return
        self.pages[key] = page
        self._hosts[key].pack_start(page, True, True, 0)
        self._hosts[key].show_all()

    def _finish_page_switch(self, _notebook, _page, number):
        page = self.pages.get(self._page_keys[number])
        if page is None or self.app._closing:
            return
        # GTK restores the previous focus during its default switch handler.
        # Move it to a control and clear selection synchronously, before paint.
        control = next((getattr(page, name) for name in
                        ('live', 'refresh_button', 'refresh_btn', 'text')
                        if getattr(page, name, None) is not None), None)
        if control is not None and page.get_mapped():
            control.grab_focus()
        self._reset_page_selection(page)

    def _reset_page_selection(self, page):
        if self.app._closing or page not in self.pages.values():
            return False
        access = getattr(page, 'text_access', None)
        if access is not None:
            access.clear_selection()

        def clear(widget):
            if isinstance(widget, Gtk.TreeView):
                widget.get_selection().unselect_all()
            elif isinstance(widget, (Gtk.Label, Gtk.Entry)):
                widget.select_region(0, 0)
            elif isinstance(widget, Gtk.TextView):
                buffer = widget.get_buffer()
                cursor = buffer.get_iter_at_mark(buffer.get_insert())
                buffer.select_range(cursor, cursor)
            elif isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    clear(child)

        clear(page)
        return False

    def _rebuild_hosts(self):
        self._host_selection_guard = True
        for child in self.host_list.get_children():
            self.host_list.remove(child)
        for index, label in [(None, 'Local host')] + [(i, profile['label']) for i, profile in enumerate(self.app.config.get('hosts', []))]:
            row = Gtk.ListBoxRow()
            row.profile_index = index
            text = Gtk.Label(label=label, xalign=0)
            text.set_ellipsize(Pango.EllipsizeMode.END)
            text.set_max_width_chars(18)
            text.set_margin_top(7)
            text.set_margin_bottom(7)
            row.add(text)
            if index is not None:
                profile = self.app.config['hosts'][index]
                row.set_tooltip_text(f"{profile['username']}@{profile['hostname']}:{profile['port']}")
            self.host_list.add(row)
        rows = self.host_list.get_children()
        position = self._profile_index + 1 if self._profile_index is not None else 0
        self.host_list.show_all()
        self.host_list.select_row(rows[min(position, len(rows)-1)])
        self._host_selection_guard = False
        self._host_buttons()

    def _host_buttons(self):
        selected = self.host_list.get_selected_row()
        remote = selected is not None and selected.profile_index is not None
        connecting = self._connecting_host is not None
        self.host_list.set_sensitive(not connecting)
        self.add_host_button.set_sensitive(not connecting)
        self.edit_host_button.set_sensitive(remote and not connecting)
        self.remove_host_button.set_sensitive(remote and not connecting)
        self.connect_host_button.set_sensitive(remote or connecting)
        self.connect_host_button.set_label('Cancel connection' if connecting else
                                           'Reconnect' if self.active_host else 'Connect')
        self.disconnect_host_button.set_sensitive(self.active_host is not None and not connecting)

    def _maintenance_busy(self):
        page = self.pages.get('maintenance')
        return page is not None and page._busy

    def _host_selected(self, _list, row):
        if self._host_selection_guard or row is None:
            return
        if self._maintenance_busy():
            self.toast('Wait for maintenance to finish before changing hosts.')
            self._rebuild_hosts()
            return
        index = row.profile_index
        if index is None:
            if self.active_host:
                self._use_host(None, None)
            self._host_buttons()
        elif index != self._profile_index or self.active_host is None:
            self._connect_profile(index)

    def _save_profiles(self):
        try:
            save_config(self.app.config)
        except OSError as exc:
            self.toast('Could not save host profiles: ' + str(exc))

    def _add_host(self, *_):
        if self._maintenance_busy():
            self.toast('Wait for maintenance before changing hosts.')
            return
        from .host_ui import edit_host
        profile = edit_host(self)
        if profile:
            if len(self.app.config.get('hosts', [])) >= 64:
                self.toast('Up to 64 SSH profiles can be saved.')
                return
            self.app.config.setdefault('hosts', []).append(profile)
            self._save_profiles()
            self._rebuild_hosts()
            self._connect_profile(len(self.app.config['hosts'])-1)

    def _edit_host(self, *_):
        row = self.host_list.get_selected_row()
        if row is None or row.profile_index is None or self._maintenance_busy():
            return
        from .host_ui import edit_host
        index = row.profile_index
        profile = edit_host(self, self.app.config['hosts'][index])
        if profile:
            self.app.config['hosts'][index] = profile
            self._save_profiles()
            self._rebuild_hosts()
            self._connect_profile(index)

    def _remove_host(self, *_):
        row = self.host_list.get_selected_row()
        if row is None or row.profile_index is None or self._maintenance_busy():
            return
        index = row.profile_index
        if self.active_host:
            self._use_host(None, None)
        del self.app.config['hosts'][index]
        self._save_profiles()
        self._rebuild_hosts()

    def _connect_clicked(self, *_):
        if self._connecting_host:
            self._connect_cancelled = True
            self._connecting_host.close()
            return
        if self._maintenance_busy():
            self.toast('Wait for maintenance to finish before disconnecting.')
            return
        if self.active_host:
            self._connect_profile(self._profile_index)
            return
        row = self.host_list.get_selected_row()
        if row is not None and row.profile_index is not None:
            self._connect_profile(row.profile_index)

    def _disconnect_clicked(self, *_):
        if self._maintenance_busy():
            self.toast('Wait for maintenance to finish before disconnecting.')
            return
        if self.active_host and not self._connecting_host:
            self._use_host(None, None)

    def _connect_profile(self, index):
        if self._connecting_host or self._maintenance_busy():
            return
        from .hosts import SSHHost
        host = SSHHost(self.app.config['hosts'][index])
        self._connecting_host = host
        self._connect_cancelled = False
        self.notebook.set_sensitive(False)
        self.host_label.set_text('Connecting: ' + host.target)
        self._host_buttons()
        def connected(result, error):
            if self.app._closing:
                host.close()
                return False
            self._connecting_host = None
            self.notebook.set_sensitive(True)
            if self._connect_cancelled or not host.connected:
                error = error or RuntimeError('Connection cancelled')
            if error:
                host.close()
                self.host_label.set_text(self.active_host.target if self.active_host else 'Local host')
                self.toast('SSH: ' + str(error))
                if not self._connect_cancelled:
                    dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                        message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE,
                        text='Could not connect to ' + host.target)
                    dialog.format_secondary_text(str(error)[:2000])
                    dialog.run()
                    dialog.destroy()
                self._rebuild_hosts()
            else:
                self._use_host(host, index)
                missing = [name for name in ('journalctl','ip','ss','python3') if not host.which(name)]
                self.toast('Connected to ' + host.target + (' · Missing: ' + ', '.join(missing) if missing else ''))
            self._host_buttons()
            return False
        self.app.run_async(host.connect, connected)

    def _use_host(self, host, index):
        from .hosts import HostContext
        # Persist widths without marking this running window as already closed.
        for key, page in self.pages.items():
            sizing = getattr(page, 'column_sizing', None)
            if sizing:
                self.app.config.setdefault('columns', {})[key] = sizing.saved_widths()
        if self._host_context:
            self._host_context.active = False
        self.pages['logs'].stop_live()
        if 'network' in self.pages:
            self.pages['network'].stop_live()
        if self.active_host:
            self.active_host.close()
        self.active_host = host
        self._profile_index = index
        self._host_context = HostContext(self.app, host)
        selected_page = max(0, self.notebook.get_current_page())
        # Only one host owns widgets/history and an SSH session at a time.
        self.notebook.handler_block_by_func(self._switch_page)
        self.notebook.hide()
        for page in self.pages.values():
            page.destroy()
        while self.notebook.get_n_pages():
            self.notebook.remove_page(0)
        self.pages = {'logs': LogsPage(self._host_context)}
        self.notebook.append_page(self.pages['logs'], Gtk.Label(label='System logs'))
        self._hosts = {}
        for key, title in (('network','Network'),('overview','Overview'),('maintenance','Maintenance'),('help','Help')):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self._hosts[key] = box
            self.notebook.append_page(box, Gtk.Label(label=title))
        self.network_host = self._hosts['network']
        for position in range(self.notebook.get_n_pages()):
            self.notebook.get_nth_page(position).show_all()
        self.notebook.set_current_page(selected_page)
        self.notebook.handler_unblock_by_func(self._switch_page)
        self._switch_page(self.notebook, self.notebook.get_nth_page(selected_page), selected_page)
        self._finish_page_switch(self.notebook, self.notebook.get_nth_page(selected_page), selected_page)
        self.notebook.show()
        self.host_label.set_text(host.target if host else 'Local host')
        self._rebuild_hosts()

    def close_hosts(self):
        if self._host_context:
            self._host_context.active = False
        if self._connecting_host:
            self._connecting_host.close()
        if self.active_host:
            self.active_host.close()

    def _current_page(self):
        key = self._page_keys[max(0, self.notebook.get_current_page())]
        return self.pages.get(key, self.pages['logs'])

    def _focus_search(self):
        search = getattr(self._current_page(), 'search', None)
        if search is not None:
            search.grab_focus()
        return True

    def _refresh_current(self):
        page = self._current_page()
        if hasattr(page, 'refresh_available'):
            page.refresh_available()
        elif hasattr(page, '_refresh_clicked'):
            page._refresh_clicked()
        return True

    def _select_tab(self, index):
        self.notebook.set_current_page(index)
        return True

    def _toggle_hosts(self):
        self.show_hosts.set_active(not self.show_hosts.get_active())
        return True

    def _toggle_live(self):
        button = getattr(self._current_page(), 'live', None)
        if button is not None and button.get_sensitive():
            button.set_active(not button.get_active())
        return True

    def _toggle_pause(self):
        page = self._current_page()
        if hasattr(page, 'toggle_pause'):
            page.toggle_pause()
            return True
        return True

    def _copy_current(self):
        focus = self.get_focus()
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        if isinstance(focus, Gtk.TextView):
            focus.get_buffer().copy_clipboard(clipboard)
        elif isinstance(focus, Gtk.Entry):
            focus.copy_clipboard()
        elif isinstance(focus, Gtk.Label):
            bounds = focus.get_selection_bounds()
            if bounds:
                start, end = bounds
                clipboard.set_text(focus.get_text()[start:end], -1)
        elif isinstance(focus, Gtk.TreeView):
            access = getattr(self._current_page(), 'text_access', None)
            model, itr = focus.get_selection().get_selected()
            if access and (access.selected_text() or itr is not None):
                clipboard.set_text(access.selected_text() or access.row_text(model[itr]), -1)
        return True

    def _select_all_current(self):
        focus = self.get_focus()
        if isinstance(focus, Gtk.TextView):
            buffer = focus.get_buffer()
            buffer.select_range(*buffer.get_bounds())
        elif isinstance(focus, (Gtk.Entry, Gtk.Label)):
            focus.select_region(0, -1)
        elif isinstance(focus, Gtk.TreeView):
            access = getattr(self._current_page(), 'text_access', None)
            if access:
                access.select_all()
        return True

    def _close_details(self):
        page = self._current_page()
        access = getattr(page, 'text_access', None)
        if access and access.clear_selection():
            return True
        tree = getattr(page, 'tree', None)
        if tree is not None:
            tree.get_selection().unselect_all()
        return True

    def _configured(self, _window, event):
        if not self._maximized and not self._fullscreen and self.get_mapped():
            self._normal_size = (event.width, event.height)
        return False

    def _window_state(self, _window, event):
        self._maximized = bool(event.new_window_state & Gdk.WindowState.MAXIMIZED)
        self._fullscreen = bool(event.new_window_state & Gdk.WindowState.FULLSCREEN)
        return False

    def _save_layout(self):
        if self._layout_saved:
            return
        config = normalized(self.app.config)
        width, height = self._normal_size
        if self.get_mapped() and not self._maximized and not self._fullscreen:
            width, height = self.get_size()
        config['window'] = {'width': width, 'height': height, 'maximized': self._maximized}
        for key, page in self.pages.items():
            sizing = getattr(page, 'column_sizing', None)
            if sizing is not None:
                config['columns'][key] = sizing.saved_widths()
        try:
            save_config(config)
        except OSError as exc:
            self.toast(f'Could not save window layout: {exc}', 'error')
            return
        self.app.config = config
        self._layout_saved = True

    def _delete_event(self, *_):
        maintenance = self.pages.get('maintenance')
        if maintenance is not None and maintenance._busy:
            self.toast('Maintenance is running. Wait for it to finish before closing.')
            return True
        self._save_layout()
        self.close_hosts()
        return False

    def toast(self, text, state="info", seconds=3):
        self.status.set_text(str(text))
        self.status.set_tooltip_text(str(text))


class SysLogApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="gr.syslogapp.desktop", flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.config = load_config()
        self.window = None
        # Historical reads are serialized; following has its own blocking reader.
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="syslogapp")
        self.css_provider = None
        self._closing = False

    def do_activate(self):
        if self.window is None:
            self.apply_theme()
            self.window = MainWindow(self)
        self.window.show_all()
        self.window.present()

    def do_shutdown(self):
        self._closing = True
        if self.window:
            self.window._save_layout()
            self.window.close_hosts()
            self.window.pages["logs"].stop_live()
            if "network" in self.window.pages:
                self.window.pages["network"].stop_live()
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
            if not self._closing:
                GLib.idle_add(callback, result, error)

        future.add_done_callback(done)

    def apply_theme(self):
        screen = Gdk.Screen.get_default()
        if not screen:
            return
        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property("gtk-application-prefer-dark-theme", True)
        provider = Gtk.CssProvider()
        provider.load_from_data(TERMINAL.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.css_provider = provider


def main(argv=None):
    return SysLogApplication().run(argv)
