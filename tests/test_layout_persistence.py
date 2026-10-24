# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from syslogapp import config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name)/'settings'
        self.file=self.directory/'config.json'
        for name,value in (('CONFIG_DIR',self.directory),('CONFIG_FILE',self.file)):
            patcher=patch.object(config,name,value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_corrupt_and_older_settings_are_safe(self):
        self.directory.mkdir()
        self.file.write_text('{broken')
        self.assertEqual(config.load_config()['window'],{})
        self.file.write_text('{"log_lines":250}')
        self.assertEqual(config.load_config(),{'log_lines':250,'window':{},'columns':{},'hosts':[]})
        data=config.normalized({'window':{'width':999999,'height':-1,'maximized':'yes'},
            'columns':{'network':{'Local address':999999,'PID':True,'unknown':100},'logs':[]}})
        self.assertEqual(data['window'],{'width':8192,'height':480})
        self.assertEqual(data['columns'],{'network':{'Local address':4096}})

    def test_atomic_write_failure_preserves_old_file(self):
        config.save_config({'log_lines':250})
        previous=self.file.read_bytes()
        with patch.object(config.os,'replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                config.save_config({'log_lines':500})
        self.assertEqual(self.file.read_bytes(),previous)
        self.assertEqual(list(self.directory.iterdir()),[self.file])

    def test_separate_pages_and_widths_round_trip(self):
        data={'log_lines':250,'window':{'width':980,'height':650,'maximized':False},
              'columns':{'logs':{'Message':420},'network':{'Local address':180,'PID':70},
                         'overview':{'Field':160}}}
        config.save_config(data)
        self.assertEqual(config.load_config(),dict(data,hosts=[]))


try:
    import gi
    gi.require_version('Gtk','3.0')
    from gi.repository import Gtk
    HAS_DISPLAY=Gtk.init_check()[0]
except ImportError:
    HAS_DISPLAY=False


@unittest.skipUnless(HAS_DISPLAY,'GTK desktop required')
class LayoutIntegrationTests(unittest.TestCase):
    def run_scenario(self,name):
        import subprocess
        import sys
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('layout_ui_check.py')),
                               'LayoutTests.'+name],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertNotIn('CRITICAL',result.stderr)

    def test_close_reopen_and_fit_columns(self):
        self.run_scenario('test_close_and_reopen_restores_size_and_columns')

    def test_maximize_and_busy_close(self):
        self.run_scenario('test_maximized_preserves_normal_size_and_busy_close_does_not_save')
