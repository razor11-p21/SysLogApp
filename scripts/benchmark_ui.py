#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Synthetic GTK CPU/RAM benchmark; no network probes or settings writes.

Requires a GTK desktop. Measurements exclude journal/ip/ss subprocesses and GPU
usage. Run separate processes for before/after comparisons; do not compare
profiled timings to unprofiled timings. This is not a performance guarantee.
"""
import argparse
import cProfile
import json
import pstats
import sys
import time
from pathlib import Path
from types import SimpleNamespace
p=argparse.ArgumentParser()
p.add_argument('--source',default=str(Path(__file__).resolve().parents[1]))
p.add_argument('--large-cache',action='store_true',help='Measure retained cache memory with 256 synthetic 32 KiB strings; no GTK required')
p.add_argument('--profile',action='store_true')
a=p.parse_args()
sys.path.insert(0,a.source)
if a.large_cache:
 import gc
 import tracemalloc
 from syslogapp.sorting import natural_key
 tracemalloc.start()
 for i in range(256): natural_key(str(i)+'X'*32768)
 gc.collect()
 current,peak=tracemalloc.get_traced_memory()
 print(json.dumps({'retained_mib':round(current/1048576,3),'peak_mib':round(peak/1048576,3)}))
 raise SystemExit(0)
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
from syslogapp.pages.logs import LogsPage
from syslogapp.pages.network import NetworkPage
app=SimpleNamespace(config={'log_lines':2000},run_async=lambda *args:None,window=SimpleNamespace(toast=lambda *args:None))
def logrow(i):
 return {'time':'2026-10-21 12:00:00','unit':f'worker-{i%31}.service','level':'Info','priority':6,
         'message':f'Event {i} completed successfully for request {i*17}',
         'raw':{'__REALTIME_TIMESTAMP':str(1792584000000000+i),'sequence':i}}
base={'interfaces':[],'routes':[],'errors':[],'limited':False,'time':'12:00:00','processes':True}
rows=[{'protocol':'TCP','state':'ESTAB','local':f'10.0.{i//250}.{i%250+1}:{10000+i}',
       'peer':f'192.0.2.{i%250+1}:443','process':f'users:(("worker-{i%31}",pid={1000+i%31},fd={i%60}))',
       'recv':'0','send':'0'} for i in range(1000)]
results={}
prof=cProfile.Profile()
if a.profile:prof.enable()
def bench(name,func,repetitions=3):
 samples=[]
 for _ in range(repetitions):
  begin=time.process_time()
  func()
  samples.append(time.process_time()-begin)
 results[name+'_cpu_ms']=round(sorted(samples)[len(samples)//2]*1000,3)
logs=LogsPage(app)
logs._all_rows=[logrow(i) for i in range(2000)]
bench('logs_2000_load',logs._apply_filter)
logs.live.handler_block_by_func(logs._on_live)
logs.live.set_active(True)
logs.live.handler_unblock_by_func(logs._on_live)
seq=[2000]
def burst():
 for i in range(seq[0],seq[0]+100):logs._queue_live(logrow(i),logs._live_generation)
 seq[0]+=100
 if logs._drain_source:
  GLib.source_remove(logs._drain_source);logs._drain_source=0
 logs._drain_live(logs._live_generation)
bench('logs_100_event_burst',burst)
network=NetworkPage(app)
bench('network_1000_load',lambda: (network.store.clear(),setattr(network,'_display_signature',()),network._loaded(dict(base,sockets=rows),None)))
counter=[0]
def sparse_change():
 counter[0]+=1
 modified=list(rows)
 modified[0]=dict(rows[0],peer=f'192.0.2.1:{440+counter[0]}')
 network._loaded(dict(base,sockets=modified),None)
bench('network_1_row_change',sparse_change,5)
bench('network_unchanged',lambda:network._loaded(dict(base,sockets=network._rows),None),5)
if a.profile:
 prof.disable();pstats.Stats(prof).sort_stats('cumtime').print_stats(18)
# Real GTK idle loop, without synthetic live traffic or snapshot timers.
window=Gtk.OffscreenWindow();window.set_size_request(1100,700);window.add(network);window.show_all()
loop=GLib.MainLoop()
GLib.timeout_add(2000,lambda:(loop.quit(),False)[1]);loop.run()
cpu=time.process_time();wall=time.monotonic()
GLib.timeout_add(1500,lambda:(loop.quit(),False)[1]);loop.run()
results['idle_cpu_ms']=round((time.process_time()-cpu)*1000,3)
results['idle_wall_ms']=round((time.monotonic()-wall)*1000,3)
with open('/proc/self/status') as f:
 for line in f:
  if line.startswith(('VmRSS:','VmHWM:')):
   results[line.split(':')[0]+'_kib']=int(line.split()[1])
window.destroy();logs.destroy()
print(json.dumps(results,sort_keys=True))
