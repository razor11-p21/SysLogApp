# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Install the workspace build and add its Cinnamon launcher applet."""
import json
import shutil
import subprocess
import tarfile
import runpy
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
expected_version = runpy.run_path(str(workspace / 'syslogapp/__init__.py'))['__version__']
if expected_version not in installed.read_text():
    raise RuntimeError('Installed version verification failed')
shutil.copytree(workspace / 'cinnamon' / uuid, applet_target, dirs_exist_ok=True)
# This explicitly requested desktop setup refreshes the app's icon while keeping
# the existing launcher command and all other custom desktop fields intact.
desktop = user_home / '.local/share/applications/syslogapp.desktop'
icon_path = user_home / '.local/share/syslogapp/syslogapp/assets/syslogapp.svg'
if desktop.exists():
    from install_user import replace_file
    lines = desktop.read_text().splitlines()
    lines = [f'Icon={icon_path}' if line.startswith('Icon=') else line for line in lines]
    if not any(line.startswith('Icon=') for line in lines):
        lines.append(f'Icon={icon_path}')
    replace_file(desktop, ('\n'.join(lines) + '\n').encode(), desktop.stat().st_mode & 0o777)


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
print('Installed version:', expected_version)
print('Applet enabled:', entry)
print('Backup:', backup)
