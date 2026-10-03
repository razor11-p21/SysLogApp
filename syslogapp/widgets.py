# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import math
from collections import deque

from gi.repository import Gtk, Gdk, GLib, Pango


STATUS_ICONS = {
    "ok": "emblem-ok-symbolic",
    "warning": "dialog-warning-symbolic",
    "error": "dialog-error-symbolic",
    "info": "dialog-information-symbolic",
}


class ResponsiveColumns(Gtk.Box):
    """Stack dashboard sections when two readable columns no longer fit."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.connect("size-allocate", self._resize)

    def add_card(self, card):
        self.pack_start(card, True, True, 0)

    def _resize(self, _widget, allocation):
        orientation = Gtk.Orientation.HORIZONTAL if allocation.width >= 1080 else Gtk.Orientation.VERTICAL
        if self.get_orientation() != orientation:
            self.set_orientation(orientation)


class WrappingToolbar(Gtk.FlowBox):
    def __init__(self):
        super().__init__()
        self.set_selection_mode(Gtk.SelectionMode.NONE)
        self.set_min_children_per_line(1)
        self.set_max_children_per_line(10)
        self.set_column_spacing(8)
        self.set_row_spacing(8)


class StatusPill(Gtk.Box):
    def __init__(self, text="", state="info"):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.get_style_context().add_class("status-pill")
        self.icon = Gtk.Image.new_from_icon_name(STATUS_ICONS.get(state, STATUS_ICONS["info"]), Gtk.IconSize.MENU)
        self.label = Gtk.Label(label=text)
        self.pack_start(self.icon, False, False, 0)
        self.pack_start(self.label, False, False, 0)
        self.set_state(text, state)

    def set_state(self, text, state):
        self.label.set_text(text)
        self.icon.set_from_icon_name(STATUS_ICONS.get(state, STATUS_ICONS["info"]), Gtk.IconSize.MENU)
        ctx = self.get_style_context()
        for cls in ("ok", "warning", "error", "info"):
            ctx.remove_class(cls)
        ctx.add_class(state)


class MetricCard(Gtk.EventBox):
    def __init__(self, title, icon_name, accent="blue"):
        super().__init__()
        self.get_style_context().add_class("metric-card")
        self.set_visible_window(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(16)
        self.add(box)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon_wrap = Gtk.EventBox()
        icon_wrap.set_visible_window(True)
        icon_wrap.get_style_context().add_class("metric-icon")
        icon_wrap.get_style_context().add_class(accent)
        icon_wrap.set_size_request(42, 42)
        icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.LARGE_TOOLBAR)
        icon_wrap.add(icon)
        top.pack_start(icon_wrap, False, False, 0)
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.get_style_context().add_class("metric-title")
        top.pack_start(title_label, True, True, 0)
        box.pack_start(top, False, False, 0)

        self.value = Gtk.Label(label="—", xalign=0)
        self.value.set_ellipsize(Pango.EllipsizeMode.END)
        self.value.set_max_width_chars(16)
        self.value.get_style_context().add_class("metric-value")
        box.pack_start(self.value, False, False, 0)

        self.status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        self.dot = Gtk.Label(label="●")
        self.dot.get_style_context().add_class("status-dot")
        self.status = Gtk.Label(label="Loading…", xalign=0)
        self.status.set_line_wrap(True)
        self.status.set_max_width_chars(20)
        self.status.get_style_context().add_class("metric-status")
        self.status_row.pack_start(self.dot, False, False, 0)
        self.status_row.pack_start(self.status, True, True, 0)
        box.pack_start(self.status_row, False, False, 0)

        self.detail = Gtk.Label(label="", xalign=0)
        self.detail.get_style_context().add_class("muted")
        self.detail.set_ellipsize(Pango.EllipsizeMode.END)
        box.pack_end(self.detail, False, False, 0)

        self._set_state_class("info")

    def _set_state_class(self, state):
        for w in (self.dot, self.status):
            ctx = w.get_style_context()
            for cls in ("ok", "warning", "error", "info"):
                ctx.remove_class(cls)
            ctx.add_class(state)

    def update(self, value, status, detail="", state="ok"):
        self.value.set_text(str(value))
        self.status.set_text(str(status))
        self.detail.set_text(str(detail))
        self._set_state_class(state)


class SectionCard(Gtk.Box):
    def __init__(self, title, subtitle=None, icon_name=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.get_style_context().add_class("section-card")
        self.set_border_width(18)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        if icon_name:
            icon_wrap = Gtk.EventBox()
            icon_wrap.set_visible_window(True)
            icon_wrap.get_style_context().add_class("section-icon")
            icon_wrap.set_size_request(42, 42)
            icon_wrap.add(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.LARGE_TOOLBAR))
            header.pack_start(icon_wrap, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.get_style_context().add_class("section-title")
        title_label.set_line_wrap(True)
        text.pack_start(title_label, False, False, 0)
        if subtitle:
            sub = Gtk.Label(label=subtitle, xalign=0)
            sub.set_line_wrap(True)
            sub.set_max_width_chars(45)
            sub.get_style_context().add_class("muted")
            text.pack_start(sub, False, False, 0)
        header.pack_start(text, True, True, 0)
        self.header_extra = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.pack_end(self.header_extra, False, False, 0)
        self.pack_start(header, False, False, 0)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.pack_start(self.content, True, True, 0)


class ActivityGraph(Gtk.DrawingArea):
    def __init__(self, max_points=60):
        super().__init__()
        self.values = deque([0.0] * max_points, maxlen=max_points)
        self.set_size_request(-1, 170)
        self.connect("draw", self._draw)

    def add_value(self, value):
        try:
            value = max(0.0, min(100.0, float(value)))
        except Exception:
            value = 0.0
        self.values.append(value)
        self.queue_draw()

    def _rgba(self, name, fallback):
        ctx = self.get_style_context()
        color = ctx.lookup_color(name)
        if color and color[0]:
            return color[1]
        return fallback

    def _draw(self, widget, cr):
        alloc = self.get_allocation()
        w, h = max(1, alloc.width), max(1, alloc.height)
        pad_l, pad_r, pad_t, pad_b = 38, 12, 10, 24
        gw, gh = max(1, w - pad_l - pad_r), max(1, h - pad_t - pad_b)

        grid = self._rgba("graph_grid", Gdk.RGBA(0.75, 0.78, 0.82, 0.35))
        line = self._rgba("graph_line", Gdk.RGBA(0.12, 0.47, 0.95, 1.0))
        fill = self._rgba("graph_fill", Gdk.RGBA(0.12, 0.47, 0.95, 0.14))
        text = self._rgba("graph_text", Gdk.RGBA(0.42, 0.46, 0.52, 1.0))

        cr.set_line_width(1)
        cr.set_source_rgba(grid.red, grid.green, grid.blue, grid.alpha)
        for pct in (0, 25, 50, 75, 100):
            y = pad_t + gh - (pct / 100.0) * gh
            cr.move_to(pad_l, y)
            cr.line_to(pad_l + gw, y)
            cr.stroke()

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        cr.set_source_rgba(text.red, text.green, text.blue, text.alpha)
        for pct in (0, 25, 50, 75, 100):
            y = pad_t + gh - (pct / 100.0) * gh
            cr.move_to(2, y + 4)
            cr.show_text(f"{pct}%")

        vals = list(self.values)
        if len(vals) < 2:
            return False
        step = gw / max(1, len(vals) - 1)
        pts = []
        for i, v in enumerate(vals):
            x = pad_l + i * step
            y = pad_t + gh - (v / 100.0) * gh
            pts.append((x, y))

        cr.move_to(pts[0][0], pad_t + gh)
        for x, y in pts:
            cr.line_to(x, y)
        cr.line_to(pts[-1][0], pad_t + gh)
        cr.close_path()
        cr.set_source_rgba(fill.red, fill.green, fill.blue, fill.alpha)
        cr.fill()

        cr.set_source_rgba(line.red, line.green, line.blue, line.alpha)
        cr.set_line_width(2)
        cr.move_to(*pts[0])
        for p in pts[1:]:
            cr.line_to(*p)
        cr.stroke()
        return False


class DiagnosticRow(Gtk.Box):
    def __init__(self, state, title, detail):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.get_style_context().add_class("diagnostic-row")
        self.set_border_width(4)
        icon = Gtk.Image.new_from_icon_name(STATUS_ICONS.get(state, STATUS_ICONS["info"]), Gtk.IconSize.MENU)
        icon.get_style_context().add_class(state)
        self.pack_start(icon, False, False, 4)
        title_lbl = Gtk.Label(label=title, xalign=0)
        title_lbl.set_hexpand(True)
        self.pack_start(title_lbl, True, True, 0)
        detail_lbl = Gtk.Label(label=detail, xalign=1)
        detail_lbl.get_style_context().add_class("muted")
        detail_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        detail_lbl.set_max_width_chars(50)
        self.pack_end(detail_lbl, False, False, 4)


def message_dialog(parent, title, text, secondary=None, message_type=Gtk.MessageType.INFO):
    dlg = Gtk.MessageDialog(parent=parent, flags=Gtk.DialogFlags.MODAL,
                            message_type=message_type, buttons=Gtk.ButtonsType.OK,
                            text=title)
    if secondary:
        dlg.format_secondary_text(secondary)
    elif text:
        dlg.format_secondary_text(text)
    dlg.run()
    dlg.destroy()


def confirm_dialog(parent, title, text):
    dlg = Gtk.MessageDialog(parent=parent, flags=Gtk.DialogFlags.MODAL,
                            message_type=Gtk.MessageType.WARNING,
                            buttons=Gtk.ButtonsType.CANCEL,
                            text=title)
    dlg.format_secondary_text(text)
    dlg.add_button("Run", Gtk.ResponseType.OK)
    resp = dlg.run()
    dlg.destroy()
    return resp == Gtk.ResponseType.OK
