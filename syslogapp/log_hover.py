# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Log-only hover preview: two seconds stationary, dismiss on movement."""
from gi.repository import Gtk, Gdk, GLib, Pango


class LogHover:
    DELAY_MS = 2000

    def __init__(self, tree, text_for_row):
        self.tree, self.text_for_row = tree, text_for_row
        self.source = 0
        self.point = None
        self.window = None
        self.destroyed = False
        tree.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        tree.connect('motion-notify-event', self._motion)
        tree.connect('enter-notify-event', self._motion)
        for signal in ('leave-notify-event', 'button-press-event', 'scroll-event', 'key-press-event', 'focus-out-event', 'unmap'):
            tree.connect(signal, self.dismiss)
        tree.connect('destroy', self._destroy)
        self._subscriptions = []
        for signal in ('row-changed', 'row-inserted', 'row-deleted', 'rows-reordered'):
            model = tree.get_model()
            self._subscriptions.append((model, model.connect(signal, self._model_changed)))
        for adjustment in (Gtk.Scrollable.get_hadjustment(tree), Gtk.Scrollable.get_vadjustment(tree)):
            self._subscriptions.append((adjustment, adjustment.connect('value-changed', self.dismiss)))

    def _hit(self):
        window = self.tree.get_bin_window()
        if window is None or self.point is None:
            return None
        _ok, ox, oy = window.get_origin()
        x, y = self.point[0] - ox, self.point[1] - oy
        if not 0 <= x < window.get_width() or not 0 <= y < window.get_height():
            return None
        return self.tree.get_path_at_pos(int(x), int(y))

    def _motion(self, _widget, event):
        point = (event.x_root, event.y_root)
        if point == self.point:
            return False
        self.dismiss()
        self.point = point
        buttons = Gdk.ModifierType.BUTTON1_MASK | Gdk.ModifierType.BUTTON2_MASK | Gdk.ModifierType.BUTTON3_MASK
        if not event.state & buttons and self._hit():
            self.source = GLib.timeout_add(self.DELAY_MS, self._show)
        return False

    def dismiss(self, *_):
        if self.source:
            GLib.source_remove(self.source)
            self.source = 0
        if self.window:
            self.window.hide()
        self.point = None
        return False

    def _model_changed(self, *_):
        if self.window and self.window.get_visible():
            self.dismiss()

    def _show(self):
        self.source = 0
        if self.destroyed or not self.tree.get_mapped():
            return False
        hit = self._hit()
        if not hit:
            return False
        model = self.tree.get_model()
        text = self.text_for_row(model, model.get_iter(hit[0]))
        if not text:
            return False
        display = self.tree.get_display()
        x, y = map(int, self.point)
        monitor = display.get_monitor_at_point(x, y)
        if monitor is None:
            return False
        area = monitor.get_workarea()
        if self.window is None:
            self.window = Gtk.Window(type=Gtk.WindowType.POPUP)
            self.window.set_type_hint(Gdk.WindowTypeHint.TOOLTIP)
            self.window.set_accept_focus(False)
            self.window.set_focus_on_map(False)
            self.window.set_resizable(False)
            self.window.set_border_width(10)
            self.window.get_style_context().add_class('log-hover')
            self.label = Gtk.Label(xalign=0)
            self.label.set_line_wrap(True)
            self.label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            self.label.set_lines(12)
            self.label.set_ellipsize(Pango.EllipsizeMode.END)
            self.window.add(self.label)
        text = str(text)
        self.label.set_text(text if len(text) <= 4096 else text[:4095] + '…')
        self.label.set_max_width_chars(max(16, min(72, (area.width - 48) // 9)))
        self.window.set_transient_for(self.tree.get_toplevel())
        self.label.show()
        _minimum, natural = self.window.get_preferred_size()
        px, py = x + 16, y + 24
        if py + natural.height > area.y + area.height:
            py = y - natural.height - 12
        px = max(area.x, min(px, area.x + area.width - natural.width))
        py = max(area.y, min(py, area.y + area.height - natural.height))
        self.window.move(px, py)
        self.window.show()
        return False

    def _destroy(self, *_):
        if self.destroyed:
            return
        self.destroyed = True
        self.dismiss()
        for owner, handler in self._subscriptions:
            owner.disconnect(handler)
        self._subscriptions.clear()
        if self.window:
            self.window.destroy()
