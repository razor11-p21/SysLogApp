#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Per-user installation with dependency preflight and transactional rollback."""
import os
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REQUIRED_COMMANDS = ('journalctl', 'ip', 'ss', 'ssh')
DEPENDENCY_HINT = 'python3 python3-gi gir1.2-gtk-3.0 systemd iproute2 openssh-client'


def dependency_hint(release_path=Path('/etc/os-release')):
    """Use distro package names without executing shell content from os-release."""
    try:
        fields = dict(line.split('=', 1) for line in release_path.read_text().splitlines()
                      if '=' in line and not line.lstrip().startswith('#'))
    except OSError:
        fields = {}
    family = (fields.get('ID', '') + ' ' + fields.get('ID_LIKE', '')).replace('"', '').replace("'", '').split()
    if 'fedora' in family:
        return 'sudo dnf install python3 python3-gobject gtk3 systemd iproute openssh-clients'
    if any(name in family for name in ('linuxmint', 'ubuntu', 'debian')):
        return 'sudo apt install ' + DEPENDENCY_HINT
    return ('Install Python 3.9+, GTK3/PyGObject, journalctl, ip, ss and the OpenSSH '
            'client with your distribution package manager.')


def check_dependencies():
    missing = []
    if sys.version_info < (3, 9):
        missing.append('Python >= 3.9')
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk  # noqa: F401
    except (ImportError, ValueError) as exc:
        missing.append(f'GTK3/PyGObject ({exc})')
    missing.extend(command for command in REQUIRED_COMMANDS if not shutil.which(command))
    if missing:
        raise RuntimeError('Missing dependencies: ' + ', '.join(missing) + '\n' + dependency_hint())


def replace_file(target, data, mode):
    """Stage in the destination directory so replacement is always atomic."""
    fd, temporary_name = tempfile.mkstemp(prefix='.syslogapp-', dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
        temporary.chmod(mode)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def install(source, user_directory=None, preflight=True):
    if preflight:
        check_dependencies()
    source = Path(source)
    user_directory = Path(user_directory) if user_directory is not None else Path.home()
    share = user_directory / '.local/share'
    app = share / 'syslogapp'
    launcher = user_directory / '.local/bin/syslogapp'
    desktop = share / 'applications/syslogapp.desktop'
    for directory in (share, launcher.parent, desktop.parent):
        directory.mkdir(parents=True, exist_ok=True)
    for target in (app, launcher, desktop):
        if target.is_symlink():
            raise RuntimeError(f'Refusing to replace a symbolic link: {target}')
    transaction = Path(tempfile.mkdtemp(prefix='.syslogapp-install-', dir=share))
    stage = transaction / 'new'
    previous = transaction / 'previous-app'
    old_files = {}
    replaced_files = []
    app_replaced = False
    moved_previous = False
    try:
        stage.mkdir()
        shutil.copytree(source / 'syslogapp', stage / 'syslogapp', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copy2(source / 'syslogapp.py', stage / 'syslogapp.py')
        for name in ('LICENSE', 'AUTHORS', 'NOTICE.md'):
            if (source / name).exists():
                shutil.copy2(source / name, stage / name)
        # Syntax errors must be caught before touching the installed version.
        for path in stage.rglob('*.py'):
            compile(path.read_text(encoding='utf-8'), str(path), 'exec')
        for target in (launcher, desktop):
            old_files[target] = (target.read_bytes(), target.stat().st_mode & 0o777) if target.exists() else None
        # Retain on-disk originals even if rollback itself encounters I/O errors.
        manifest = {}
        for index, (target, old) in enumerate(old_files.items()):
            filename = f'original-file-{index}'
            if old is not None:
                (transaction / filename).write_bytes(old[0])
            manifest[str(target)] = {'backup': filename if old is not None else None,
                                     'mode': old[1] if old is not None else None}
        (transaction / 'rollback-files.json').write_text(json.dumps(manifest, indent=2))
        if app.exists():
            os.replace(app, previous)
            moved_previous = True
        os.replace(stage, app)
        app_replaced = True
        # Explicit system Python avoids unrelated virtual environments.
        import shlex
        command = ('#!/bin/sh\nexec /usr/bin/python3 ' + shlex.quote(str(app / 'syslogapp.py')) + ' "$@"\n').encode()
        if old_files[launcher] is None or old_files[launcher][0] != command:
            replaced_files.append(launcher)
            replace_file(launcher, command, 0o755)
        if old_files[desktop] is None:
            # Desktop Exec uses its own quoting rules, not shell quoting.
            escaped = str(launcher).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
            icon = str(app / 'syslogapp/assets/syslogapp.svg') if (app / 'syslogapp/assets/syslogapp.svg').exists() else 'utilities-terminal'
            entry = f'[Desktop Entry]\nType=Application\nName=SysLogApp\nComment=Terminal-style journal and network viewer\nExec="{escaped}"\nIcon={icon}\nTerminal=false\nCategories=System;Utility;\nStartupNotify=true\nStartupWMClass=Syslogapp.py\n'
            replaced_files.append(desktop)
            replace_file(desktop, entry.encode(), 0o644)
        if moved_previous:
            destination = share / 'syslogapp-backups'
            destination.mkdir(exist_ok=True)
            backup = destination / ('previous-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
            os.replace(previous, backup)
            print('Previous installation retained:', backup)
        shutil.rmtree(transaction, ignore_errors=True)
    except BaseException:
        rollback_errors = []
        for target in reversed(replaced_files):
            try:
                old = old_files[target]
                if old is None:
                    target.unlink(missing_ok=True)
                else:
                    replace_file(target, *old)
            except OSError as exc:
                rollback_errors.append(str(exc))
        try:
            if app_replaced and app.exists():
                shutil.rmtree(app)
            if moved_previous and previous.exists():
                os.replace(previous, app)
        except OSError as exc:
            rollback_errors.append(str(exc))
        if rollback_errors:
            print('Rollback needs attention; backup preserved at ' + str(transaction) + ': ' + '; '.join(rollback_errors), file=sys.stderr)
        else:
            shutil.rmtree(transaction, ignore_errors=True)
        raise
    print('Installed:', app)
    print('Launcher:', launcher)
    print('Settings preserved in:', user_directory / '.config/syslogapp')


if __name__ == '__main__':
    try:
        install(Path(__file__).resolve().parents[1])
    except Exception as exc:
        print('Installation failed: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
