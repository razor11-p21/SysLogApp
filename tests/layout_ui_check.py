# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
# Run real Gtk.Application lifecycle scenarios in their own process.
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import os
import unittest
from unittest.mock import Mock
from test_layout_persistence import ConfigTests, config


try:
    import gi
    gi.require_version('Gtk','3.0')
    from gi.repository import Gtk, GLib, Gio
    from syslogapp.app import MainWindow,SysLogApplication
    HAS_DISPLAY=Gtk.init_check()[0]
except ImportError:
    HAS_DISPLAY=False


@unittest.skipUnless(HAS_DISPLAY,'GTK desktop required')
class LayoutTests(unittest.TestCase):
    def setUp(self):
        ConfigTests.setUp(self)
        self.app=SysLogApplication()
        self.app.set_application_id(f'gr.syslogapp.layoutTests.p{os.getpid()}.t{id(self)}')
        self.app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
        self.assertTrue(self.app.register(None))
        self.assertFalse(self.app.get_is_remote())
        self.app.run_async=Mock()
        self.window=None

    def tearDown(self):
        if self.window:
            self.window.destroy()
        self.app.executor.shutdown(wait=True)
        self.settle()

    def settle(self):
        loop=GLib.MainLoop()
        GLib.timeout_add(200,lambda:(loop.quit(),False)[1])
        loop.run()

    def open(self):
        self.window=MainWindow(self.app)
        self.app.window=self.window
        self.window.show_all()
        self.settle()
        return self.window

    def test_close_and_reopen_restores_size_and_columns(self):
        self.app.config['columns']={'overview':{'Field':155}}
        window=self.open()
        window.resize(940,620)
        self.settle()
        window.pages['logs'].tree_columns[3].set_fixed_width(350)
        window.notebook.set_current_page(1)
        self.settle()
        window.pages['network'].columns[2].set_fixed_width(180)
        window.pages['network'].columns[5].set_fixed_width(90)
        window.pages['network'].columns[6].set_fixed_width(77)
        self.assertFalse(self.file.exists())  # no writes during dragging
        self.assertFalse(window._delete_event())
        saved=config.load_config()
        self.assertEqual(saved['window'],{'width':940,'height':620,'maximized':False})
        self.assertEqual(saved['columns']['logs']['Message'],350)
        self.assertEqual(saved['columns']['network'],{'Local address':180,'Remote port':90,'PID':77})
        self.assertEqual(saved['columns']['overview'],{'Field':155})  # unopened tab preserved
        window.destroy()
        self.app.config=saved
        window=self.open()
        self.assertEqual(window.get_size(),(940,620))
        self.assertEqual(window.pages['logs'].tree_columns[3].get_fixed_width(),350)
        window.notebook.set_current_page(1)
        self.settle()
        network=window.pages['network']
        self.assertEqual(network.columns[2].get_fixed_width(),180)
        self.assertEqual(network.columns[5].get_fixed_width(),90)
        self.assertEqual(network.columns[6].get_fixed_width(),77)
        network._fit_columns()
        window._delete_event()
        self.assertEqual(config.load_config()['columns']['network'],{})

    def test_maximized_preserves_normal_size_and_busy_close_does_not_save(self):
        window=self.open()
        window.resize(980,650)
        self.settle()
        window.maximize()
        self.settle()
        self.assertTrue(window._maximized)
        window.notebook.set_current_page(3)
        window.pages['maintenance']._busy=True
        self.assertTrue(window._delete_event())
        self.assertFalse(self.file.exists())
        window.pages['maintenance']._busy=False
        self.assertFalse(window._delete_event())
        self.assertEqual(config.load_config()['window'],{'width':980,'height':650,'maximized':True})
        window.destroy()
        self.app.config=config.load_config()
        window=self.open()
        self.assertTrue(window._maximized)
        window.unmaximize()
        self.settle()
        self.assertEqual(window.get_size(),(980,650))



if __name__ == '__main__':
    unittest.main()

