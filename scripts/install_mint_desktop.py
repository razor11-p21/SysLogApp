# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Install the workspace build and add its Cinnamon launcher applet."""
import json
import shutil
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

from gi.repository import Gio

workspace = Path(__file__).resolve().parents[1]
user_home = Path.home()
settings = Gio.Settings.new('org.cinnamon')
if not settings.is_writable('enabled-applets') or not settings.is_writable('next-applet-id'):
    raise RuntimeError('Cinnamon panel settings are not writable')
enabled = list(settings.get_strv('enabled-applets'))
next_id = settings.get_int('next-applet-id')
backup = workspace / 'backups' / datetime.now().strftime('%Y%m%d-%H%M%S')
backup.mkdir(parents=True)
(backup / 'cinnamon-panel.json').write_text(json.dumps({
    'enabled-applets': enabled, 'next-applet-id': next_id,
}, indent=2))

uuid = 'syslogapp@razor'
applet_target = user_home / '.local/share/cinnamon/applets' / uuid
with tarfile.open(backup / 'previous-installation.tar.gz', 'w:gz') as archive:
    for relative in ('.local/share/syslogapp', '.local/bin/syslogapp',
                     '.local/share/applications/syslogapp.desktop',
                     '.local/share/cinnamon/applets/' + uuid):
        source = user_home / relative
        if source.exists():
            archive.add(source, arcname=relative)

subprocess.run(['bash', str(workspace / 'install.sh')], cwd=workspace, check=True)
installed = user_home / '.local/share/syslogapp/syslogapp/__init__.py'
if '2.0.0-preview18' not in installed.read_text():
    raise RuntimeError('Installed version verification failed')
shutil.copytree(workspace / 'cinnamon' / uuid, applet_target, dirs_exist_ok=True)

existing = [item for item in enabled if item.split(':')[3] == uuid]
if existing:
    entry = existing[0]
else:
    definitions = [item.split(':') for item in enabled]
    panel = next((item[0] for item in definitions if item[3] == 'grouped-window-list@cinnamon.org'), 'panel1')
    position = max((int(item[2]) for item in definitions if item[0] == panel and item[1] == 'left'), default=-1) + 1
    instance_id = max(next_id, max((int(item[4]) for item in definitions), default=-1) + 1)
    entry = f'{panel}:left:{position}:{uuid}:{instance_id}'
    settings.delay()
    settings.set_int('next-applet-id', instance_id + 1)
    settings.set_strv('enabled-applets', [*enabled, entry])
    settings.apply()
    Gio.Settings.sync()
if entry not in settings.get_strv('enabled-applets'):
    raise RuntimeError('Panel applet setting was not saved')
print('Installed version: 2.0.0-preview18')
print('Applet enabled:', entry)
print('Backup:', backup)
