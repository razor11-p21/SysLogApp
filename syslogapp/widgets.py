# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
from gi.repository import Gtk, Gdk, GLib, Pango


def set_cell_style(cell, foreground, weight):
    """Avoid invalidating Pango layouts when a reused cell's style is unchanged."""
    style = (foreground, int(weight))
    if getattr(cell, '_terminal_style', None) != style:
        cell.set_property('foreground', foreground)
        cell.set_property('weight', weight)
        cell._terminal_style = style


def _empty_compare(*_args):
    return 0


class TableTextAccess:
    """Character selection across native table cells; never replaces readouts."""
    def __init__(self, tree, columns, extra_actions=(), connect=True, on_select=None,
                 cell_data=None, format_value=None):
        self.tree, self.columns = tree, columns
        self.extra_actions, self.on_select = extra_actions, on_select
        self.cell_data, self.format_value = cell_data, format_value
        self._anchor = self._end = None
        self._pressed = self._dragging = False
        self._pointer = None
        self._scroll_source = 0
        self._full_attrs = self._attributes(0, 0xffffffff)
        self._subscriptions = []
        self._disposed = False
        for column, index in columns.items():
            for renderer in column.get_cells():
                if isinstance(renderer, Gtk.CellRendererText):
                    renderer.set_property('editable', False)
                    column.set_cell_data_func(renderer, self._paint_cell, index)
            self._subscriptions.append((column, column.connect('notify::visible', lambda *_: self.clear_selection())))
        model = tree.get_model()
        self._subscriptions.append((model, model.connect('sort-column-changed', lambda *_: self.clear_selection())))
        if connect:
            tree.connect('button-press-event', self.button_press)
        tree.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)
        tree.connect('motion-notify-event', self._drag)
        tree.connect('button-release-event', self._release)
        tree.connect('key-press-event', self._key)
        tree.connect('destroy', self._destroy)

    @staticmethod
    def _attributes(start, end):
        attrs = Pango.AttrList()
        for attr in (Pango.attr_background_new(0x4260, 0x6950, 0x4bd0),
                     Pango.attr_foreground_new(0xffff, 0xffff, 0xffff)):
            attr.start_index, attr.end_index = start, end
            attrs.insert(attr)
        return attrs

    def _visible(self):
        return [column for column in self.tree.get_columns()
                if column in self.columns and column.get_visible()]

    def _text(self, row, index):
        value = row[index]
        return str(self.format_value(index, value) if self.format_value else value)

    def _point(self, path, column, offset):
        return (Gtk.TreeRowReference.new(self.tree.get_model(), path), column, offset)

    def _resolve(self, point):
        if point is None or not point[0].valid():
            return None
        visible = self._visible()
        if point[1] not in visible:
            return None
        return (point[0].get_path().get_indices()[0], visible.index(point[1]), point[2])

    def _bounds(self):
        start, end = self._resolve(self._anchor), self._resolve(self._end)
        return sorted((start, end)) if start is not None and end is not None and start != end else None

    def clear_selection(self):
        had_selection = self._bounds() is not None
        self._anchor = self._end = None
        self._pressed = self._dragging = False
        self._stop_scroll()
        self.tree.queue_draw()
        return had_selection

    def _paint_cell(self, column, renderer, model, itr, index):
        if self.cell_data:
            self.cell_data(column, renderer, model, itr, index)
        if renderer.get_property('attributes') is not None:
            renderer.set_property('attributes', None)
        bounds = self._bounds()
        if not bounds:
            return
        first, last = bounds
        row = model.get_path(itr).get_indices()[0]
        visible = self._visible()
        if column not in visible:
            return
        cell = visible.index(column)
        if (row, cell) < first[:2] or (row, cell) > last[:2]:
            return
        text = renderer.get_property('text') or ''
        start = first[2] if (row, cell) == first[:2] else 0
        end = last[2] if (row, cell) == last[:2] else len(text)
        if start >= end:
            return
        if start == 0 and end >= len(text):
            attrs = self._full_attrs
        else:
            attrs = self._attributes(len(text[:start].encode('utf-8')), len(text[:end].encode('utf-8')))
        renderer.set_property('attributes', attrs)

    def _hit(self, x, y):
        window = self.tree.get_bin_window()
        if window is None or not len(self.tree.get_model()):
            return None
        visible = self._visible()
        if not visible:
            return None
        width, height = window.get_width(), window.get_height()
        px, py = max(0, min(width - 1, int(x))), max(0, min(height - 1, int(y)))
        hit = self.tree.get_path_at_pos(px, py)
        if hit:
            path, column = hit[:2]
        else:
            path = Gtk.TreePath.new_from_indices([0 if y < 0 else len(self.tree.get_model()) - 1])
            column = visible[-1]
        if column not in visible:
            column = min(visible, key=lambda col: abs(self.tree.get_cell_area(path, col).x - px))
        model = self.tree.get_model()
        itr = model.get_iter(path)
        column.cell_set_cell_data(model, itr, False, False)
        renderer = next(r for r in column.get_cells() if isinstance(r, Gtk.CellRendererText))
        text = renderer.get_property('text') or ''
        area = self.tree.get_cell_area(path, column)
        layout = self.tree.create_pango_layout(text)
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_weight_new(renderer.get_property('weight')))
        layout.set_attributes(attrs)
        layout.set_single_paragraph_mode(renderer.get_property('single-paragraph-mode'))
        wrap = renderer.get_property('wrap-width')
        if wrap > 0:
            layout.set_width(max(1, min(wrap, area.width - 2 * renderer.get_property('xpad'))) * Pango.SCALE)
            layout.set_wrap(renderer.get_property('wrap-mode'))
        elif renderer.get_property('ellipsize') != Pango.EllipsizeMode.NONE:
            layout.set_width(max(1, area.width - 2 * renderer.get_property('xpad')) * Pango.SCALE)
            layout.set_ellipsize(renderer.get_property('ellipsize'))
        tx = int(x - area.x - renderer.get_property('xpad'))
        ty = int(y - area.y - renderer.get_property('ypad'))
        if y < area.y:
            offset = 0
        elif y >= area.y + area.height:
            offset = len(text)
        else:
            _inside, byte, trailing = layout.xy_to_index(tx * Pango.SCALE, ty * Pango.SCALE)
            offset = min(len(text), len(text.encode('utf-8')[:byte].decode('utf-8')) + trailing)
        return path, column, offset, text

    def _event_hit(self, event):
        return self._hit(event.x, event.y)

    def _start_selection(self):
        if not self._dragging:
            self._dragging = True
            if self.on_select:
                self.on_select()

    def _drag(self, _widget, event):
        if not self._pressed or not event.state & Gdk.ModifierType.BUTTON1_MASK:
            return False
        self._pointer = (event.x, event.y)
        hit = self._event_hit(event)
        if hit:
            self._end = self._point(*hit[:3])
            if self._bounds():
                self._start_selection()
            self.tree.queue_draw()
        window = self.tree.get_bin_window()
        if window and (event.y < 16 or event.y > window.get_height() - 16):
            if not self._scroll_source:
                self._scroll_source = GLib.timeout_add(40, self._auto_scroll)
        else:
            self._stop_scroll()
        return True

    def _stop_scroll(self):
        if self._scroll_source:
            GLib.source_remove(self._scroll_source)
            self._scroll_source = 0

    def _auto_scroll(self):
        if not self._pressed or self._pointer is None:
            self._scroll_source = 0
            return False
        x, y = self._pointer
        height = self.tree.get_bin_window().get_height()
        delta = min(-8, y - 16) if y < 16 else max(8, y - height + 16)
        adjustment = Gtk.Scrollable.get_vadjustment(self.tree)
        previous = adjustment.get_value()
        adjustment.set_value(max(adjustment.get_lower(), min(adjustment.get_upper() - adjustment.get_page_size(),
                                                            adjustment.get_value() + delta)))
        if adjustment.get_value() == previous:
            self._scroll_source = 0
            return False
        hit = self._hit(x, y)
        if hit:
            self._end = self._point(*hit[:3])
            if self._bounds():
                self._start_selection()
            self.tree.queue_draw()
        return True

    def _release(self, _widget, event):
        if event.button != 1 or not self._pressed:
            return False
        self._stop_scroll()
        if not self._dragging and self._anchor and self._anchor[0].valid():
            self.tree.get_selection().select_path(self._anchor[0].get_path())
        elif self._bounds():
            Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY).set_text(self.selected_text(), -1)
        self._pressed = False
        return True

    def selected_row_indices(self):
        """Whole entries touched by a character selection, or the selected row."""
        bounds = self._bounds()
        if bounds:
            first, last = bounds
            end = last[0] - (1 if last[1:] == (0, 0) else 0)
            return list(range(first[0], end + 1))
        model, itr = self.tree.get_selection().get_selected()
        return [model.get_path(itr).get_indices()[0]] if itr is not None else []

    def selected_text(self):
        bounds = self._bounds()
        if not bounds:
            return ''
        first, last = bounds
        visible, model = self._visible(), self.tree.get_model()
        rows = []
        for row_index in range(first[0], last[0] + 1):
            values = []
            for cell, column in enumerate(visible):
                if (row_index, cell) < first[:2] or (row_index, cell) > last[:2]:
                    continue
                text = self._text(model[row_index], self.columns[column])
                start = first[2] if (row_index, cell) == first[:2] else 0
                end = last[2] if (row_index, cell) == last[:2] else len(text)
                values.append(text[start:end])
            rows.append('\t'.join(values))
        return '\n'.join(rows)

    def select_all(self):
        model, visible = self.tree.get_model(), self._visible()
        if not len(model) or not visible:
            return
        self._anchor = self._point(Gtk.TreePath.new_from_indices([0]), visible[0], 0)
        last = len(model) - 1
        self._end = self._point(Gtk.TreePath.new_from_indices([last]), visible[-1],
                                len(self._text(model[last], self.columns[visible[-1]])))
        self._start_selection()
        self.tree.queue_draw()

    def _key(self, _widget, event):
        control = event.state & Gdk.ModifierType.CONTROL_MASK
        if control and event.keyval in (Gdk.KEY_c, Gdk.KEY_C):
            text = self.selected_text()
            if text:
                self.copy_text(text)
                return True
        if control and event.keyval in (Gdk.KEY_a, Gdk.KEY_A):
            self.select_all()
            return True
        if event.keyval == Gdk.KEY_Escape:
            return self.clear_selection()
        return False

    def row_text(self, row):
        return '\t'.join(self._text(row, self.columns[column]) for column in self._visible())

    def all_text(self):
        return '\n'.join(self.row_text(row) for row in self.tree.get_model())

    def copy_text(self, value):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(value, -1)

    def _destroy(self, *_):
        if self._disposed:
            return
        self._disposed = True
        self._stop_scroll()
        for owner, handler in self._subscriptions:
            owner.disconnect(handler)
        self._subscriptions.clear()
        self.extra_actions = ()
        self.on_select = self.cell_data = self.format_value = None
        self._anchor = self._end = None
        # Native GTK retains these Python callbacks beyond widget destruction.
        # Remove references back to a page so host switching can collect it.
        model = self.tree.get_model()
        if model is not None:
            _column, order = model.get_sort_column_id()
            model.set_sort_column_id(Gtk.TREE_SORTABLE_UNSORTED_SORT_COLUMN_ID, order if order is not None else Gtk.SortType.ASCENDING)
        for column in self.tree.get_columns():
            sort_id = column.get_sort_column_id()
            if model is not None and sort_id >= 0:
                model.set_sort_func(sort_id, _empty_compare)
            for renderer in column.get_cells():
                column.set_cell_data_func(renderer, None)

    def button_press(self, tree, event):
        if event.button not in (1, 3):
            return False
        if not tree.get_path_at_pos(int(event.x), int(event.y)):
            if event.button == 1:
                self.clear_selection()
            return False
        hit = self._event_hit(event)
        if not hit:
            return False
        path, column, offset, text = hit
        if event.button == 1:
            self.clear_selection()
            tree.grab_focus()
            self._anchor = self._end = self._point(path, column, offset)
            self._pressed = True
            if event.type == Gdk.EventType._2BUTTON_PRESS:
                start = min(offset, max(0, len(text) - 1))
                end = start
                while start > 0 and not text[start - 1].isspace():
                    start -= 1
                while end < len(text) and not text[end].isspace():
                    end += 1
                self._anchor = self._point(path, column, start)
                self._end = self._point(path, column, end)
                self._start_selection()
                tree.queue_draw()
            elif event.type == Gdk.EventType._3BUTTON_PRESS:
                visible = self._visible()
                self._anchor = self._point(path, visible[0], 0)
                self._end = self._point(path, visible[-1], len(self._text(tree.get_model()[path], self.columns[visible[-1]])))
                self._start_selection()
                tree.queue_draw()
            return True
        row = tree.get_model()[path]
        tree.get_selection().select_path(path)
        cell, row_text = self._text(row, self.columns[column]), self.row_text(row)
        menu = Gtk.Menu()
        actions = [('Copy selected text', lambda *_: self.copy_text(self.selected_text())),
                   ('Select all shown text', lambda *_: self.select_all()),
                   ('Copy cell', lambda *_: self.copy_text(cell)),
                   ('Copy row', lambda *_: self.copy_text(row_text)),
                   ('Copy all shown rows', lambda *_: self.copy_text(self.all_text()))]
        for label, callback in actions + list(self.extra_actions):
            item = Gtk.MenuItem(label=label)
            if label == 'Copy selected text':
                item.set_sensitive(bool(self._bounds()))
            item.connect('activate', callback)
            menu.append(item)
        menu.show_all()
        menu.connect('selection-done', lambda widget: widget.destroy())
        menu.popup_at_pointer(event)
        return True


def selectable_readouts(widget):
    """Give labels native mouse selection and Copy menus, excluding controls."""
    if isinstance(widget, (Gtk.Button, Gtk.TreeView, Gtk.ComboBox)):
        return
    if isinstance(widget, Gtk.Label):
        widget.set_selectable(True)
    elif isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            selectable_readouts(child)


class WrappingToolbar(Gtk.FlowBox):
    """Native controls that wrap instead of imposing a wide minimum window."""
    def __init__(self):
        super().__init__()
        self.set_selection_mode(Gtk.SelectionMode.NONE)
        self.set_min_children_per_line(1)
        self.set_max_children_per_line(10)
        self.set_column_spacing(6)
        self.set_row_spacing(3)


class CommandBar(Gtk.Box):
    """Wrapping primary controls and an expanding search row; no polling."""
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.get_style_context().add_class('toolbar-card')
        self.primary = WrappingToolbar()
        self.secondary = Gtk.Box(spacing=6)
        self.secondary.set_border_width(4)
        self.pack_start(self.primary, False, False, 0)
        self.pack_start(self.secondary, False, False, 0)


def action_menu(actions):
    button = Gtk.MenuButton(label='⋯')
    button.get_accessible().set_name('More actions')
    menu = Gtk.Menu()
    for label, callback in actions:
        item = Gtk.MenuItem(label=label)
        item.connect('activate', callback)
        menu.append(item)
    menu.show_all()
    button.set_popup(menu)
    return button


class ColumnSizing:
    """Automatic fit until a header is dragged; manual widths survive re-layout."""
    RESIZE_DELAY_MS = 120
    def __init__(self, columns, renderers, changed, saved=None):
        self.columns = columns
        self.renderers = renderers
        self.changed = changed
        self.manual = {}
        self._applying = False
        self._resize_source = 0
        self._pending_widths = None
        self._last_requested = None
        self._automatic_ready = False
        self._width_handlers = []
        for index, column in enumerate(columns):
            column.set_resizable(True)
            column.set_max_width(-1)
            self._width_handlers.append((column, column.connect('notify::fixed-width', self._user_width, index)))
        self.restore(saved or {})

    def restore(self, saved):
        self._applying = True
        try:
            for index, column in enumerate(self.columns):
                key = column.get_title() or 'Severity'
                width = saved.get(key)
                if type(width) is int:
                    width = max(24, column.get_min_width(), min(4096, width))
                    self.manual[index] = width
                    column.set_fixed_width(width)
                    column.queue_resize()
                    self._wrap(index, width)
        finally:
            self._applying = False

    def saved_widths(self):
        return {self.columns[index].get_title() or 'Severity': width
                for index, width in self.manual.items()}

    def _wrap(self, index, width):
        renderer = self.renderers[index]
        if renderer is not None:
            width = max(24, width - 12)
            if renderer.get_property('wrap-width') != width:
                renderer.set_property('wrap-width', width)
                return True
        return False

    def _user_width(self, column, _spec, index):
        if self._applying:
            return
        self.cancel_pending()
        self._last_requested = None
        width = max(column.get_min_width(), column.get_fixed_width())
        self.manual[index] = width
        # Save the width immediately, but defer expensive wrapped-row layout
        # while the user drags a column divider.
        self._automatic_ready = True
        self._pending_widths = tuple(col.get_fixed_width() for col in self.columns)
        self._resize_source = GLib.timeout_add(self.RESIZE_DELAY_MS, self._finish_resize)

    def cancel_pending(self):
        if self._resize_source:
            GLib.source_remove(self._resize_source)
            self._resize_source = 0
        self._pending_widths = None

    def dispose(self):
        self.cancel_pending()
        for column, handler in self._width_handlers:
            column.disconnect(handler)
        self._width_handlers.clear()
        self.changed = lambda: None

    def apply_deferred(self, widths):
        # Keep vertical allocations cheap and collapse horizontal drag events.
        widths = tuple(widths)
        if widths == self._last_requested:
            return
        self._last_requested = widths
        self.cancel_pending()
        if not self._automatic_ready:
            self._automatic_ready = True
            self.apply(widths)
            return
        self._pending_widths = widths
        self._resize_source = GLib.timeout_add(self.RESIZE_DELAY_MS, self._finish_resize)

    def _finish_resize(self):
        self._resize_source = 0
        widths, self._pending_widths = self._pending_widths, None
        if widths is not None:
            self.apply(widths)
        return False

    def apply(self, widths):
        changed = False
        self._applying = True
        try:
            for index, (column, width) in enumerate(zip(self.columns, widths)):
                if width <= 0:
                    continue
                width = self.manual.get(index, width)
                if column.get_fixed_width() != width:
                    column.set_fixed_width(width)
                    column.queue_resize()
                    changed = True
                changed = self._wrap(index, width) or changed
        finally:
            self._applying = False
        if changed:
            self.changed()

    def reset(self):
        self.cancel_pending()
        self._last_requested = None
        self.manual.clear()
