# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import threading
import time
from datetime import datetime
import sys
import shutil
from pathlib import Path
from gi.repository import Gtk, GLib, Pango, Gdk
from ..maintenance import ACTIONS, Action, resolve, run_action, vacuum_action
from ..logrotate_config import render
from ..widgets import TableTextAccess, selectable_readouts, action_menu


class MaintenancePage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.app = app
        self.host = getattr(app, "host", None)
        self._sudo_password = None
        self._probing = False
        self._busy = self._destroyed = False
        self._buttons = []
        self.set_border_width(8)
        hint = Gtk.Label(label='Actions run only when selected. Changes require confirmation and administrator authentication.', xalign=0)
        hint.set_line_wrap(True)
        hint.set_max_width_chars(1)
        hint.get_style_context().add_class('muted')
        self.pack_start(hint, False, False, 0)
        refresh = Gtk.Button(label='Refresh availability')
        self.refresh_button = refresh
        refresh.set_halign(Gtk.Align.START)
        refresh.connect('clicked', self.refresh_available)
        self.pack_start(refresh, False, False, 0)
        self.target = self.host.target if self.host else 'Local host'
        self._availability_labels = {}
        self._output_lock = threading.Lock()
        self._pending_output = ''
        self._flush_source = self._progress_source = 0
        self._after_action = None
        application = getattr(app, 'application', app)
        if not hasattr(application, 'maintenance_history'):
            application.maintenance_history = []
        self._history = application.maintenance_history
        self.split = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.split.set_wide_handle(True)
        controls_scroll = Gtk.ScrolledWindow()
        controls_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        diagnostics = self._group(content, 'Diagnostics')
        self._add_action(diagnostics, ACTIONS[0])
        cleanup = self._group(content, 'Cleanup')
        self._add_action(cleanup, ACTIONS[1], self._review_vacuum)
        settings = Gtk.Box(spacing=6)
        self.vacuum_mode = Gtk.ComboBoxText()
        self.vacuum_mode.append('age', 'Retention age (days)')
        self.vacuum_mode.append('size', 'Storage target (MiB)')
        self.vacuum_mode.set_active_id('age')
        self.vacuum_value = Gtk.SpinButton.new_with_range(1, 102400, 1)
        self.vacuum_value.set_value(7)
        self.vacuum_mode.connect('changed', self._vacuum_mode_changed)
        self.vacuum_value.connect('value-changed', self._vacuum_changed)
        settings.pack_start(self.vacuum_mode, False, False, 0)
        settings.pack_start(self.vacuum_value, False, False, 0)
        cleanup.pack_start(settings, False, False, 0)
        self.usage = self._label('Journal usage: not checked. Usage is read before cleanup review.')
        cleanup.pack_start(self.usage, False, False, 0)
        self._add_action(cleanup, ACTIONS[2])
        services = self._group(content, 'Services')
        self._add_action(services, ACTIONS[3])
        self._rotation_editor(content)
        advanced = Gtk.Expander(label='Advanced · Services and Packages')
        advanced.set_expanded(False)
        advanced_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._add_action(self._group(advanced_box, 'Services'), ACTIONS[4])
        self._add_action(self._group(advanced_box, 'Packages'), ACTIONS[5])
        advanced.add(advanced_box)
        content.pack_start(advanced, False, False, 0)
        self.advanced = advanced
        controls_scroll.add(content)
        self.split.pack1(controls_scroll, resize=True, shrink=True)
        output_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        output_header = Gtk.Box(spacing=6)
        self.status = self._label('Idle · no checks or actions run in the background')
        self.status.get_style_context().add_class('muted')
        output_header.pack_start(self.status, True, True, 0)
        self.output_menu = action_menu([('Copy output', self._copy_output),
                                        ('Save output…', self._save_output), ('Clear output', self._clear_output)])
        output_header.pack_start(self.output_menu, False, False, 0)
        output_box.pack_start(output_header, False, False, 0)
        target = self._label('Current target: ' + self.target)
        target.get_style_context().add_class('terminal-title')
        output_box.pack_start(target, False, False, 0)
        self.history = Gtk.ComboBoxText()
        self.history.set_hexpand(True)
        for renderer in self.history.get_cells():
            renderer.set_property('ellipsize', Pango.EllipsizeMode.END)
            renderer.set_property('max-width-chars', 45)
            renderer.set_property('width-chars', 20)
        self.history.set_tooltip_text('Last 10 results from this app session, including host and exit status')
        self._history_guard = False
        self.history.connect('changed', self._history_selected)
        output_box.pack_start(self.history, False, False, 0)
        self._reload_history()
        self.output = Gtk.TextView(editable=False, cursor_visible=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.output.get_style_context().add_class('detail-text')
        self.output.set_bottom_margin(16)
        self.output_scroll = Gtk.ScrolledWindow()
        self.output_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.output_scroll.add(self.output)
        output_box.pack_start(self.output_scroll, True, True, 0)
        self.split.pack2(output_box, resize=True, shrink=True)
        self.split.set_position(330)
        self.pack_start(self.split, True, True, 0)
        self.connect('destroy', self._destroy)
        selectable_readouts(self)
        # Start keyboard focus on a control, not the selectable introductory text.
        self.set_focus_chain([self.refresh_button, self.split])
        self._refresh_clicked()

    @staticmethod
    def _label(text):
        label = Gtk.Label(label=text, xalign=0)
        label.set_line_wrap(True)
        label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_max_width_chars(1)
        label.set_hexpand(True)
        label.set_selectable(True)
        return label

    def _group(self, parent, title):
        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        label = self._label(title)
        label.get_style_context().add_class('section-title')
        group.pack_start(label, False, False, 0)
        parent.pack_start(group, False, False, 0)
        return group

    def _add_action(self, parent, action, callback=None):
        row = Gtk.Box(spacing=8)
        button = Gtk.Button(label=action.title)
        button.get_style_context().add_class('maintenance-change' if action.privileged else 'maintenance-read')
        button.connect('clicked', callback or (lambda *_: self._run_action(action)))
        row.pack_start(button, False, False, 0)
        target = self._label('→ ' + self.target)
        row.pack_start(target, True, True, 0)
        parent.pack_start(row, False, False, 0)
        text = action.description
        if action == ACTIONS[4]:
            text = ('SSH DISCONNECT RISK: restarting NetworkManager may drop this session. If disconnected, check the remote host before retrying. ' if self.host else 'DISRUPTIVE: network connections may be interrupted. ') + text
        label = self._label(text)
        label.get_style_context().add_class('muted')
        parent.pack_start(label, False, False, 0)
        self._buttons.append((button, action))
        self._availability_labels[button] = (label, text)

    def _vacuum_mode_changed(self, *_):
        self.vacuum_value.set_value(7 if self.vacuum_mode.get_active_id() == 'age' else 512)
        self._vacuum_changed()

    def _vacuum_changed(self, *_):
        action = vacuum_action(self.vacuum_mode.get_active_id(), self.vacuum_value.get_value_as_int())
        for button, original in self._buttons:
            if original == ACTIONS[1]:
                label, _ = self._availability_labels[button]
                self._availability_labels[button] = (label, action.description)
        if hasattr(self, 'status'):
            self._refresh_clicked()

    def _review_vacuum(self, *_):
        if self._busy:
            return
        action = vacuum_action(self.vacuum_mode.get_active_id(), self.vacuum_value.get_value_as_int())
        def review(code, output):
            usage = output.strip()[:2000] if code == 0 else 'Could not check current usage: ' + output.strip()[:1000]
            reviewed = Action(action.title, 'Current journal usage: ' + usage + '\n\n' + action.description,
                              action.command, action.privileged)
            self._run_action(reviewed)
        self._run_action(ACTIONS[0], after=review)

    def _rotation_editor(self, content):
        expander = Gtk.Expander(label='Text log rotation configuration')
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(6)
        hint = Gtk.Label(label='Manage one custom profile: /etc/logrotate.d/syslogapp. Existing rules are checked for conflicts. Saving does not rotate logs.', xalign=0)
        hint.set_line_wrap(True)
        hint.set_max_width_chars(1)
        box.pack_start(hint, False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        self.rotation_path = Gtk.Entry()
        self.rotation_path.set_placeholder_text('/var/log/myapp.log')
        self.rotation_path.set_hexpand(True)
        path_box = Gtk.Box(spacing=6)
        path_box.pack_start(self.rotation_path, True, True, 0)
        browse = Gtk.Button(label='Browse')
        self.rotation_browse = browse
        browse.connect('clicked', self._browse_log)
        path_box.pack_start(browse, False, False, 0)
        self.rotation_frequency = Gtk.ComboBoxText()
        for item in ('daily', 'weekly', 'monthly'):
            self.rotation_frequency.append_text(item)
        self.rotation_frequency.set_active(1)
        self.rotation_keep = Gtk.SpinButton.new_with_range(1, 52, 1)
        self.rotation_keep.set_value(4)
        self.rotation_size = Gtk.SpinButton.new_with_range(0, 102400, 1)
        self.rotation_size.set_tooltip_text('0 disables the size threshold; evaluated when the system scheduler runs logrotate')
        self.rotation_mode = Gtk.ComboBoxText()
        self.rotation_mode.append('rename', 'Rename · writer must reopen')
        self.rotation_mode.append('copytruncate', 'Copy/truncate · possible data loss')
        self.rotation_mode.set_active_id('rename')
        self.rotation_compress = Gtk.CheckButton(label='Compress · delay newest archive')
        self.rotation_compress.set_active(True)
        for index, (name, widget) in enumerate((('Log file', path_box), ('Schedule', self.rotation_frequency),
                    ('Archives to keep', self.rotation_keep), ('Max size (MiB)', self.rotation_size),
                    ('Method', self.rotation_mode), ('Compression', self.rotation_compress))):
            grid.attach(Gtk.Label(label=name, xalign=0), 0, index, 1, 1)
            grid.attach(widget, 1, index, 1, 1)
        box.pack_start(grid, False, False, 0)
        note = Gtk.Label(label='Rename requires the writer to reopen its log; no reopen script is added. Copy/truncate needs no reopen signal but may lose entries written during copying. Schedule and max size are evaluated by the system logrotate timer/cron job.', xalign=0)
        note.set_line_wrap(True)
        note.set_max_width_chars(1)
        note.get_style_context().add_class('muted')
        box.pack_start(note, False, False, 0)
        self.rotation_save = Gtk.Button(label='Review and save rotation settings…')
        self.rotation_save.get_style_context().add_class('maintenance-change')
        self.rotation_save.connect('clicked', self._save_rotation)
        box.pack_start(self.rotation_save, False, False, 0)
        expander.add(box)
        content.pack_start(expander, False, False, 0)
        self.rotation_expander = expander
        # Read only our small generated profile; preserve saved editor values.
        try:
            if self.host:
                text = self.host.rotation_text
            else:
                with open('/etc/logrotate.d/syslogapp') as stream:
                    text = stream.read(8192)
            import re
            path = re.search(r'^(/var/log/[^\s{}]+) \{', text, re.M)
            schedule = re.search(r'^    (daily|weekly|monthly)$', text, re.M)
            keep = re.search(r'^    rotate (\d+)$', text, re.M)
            size = re.search(r'^    maxsize (\d+)M$', text, re.M)
            if path and schedule and keep:
                self.rotation_path.set_text(path[1])
                self.rotation_frequency.set_active(('daily','weekly','monthly').index(schedule[1]))
                self.rotation_keep.set_value(int(keep[1]))
                self.rotation_size.set_value(int(size[1]) if size else 0)
                self.rotation_compress.set_active('    compress\n' in text)
                self.rotation_mode.set_active_id('copytruncate' if '    copytruncate\n' in text else 'rename')
        except OSError:
            pass
        self.rotation_summary = self._label('')
        box.pack_start(self.rotation_summary, False, False, 0)
        self.rotation_preview = Gtk.TextView(editable=False, cursor_visible=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        preview_scroll = Gtk.ScrolledWindow()
        preview_scroll.set_min_content_height(130)
        preview_scroll.add(self.rotation_preview)
        box.pack_start(preview_scroll, False, False, 0)
        self.rotation_validate = Gtk.Button(label='Validate only · no changes')
        self.rotation_validate.get_style_context().add_class('maintenance-read')
        self.rotation_validate.connect('clicked', lambda *_: self._save_rotation(validate=True))
        box.pack_start(self.rotation_validate, False, False, 0)
        self.rotation_availability = self._label('')
        box.pack_start(self.rotation_availability, False, False, 0)
        box.reorder_child(self.rotation_save, -1)
        for widget, signal in ((self.rotation_path, 'changed'), (self.rotation_frequency, 'changed'),
                               (self.rotation_keep, 'value-changed'), (self.rotation_size, 'value-changed'),
                               (self.rotation_mode, 'changed'), (self.rotation_compress, 'toggled')):
            widget.connect(signal, self._rotation_changed)
        self._rotation_changed()

    def _rotation_changed(self, *_):
        try:
            preview = render(self.rotation_path.get_text().strip(), self.rotation_frequency.get_active_text(),
                             self.rotation_keep.get_value_as_int(), self.rotation_compress.get_active(),
                             self.rotation_mode.get_active_id(), self.rotation_size.get_value_as_int())
            self.rotation_summary.set_text(f'{self.rotation_path.get_text().strip()}: {self.rotation_frequency.get_active_text()}, '
                f'keep {self.rotation_keep.get_value_as_int()} archives, '
                + ('compress older archives' if self.rotation_compress.get_active() else 'no compression')
                + f', {self.rotation_mode.get_active_id()}, size threshold {self.rotation_size.get_value_as_int()} MiB (0 = disabled). '
                'The system scheduler controls rotation; saving does not rotate files.')
            self.rotation_preview.get_buffer().set_text(preview)
            self._rotation_valid = True
        except ValueError as error:
            self._rotation_valid = False
            self.rotation_summary.set_text(str(error))
            self.rotation_preview.get_buffer().set_text('')
        if hasattr(self, 'status'):
            self._refresh_clicked()

    def _browse_log(self, *_):
        if self.host:
            self._browse_remote_log()
            return
        dialog = Gtk.FileChooserDialog(title='Select a text log under /var/log',
                    transient_for=self.get_toplevel(), action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Select', Gtk.ResponseType.OK)
        dialog.set_current_folder('/var/log')
        if dialog.run() == Gtk.ResponseType.OK:
            self.rotation_path.set_text(dialog.get_filename())
        dialog.destroy()

    def _browse_remote_log(self):
        # Remote filesystem browsing uses the remote host, never the local chooser.
        dialog = Gtk.Dialog(title='Remote text log — ' + self.host.target,
                            transient_for=self.get_toplevel(), modal=True)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Select', Gtk.ResponseType.OK)
        dialog.set_default_size(600, 380)
        store = Gtk.ListStore(str)
        tree = Gtk.TreeView(model=store)
        tree.append_column(Gtk.TreeViewColumn('/var/log files (up to 500)', Gtk.CellRendererText(), text=0))
        TableTextAccess(tree, {tree.get_column(0): 0})
        scroll = Gtk.ScrolledWindow()
        scroll.set_margin_bottom(12)
        scroll.add(tree)
        dialog.get_content_area().pack_start(scroll, True, True, 0)
        status = Gtk.Label(label='Reading remote log files…', xalign=0)
        dialog.get_content_area().pack_start(status, False, False, 4)
        active = [True]
        def loaded(result, error):
            if not active[0]:
                return False
            if error:
                status.set_text(str(error))
            else:
                for path in result[0].splitlines()[:500]:
                    store.append([path])
                status.set_text('Select a remote file or type its path in the editor.')
            return False
        self.app.run_async(lambda: self.host.capture(['find', '/var/log', '-maxdepth', '3', '-type', 'f', '-name', '*.log'],
                                                     timeout=5, max_bytes=64000), loaded)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            model, itr = tree.get_selection().get_selected()
            if itr is not None:
                self.rotation_path.set_text(model.get_value(itr,0))
        active[0] = False
        dialog.destroy()

    def _save_rotation(self, *_, validate=False):
        if self._busy:
            return
        path = self.rotation_path.get_text().strip()
        frequency = self.rotation_frequency.get_active_text()
        keep = self.rotation_keep.get_value_as_int()
        size = self.rotation_size.get_value_as_int()
        mode = self.rotation_mode.get_active_id()
        compress = self.rotation_compress.get_active()
        try:
            preview = render(path, frequency, keep, compress, mode, size)
        except ValueError as exc:
            self.status.set_text(str(exc))
            return
        helper = str(Path(__file__).resolve().parents[1] / 'logrotate_config.py')
        description = ('Validate the staged configuration against all existing rules. No configuration, state, backups or logs will change.' if validate else
                       'Validate and save /etc/logrotate.d/syslogapp. Only the app-managed profile is replaced; its previous contents are backed up. No logs are rotated now.')
        action = Action('Validate text log rotation' if validate else 'Save text log rotation',
                        description + '\n\n' + preview,
                        (sys.executable, helper, '--path', path, '--frequency', frequency,
                         '--keep', str(keep), '--compress', 'yes' if compress else 'no',
                         '--mode', mode, '--size-mib', str(size), *(['--validate-only'] if validate else [])))
        self._run_action(action)

    def _refresh_clicked(self, *_):
        # Only executable availability; never runs a command.
        for button, action in self._buttons:
            args, reason = self._resolve(action)
            button.set_sensitive(bool(args) and not self._busy and not self._probing)
            button.set_tooltip_text(reason or action.description)
            label, text = self._availability_labels[button]
            label.set_text(text + ('\nUnavailable: ' + reason if reason else ''))

        for widget in (self.refresh_button, self.vacuum_mode, self.vacuum_value, self.rotation_path,
                       self.rotation_frequency, self.rotation_keep, self.rotation_size, self.rotation_mode,
                       self.rotation_compress, self.rotation_browse):
            widget.set_sensitive(not self._busy and not self._probing)

        available = (bool(self.host.which('logrotate') and self.host.which('python3') and
                          getattr(self.host, 'python_ready', True) and
                          (self.host.uid == 0 or self.host.which('sudo'))) if self.host else
                     bool(shutil.which('logrotate') and shutil.which('pkexec')))
        self.rotation_save.set_sensitive(available and self._rotation_valid and not self._busy and not self._probing)
        self.rotation_validate.set_sensitive(available and self._rotation_valid and not self._busy and not self._probing)
        self.history.set_sensitive(not self._busy)
        self.output_menu.get_popup().get_children()[2].set_sensitive(not self._busy)
        self.rotation_availability.set_text(('Unavailable: remote logrotate, Python 3.8+ and sudo/root required' if self.host else 'Unavailable: logrotate and pkexec required') if not available else 'Validate and Save require administrator authentication; validation changes no files.')
        self.rotation_save.set_tooltip_text(('Remote logrotate, Python 3.8+ and sudo/root required' if self.host else
                                           'Requires logrotate and pkexec') if not available else 'Review the configuration before authentication')

    def refresh_available(self, *_):
        if self._busy or self._probing:
            return
        if not self.host:
            self._refresh_clicked()
            return
        self._probing = True
        self._refresh_clicked()
        self.status.set_text('Checking command availability on ' + self.host.target + '…')
        def done(_result, error):
            if self._destroyed:
                return False
            self._probing = False
            self._refresh_clicked()
            self.status.set_text(str(error) if error else 'Remote command availability refreshed')
            return False
        self.app.run_async(self.host._probe, done)

    def _resolve(self, action):
        host = getattr(self, 'host', None)
        return host.resolve_action(action) if host else resolve(action)

    def _confirm(self, action, args):
        dialog = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                   message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.CANCEL, text=action.title + '?')
        target = self.host.target if self.host else 'Local host'
        rotation = len(action.command) > 1 and str(action.command[1]).endswith('/logrotate_config.py')
        command = ('Remote Python helper (configuration shown above)' if self.host and rotation
                   else ' '.join(action.command))
        disconnect = '\n\nSSH DISCONNECT RISK: this session may be interrupted. If disconnected, check the host before retrying.' if self.host and 'NetworkManager.service' in action.command else ''
        dialog.format_secondary_text('TARGET: ' + target + '\n\n' + action.description + '\n\n' + command +
                                     disconnect + '\n\nKeep the app open until the action finishes.')
        dialog.set_resizable(True)
        dialog.set_default_size(600, -1)
        dialog.add_button('Validate only' if '--validate-only' in action.command else 'Run action', Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def _run_action(self, action, after=None):
        if self._busy or self._destroyed:
            return
        args, reason = MaintenancePage._resolve(self, action)
        if not args:
            self.status.set_text(reason)
            self._refresh_clicked()
            return
        if action.privileged and not self._confirm(action, args):
            return
        host = getattr(self, 'host', None)
        if host and action.privileged and host.uid != 0:
            from ..host_ui import sudo_password
            self._sudo_password = sudo_password(self.get_toplevel(), host.target)
            if self._sudo_password is None:
                return
        self._busy = True
        self._after_action = after
        self._running_action = action
        self._started = datetime.now().isoformat(timespec='seconds')
        self._running_since = time.monotonic()
        self._history_guard = True
        self.history.set_active_id('current')
        self._history_guard = False
        self._refresh_clicked()
        self.output.get_buffer().set_text('')
        context = self.status.get_style_context()
        context.remove_class('active-live')
        context.remove_class('maintenance-error')
        context.add_class('paused-live')
        self._progress_tick()
        self._progress_source = GLib.timeout_add_seconds(1, self._progress_tick)
        # Created only for an explicit action; cannot occupy the snapshot worker.
        threading.Thread(target=self._worker, args=(action, args),
                         name='syslogapp-maintenance', daemon=False).start()

    def _worker(self, action, args):
        try:
            host = getattr(self, 'host', None)
            if host:
                password = self._sudo_password
                self._sudo_password = None
                if action.privileged:
                    callback = getattr(self, '_queue_output', None)
                    result = host.maintenance(args, password, on_output=callback) if callback else host.maintenance(args, password)
                    password = None
                else:
                    callback = getattr(self, '_queue_output', None)
                    if callback:
                        result = host.maintenance(args, on_output=callback, timeout=5)
                    else:
                        text, limited = host.capture(args, timeout=5, max_bytes=64 * 1024)
                        result = (0, text + ('\n[Output limited]' if limited else ''))
            else:
                callback = getattr(self, '_queue_output', None)
                result = run_action(args, action.privileged, on_output=callback) if callback else run_action(args, action.privileged)
            error = None
        except Exception as exc:
            tail = getattr(exc, 'output', '')
            result, error = (1, str(exc) + ('\n' + tail if tail else '')), exc
        if not self._destroyed and not self.app._closing:
            GLib.idle_add(self._done, action, result, error)

    def _done(self, action, result, error):
        if self._destroyed:
            return False
        self._busy = False
        if hasattr(self, '_stop_progress'):
            self._stop_progress()
        self._refresh_clicked()
        code, output = result if result is not None else (1, str(error))
        state = 'finished' if code == 0 else ('authentication cancelled' if code == 126 else f'failed (exit {code})')
        if code == 255 and getattr(self, 'host', None):
            state = 'SSH disconnected · remote outcome unknown'
        elapsed = time.monotonic() - getattr(self, '_running_since', time.monotonic())
        target = getattr(self, 'target', 'Local host')
        self.status.set_text(f'{action.title} · {target}: {state} · {elapsed:.1f}s · exit {code}')
        context = self.status.get_style_context()
        context.remove_class('active-live')
        context.remove_class('paused-live')
        context.remove_class('maintenance-error')
        context.add_class('active-live' if code == 0 else 'maintenance-error')
        self.output.get_buffer().set_text(output or '(No output)')
        self._latest_result = (self.status.get_text(), output or '(No output)', code)
        if hasattr(self, '_record_result'):
            self._record_result(action, code, output, elapsed)
        if hasattr(self, 'usage') and action.command[:2] == ('journalctl', '--disk-usage'):
            self.usage.set_text('Journal usage: ' + (output.strip() if code == 0 else 'Could not check'))
        after = getattr(self, '_after_action', None)
        self._after_action = None
        if after:
            after(code, output)
        return False

    def _queue_output(self, text):
        if self._destroyed or self.app._closing:
            return
        with self._output_lock:
            self._pending_output = (self._pending_output + text)[-65536:]
            if not self._flush_source:
                self._flush_source = GLib.timeout_add(100, self._flush_output)

    def _flush_output(self):
        with self._output_lock:
            text = self._pending_output
            self._pending_output = ''
            self._flush_source = 0
        if self._destroyed or not text:
            return False
        buffer = self.output.get_buffer()
        held = buffer.get_has_selection()
        adjustment = self.output_scroll.get_vadjustment()
        at_end = adjustment.get_value() + adjustment.get_page_size() >= adjustment.get_upper() - 24
        buffer.insert(buffer.get_end_iter(), text)
        excess = buffer.get_char_count() - 128 * 1024
        if excess > 0:
            buffer.delete(buffer.get_start_iter(), buffer.get_iter_at_offset(excess))
        if at_end and not held and self.output.get_mapped():
            self.output.scroll_to_iter(buffer.get_end_iter(), 0, False, 0, 0)
        return False

    def _progress_tick(self):
        if self._destroyed or not self._busy:
            self._progress_source = 0
            return False
        self.status.set_text(f'{self._running_action.title} · {self.target} · running · '
                             f'{time.monotonic() - self._running_since:.0f}s')
        return True

    def _stop_progress(self):
        for name in ('_progress_source', '_flush_source'):
            source = getattr(self, name, 0)
            if source:
                GLib.source_remove(source)
                setattr(self, name, 0)
        with self._output_lock:
            self._pending_output = ''

    def _destroy(self, *_):
        self._destroyed = True
        self._stop_progress()

    def _record_result(self, action, code, output, elapsed):
        self._history.append(dict(action=action.title, target=self.target, started=self._started,
                                  elapsed=elapsed, code=code, output=output[-32768:]))
        del self._history[:-10]
        self._reload_history()

    def _reload_history(self):
        self._history_guard = True
        self.history.remove_all()
        self.history.append('current', 'Current output · session history (last 10 results)')
        for index in range(len(self._history) - 1, -1, -1):
            record = self._history[index]
            self.history.append(str(index), f"{record['started']} · {record['action']} · {record['target']} · exit {record['code']}")
        self.history.set_active_id('current')
        self._history_guard = False

    def _history_selected(self, *_):
        if self._history_guard or self._busy:
            return
        key = self.history.get_active_id()
        if key and key != 'current':
            record = self._history[int(key)]
            self.status.set_text(f"History · {record['action']} · {record['target']} · exit {record['code']} · {record['elapsed']:.1f}s")
            self.output.get_buffer().set_text('[Session history tail]\n' + record['output'])
            self._color_status(record['code'])
        elif key == 'current' and hasattr(self, '_latest_result'):
            self.status.set_text(self._latest_result[0])
            self.output.get_buffer().set_text(self._latest_result[1])
            self._color_status(self._latest_result[2])
        elif key == 'current':
            self.status.set_text('Idle · ' + self.target)
            self.output.get_buffer().set_text('')
            self._color_status(None)

    def _color_status(self, code):
        context = self.status.get_style_context()
        for name in ('active-live', 'paused-live', 'maintenance-error', 'muted'):
            context.remove_class(name)
        context.add_class('active-live' if code == 0 else ('maintenance-error' if code is not None else 'muted'))

    def _output_text(self):
        buffer = self.output.get_buffer()
        return buffer.get_text(*buffer.get_bounds(), False)

    def _copy_output(self, *_):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self._output_text(), -1)

    def _clear_output(self, *_):
        if not self._busy:
            self._history_guard = True
            self.history.set_active_id('current')
            self._history_guard = False
            self.output.get_buffer().set_text('')
            self._latest_result = ('Output cleared · session history retained', '', None)
            self.status.set_text(self._latest_result[0])

    def _save_output(self, *_):
        dialog = Gtk.FileChooserDialog(title='Save output on this computer', transient_for=self.get_toplevel(),
                                       action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Save', Gtk.ResponseType.OK)
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name('syslogapp-maintenance-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.txt')
        if dialog.run() == Gtk.ResponseType.OK:
            try:
                Path(dialog.get_filename()).write_text(self.status.get_text() + '\n\n' + self._output_text())
            except OSError as error:
                self.app.window.toast('Could not save output: ' + str(error))
        dialog.destroy()
