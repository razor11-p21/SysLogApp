# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Pango, GLib
from syslogapp.widgets import TableTextAccess
from syslogapp.pages.network import NetworkPage
from syslogapp.pages.overview import OverviewPage


@unittest.skipUnless(Gtk.init_check()[0], 'No GTK desktop display')
class TextAccessTests(unittest.TestCase):
    def setUp(self):
        self.store = Gtk.ListStore(str, str)
        for row in [('first', 'literal <text> & unicode α\nsecond line'),
                    ('second', 'another message'), ('third', 'final entry')]:
            self.store.append(row)
        self.tree = Gtk.TreeView(model=self.store)
        self.columns = []
        for i in range(2):
            renderer = Gtk.CellRendererText()
            renderer.set_property('yalign', 0)
            renderer.set_property('wrap-mode', Pango.WrapMode.WORD_CHAR)
            renderer.set_property('wrap-width', 350)
            column = Gtk.TreeViewColumn(str(i), renderer, text=i)
            column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            column.set_fixed_width(160 if i == 0 else 380)
            self.tree.append_column(column)
            self.columns.append(column)
        self.access = TableTextAccess(self.tree, dict(zip(self.columns, range(2))), on_select=Mock())
        self.window = Gtk.OffscreenWindow()
        self.window.set_default_size(600, 250)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.add(self.tree)
        self.window.add(self.scroll)
        self.window.show_all()
        self.settle()

    def tearDown(self):
        self.window.destroy()

    def settle(self):
        loop = GLib.MainLoop()
        GLib.timeout_add(40, lambda: (loop.quit(), False)[1])
        loop.run()
        for _ in range(1000):
            if not Gtk.events_pending():
                break
            Gtk.main_iteration_do(False)

    def event_at(self, row, cell, char):
        path = Gtk.TreePath.new_from_indices([row])
        column = self.columns[cell]
        area = self.tree.get_cell_area(path, column)
        renderer = column.get_cells()[0]
        text = self.store[row][cell]
        layout = self.tree.create_pango_layout(text)
        layout.set_width(renderer.get_property('wrap-width') * Pango.SCALE)
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        position = layout.index_to_pos(len(text[:char].encode('utf-8')))
        return SimpleNamespace(x=area.x + renderer.get_property('xpad') + position.x / Pango.SCALE,
                               y=area.y + renderer.get_property('ypad') + position.y / Pango.SCALE + 3,
                               button=1, type=Gdk.EventType.BUTTON_PRESS,
                               state=Gdk.ModifierType.BUTTON1_MASK)

    def drag(self, start, end):
        self.assertTrue(self.access.button_press(self.tree, self.event_at(*start)))
        self.assertTrue(self.access._drag(self.tree, self.event_at(*end)))
        self.access._release(self.tree, self.event_at(*end))
        self.settle()

    def test_click_keeps_all_text_visible_without_creating_editor(self):
        before = list(tuple(row) for row in self.store)
        event = self.event_at(0, 1, 3)
        self.access.button_press(self.tree, event)
        self.access._release(self.tree, event)
        self.settle()
        self.assertEqual(self.tree.get_children(), [])
        self.assertEqual(list(tuple(row) for row in self.store), before)
        self.assertFalse(self.columns[1].get_cells()[0].get_property('editable'))
        self.columns[1].cell_set_cell_data(self.store, self.store.get_iter_first(), False, False)
        self.assertEqual(self.columns[1].get_cells()[0].get_property('text'), before[0][1])
        self.access.on_select.assert_not_called()

    def test_drag_spans_columns_and_rows_and_copies_exact_partial_range(self):
        self.drag((0, 1, 3), (2, 1, 5))
        expected = self.store[0][1][3:] + '\nsecond\tanother message\nthird\tfinal'
        self.assertEqual(self.access.selected_text(), expected)
        self.access.on_select.assert_called_once()
        self.access._key(self.tree, SimpleNamespace(state=Gdk.ModifierType.CONTROL_MASK, keyval=Gdk.KEY_c))
        self.assertEqual(Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text(), expected)
        self.assertEqual(self.tree.get_children(), [])
        self.columns[1].cell_set_cell_data(self.store, self.store.get_iter_first(), False, False)
        self.assertIsNotNone(self.columns[1].get_cells()[0].get_property('attributes'))

    def test_reverse_drag_and_multiline_unicode_selection(self):
        self.drag((1, 1, 7), (0, 1, 25))
        self.assertEqual(self.access.selected_text(), self.store[0][1][25:] + '\nsecond\tanother')
        self.assertTrue(self.access.clear_selection())
        self.assertEqual(self.access.selected_text(), '')

    def test_select_all_follows_sort_and_visible_columns(self):
        self.store.set_sort_column_id(0, Gtk.SortType.DESCENDING)
        self.columns[0].set_visible(False)
        self.access.select_all()
        self.access._paint_cell(self.columns[0], self.columns[0].get_cells()[0],
                                self.store, self.store.get_iter_first(), 0)
        self.assertEqual(self.access.selected_text(), 'final entry\nanother message\nliteral <text> & unicode α\nsecond line')
        self.assertEqual(self.access.selected_text(), self.access.all_text())
        self.store.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        self.assertEqual(self.access.selected_text(), '')

    def test_drag_at_bottom_scrolls_and_release_removes_timer(self):
        for i in range(80):
            self.store.append([f'host{i}', 'message'])
        self.settle()
        self.access.button_press(self.tree, self.event_at(0, 1, 2))
        event = SimpleNamespace(x=220, y=self.tree.get_bin_window().get_height() + 30,
                                button=1, state=Gdk.ModifierType.BUTTON1_MASK)
        self.access._drag(self.tree, event)
        self.assertTrue(self.access._scroll_source)
        self.access._auto_scroll()
        self.assertGreater(Gtk.Scrollable.get_vadjustment(self.tree).get_value(), 0)
        self.access._release(self.tree, event)
        self.assertEqual(self.access._scroll_source, 0)
        self.assertIn('\n', self.access.selected_text())

    def test_selection_survives_append_and_resize_but_not_eviction(self):
        self.drag((0, 1, 1), (1, 1, 4))
        before = self.access.selected_text()
        self.store.append(['fourth', 'new event'])
        self.columns[1].set_fixed_width(210)
        self.settle()
        self.assertEqual(self.access.selected_text(), before)
        self.store.remove(self.store.get_iter_first())
        self.assertEqual(self.access.selected_text(), '')

    def test_local_and_remote_refresh_keep_completed_status(self):
        for host in (None, SimpleNamespace(target='test@remote', overview=Mock())):
            app = SimpleNamespace(host=host, config={}, run_async=Mock())
            page = NetworkPage(app)
            page._snapshot = {'time': '12:00:00'}
            page.status.set_text('LIVE · completed snapshot')
            page.refresh(automatic=True)
            self.assertEqual(page.status.get_text(), 'LIVE · completed snapshot')
            self.assertEqual(page.socket_scroll.get_margin_bottom(), 12)
            self.assertTrue(page.status.get_selectable())
            page.destroy()
            page = OverviewPage(app)
            page._text = 'previous snapshot'
            page.status.set_text('Snapshot: 12:00:00')
            page._refresh_clicked()
            self.assertEqual(page.status.get_text(), 'Snapshot: 12:00:00')
            page.destroy()
