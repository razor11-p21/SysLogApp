# SPDX-License-Identifier: GPL-3.0-or-later
import gc,json,os,sys,weakref
from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
from syslogapp.pages.logs import LogsPage
from syslogapp.pages.network import NetworkPage
from syslogapp.pages.overview import OverviewPage
from syslogapp.pages.maintenance import MaintenancePage
refs=[]
def cycle():
 for cls in (LogsPage,NetworkPage,OverviewPage,MaintenancePage):
  app=SimpleNamespace(config={},run_async=lambda *args:None,window=SimpleNamespace(toast=Mock()))
  page=cls(app)
  refs.append((weakref.ref(page), cls.__name__))
  page.destroy()
 for _ in range(100):
  if Gtk.events_pending():Gtk.main_iteration_do(False)
 gc.collect()
cycle()
start=len(os.listdir('/proc/self/fd'))
for _ in range(20):cycle()
report = {'destroyed_page_wrappers_retained':sum(ref() is not None for ref, name in refs),'retained_by_class':{name:sum(ref() is not None for ref, cls in refs if cls==name) for name in ('LogsPage','NetworkPage','OverviewPage','MaintenancePage')},'pages_created':len(refs),'fd_before':start,'fd_after':len(os.listdir('/proc/self/fd'))}
assert report['destroyed_page_wrappers_retained'] == 0, report
assert report['fd_after'] <= report['fd_before'], report
print(json.dumps(report))
