#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic hidden-tab GTK work; excludes journal/SSH collection and GPU usage."""
import argparse
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', default=str(Path(__file__).resolve().parents[1]))
args = parser.parse_args()
sys.path.insert(0, args.source)
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
from syslogapp.pages.logs import LogsPage
app = SimpleNamespace(config={'log_lines': 2000}, run_async=lambda *a: None,
                      window=SimpleNamespace(toast=lambda *a, **kw: None))
page = LogsPage(app)
page._mapped_once = True
window = Gtk.Window()
notebook = Gtk.Notebook()
notebook.append_page(page, Gtk.Label(label='Logs'))
notebook.append_page(Gtk.Label(label='Other tab'), Gtk.Label(label='Other'))
window.add(notebook)
window.show_all()
while Gtk.events_pending(): Gtk.main_iteration_do(False)
page.live.handler_block_by_func(page._on_live)
page.live.set_active(True)
page.live.handler_unblock_by_func(page._on_live)
notebook.set_current_page(1)
while Gtk.events_pending(): Gtk.main_iteration_do(False)
mutations = [0]
def changed(*_): mutations[0] += 1
for signal in ('row-inserted', 'row-deleted', 'row-changed'): page.store.connect(signal, changed)
start = time.process_time()
for batch in range(100):
    for index in range(100):
        i = batch*100+index
        row = dict(time='2026-10-28 12:00:00', unit='fixture.service', level='Info', priority=6,
                   message=f'Event {i}: '+ 'Synthetic long message. '*12,
                   raw={'MESSAGE': f'Event {i}', '__REALTIME_TIMESTAMP':str(1793188800000000+i)})
        page._queue_live(row, page._live_generation)
    if page._drain_source: GLib.source_remove(page._drain_source)
    page._drain_live(page._live_generation)
cpu = (time.process_time()-start)*1000
hidden_mutations=mutations[0]
start=time.process_time()
notebook.set_current_page(0)
restore_cpu=(time.process_time()-start)*1000
print(json.dumps(dict(hidden_cpu_ms=round(cpu,3), hidden_model_mutations=hidden_mutations,
                      retained_events=len(page._all_rows), restored_model_rows=len(page.store),
                      restore_callback_cpu_ms=round(restore_cpu,3))))
window.destroy()
