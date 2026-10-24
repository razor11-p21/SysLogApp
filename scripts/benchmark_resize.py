#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Synthetic GTK horizontal-resize benchmark; no settings writes or system probes.

Run: /usr/bin/python3 scripts/benchmark_resize.py [source-directory] [--profile]
Uses an offscreen window with 1,000 synthetic wrapped journal records. CPU time
and resize-step gaps do not measure compositor performance or pointer latency.
"""
import sys,time,json,cProfile,pstats
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1] if len(sys.argv)>1 and not sys.argv[1].startswith('--') else str(Path(__file__).resolve().parents[1]))
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
from syslogapp.pages.logs import LogsPage
app=SimpleNamespace(config={'log_lines':2000},run_async=lambda *a:None,window=SimpleNamespace(toast=lambda *a:None))
p=LogsPage(app)
p._all_rows=[{'time':'2026-10-25 12:00:00','unit':f'service-{i%20}.service','level':'Info','priority':6,'message':('A moderately long journal message to exercise wrapping and resizing. '*4)+str(i),'raw':{'__REALTIME_TIMESTAMP':str(1700000000000000+i)}} for i in range(1000)]
p._apply_filter()
w=Gtk.OffscreenWindow();w.set_size_request(1100,650);w.add(p);w.show_all()
loop=GLib.MainLoop();GLib.timeout_add(400,lambda:(loop.quit(),False)[1]);loop.run()
widths=list(range(1100,699,-20))+list(range(700,1101,20));gaps=[];last=time.monotonic();start=last;cpu=time.process_time();index=0
profile=cProfile.Profile()
if '--profile' in sys.argv:profile.enable()
def step():
 global index,last
 now=time.monotonic();gaps.append((now-last)*1000);last=now
 if index>=len(widths):
  GLib.timeout_add(350,lambda:(loop.quit(),False)[1]);return False
 w.set_size_request(widths[index],650);w.resize(widths[index],650);index+=1;return True
GLib.timeout_add(16,step);loop.run()
if '--profile' in sys.argv:profile.disable();pstats.Stats(profile).sort_stats('cumtime').print_stats(12)
print(json.dumps({'resize_cpu_ms':round((time.process_time()-cpu)*1000,1),'wall_ms':round((time.monotonic()-start)*1000,1),'slowest_step_ms':round(max(gaps),1),'steps':len(widths)}))
w.destroy()
