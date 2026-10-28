#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Build local Debian packages and a clean source archive without installing."""
import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755 if executable else 0o644)


def package(stage, name, version, maintainer, depends, description, destination):
    doc = stage / 'usr/share/doc' / name
    doc.mkdir(parents=True, exist_ok=True)
    copyright_text = ('Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n'
                      'Upstream-Name: SysLogApp\n\nFiles: *\nCopyright: 2026 pit pitopoulos\nLicense: GPL-3+\n'
                      ' This program is free software: you can redistribute it and/or modify\n'
                      ' it under the terms of the GNU General Public License as published by\n'
                      ' the Free Software Foundation, either version 3 of the License, or\n'
                      ' (at your option) any later version.\n'
                      ' .\n This program is distributed without any warranty.\n'
                      ' On Debian systems the full GPL version 3 text is available in\n'
                      ' /usr/share/common-licenses/GPL-3.\n')
    write(doc / 'copyright', copyright_text)
    shutil.copy2(ROOT / 'NOTICE.md', doc / 'NOTICE.md')
    shutil.copy2(ROOT / 'AUTHORS', doc / 'AUTHORS')
    changelog = f'{name} ({version}) unstable; urgency=medium\n\n  * Publish the first public alpha, based on Preview 70.\n  * Include journal, network, SSH, overview and maintenance tools.\n\n -- {maintainer}  Wed, 28 Oct 2026 00:00:00 +0200\n'
    (doc / 'changelog.Debian.gz').write_bytes(gzip.compress(changelog.encode(), mtime=0))
    files = sorted(path for path in stage.rglob('*') if path.is_file())
    installed_size = sum(path.stat().st_size for path in files) // 1024 + 1
    write(stage / 'DEBIAN/control', f'Package: {name}\nVersion: {version}\nSection: utils\nPriority: optional\nArchitecture: all\nMaintainer: {maintainer}\nInstalled-Size: {installed_size}\nDepends: {depends}\nDescription: {description}\n')
    if name == 'syslogapp':
        with (stage / 'DEBIAN/control').open('a') as control:
            control.write('Suggests: syslogapp-cinnamon-applet, pkexec, logrotate, gir1.2-secret-1, gnome-keyring\n')
    checksums = ''.join(hashlib.md5(path.read_bytes()).hexdigest() + '  ' + str(path.relative_to(stage)) + '\n' for path in files)
    write(stage / 'DEBIAN/md5sums', checksums)
    for path in stage.rglob('*'):
        if path.is_dir():
            path.chmod(0o755)
        elif path != stage / 'usr/bin/syslogapp':
            path.chmod(0o644)
    output = destination / f'{name}_{version}_all.deb'
    subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(stage), str(output)], check=True)
    return output


def build(draft=False):
    metadata = json.loads((ROOT / 'packaging/release.json').read_text())
    email = metadata.get('maintainer_email')
    if draft and not email:
        email = 'release-preparation@example.invalid'
    if not email or not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+', email):
        raise ValueError('Set the real public maintainer email in packaging/release.json before building a release')
    version = metadata['version']
    if draft:
        version = version.replace('-1', '+draft1-1')
    release_directory = metadata.get('release_directory', 'alpha1')
    if not re.fullmatch(r'[A-Za-z0-9._-]+', release_directory) or release_directory in ('.', '..'):
        raise ValueError('Release directory must be a simple directory name')
    destination = ROOT / 'dist' / ('draft' if draft else release_directory)
    destination.mkdir(parents=True, exist_ok=True)
    maintainer = f"{metadata['author']} <{email}>"
    with tempfile.TemporaryDirectory(prefix='syslogapp-build-') as temporary:
        stage = Path(temporary) / 'main'
        program = stage / 'usr/share/syslogapp'
        program.mkdir(parents=True)
        shutil.copytree(ROOT / 'syslogapp', program / 'syslogapp', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copy2(ROOT / 'syslogapp.py', program / 'syslogapp.py')
        write(stage / 'usr/bin/syslogapp', '#!/bin/sh\nexec /usr/bin/python3 /usr/share/syslogapp/syslogapp.py "$@"\n', executable=True)
        desktop = stage / 'usr/share/applications/syslogapp.desktop'
        desktop.parent.mkdir(parents=True)
        shutil.copy2(ROOT / 'packaging/syslogapp.desktop', desktop)
        subprocess.run(['desktop-file-validate', str(desktop)], check=True)
        icon = stage / 'usr/share/icons/hicolor/scalable/apps/syslogapp.svg'
        icon.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / 'syslogapp/assets/syslogapp.svg', icon)
        docs = stage / 'usr/share/doc/syslogapp'
        docs.mkdir(parents=True)
        for name in ('README.md', 'RELEASE.md', 'PERFORMANCE.md', 'COMPATIBILITY.md'):
            shutil.copy2(ROOT / name, docs / name)
        man = stage / 'usr/share/man/man1/syslogapp.1.gz'
        man.parent.mkdir(parents=True)
        man.write_bytes(gzip.compress((ROOT / 'packaging/syslogapp.1').read_bytes(), mtime=0))
        # dpkg and libc-bin/getent are Essential Debian packages, implicitly available.
        dependencies = 'python3 (>= 3.9), python3-gi, gir1.2-gtk-3.0, systemd, iproute2, openssh-client'
        results = [package(stage, 'syslogapp', version, maintainer, dependencies,
                           'terminal-style journal and network viewer\n Compact GTK3 journal viewer with bounded history, filters, event details,\n batched live following and on-demand network snapshots.', destination)]
        stage = Path(temporary) / 'applet'
        applet = stage / 'usr/share/cinnamon/applets/syslogapp@razor'
        shutil.copytree(ROOT / 'cinnamon/syslogapp@razor', applet)
        results.append(package(stage, 'syslogapp-cinnamon-applet', version, maintainer,
                               f'syslogapp (= {version}), cinnamon',
                               'optional Cinnamon panel launcher for SysLogApp\n Adds an applet available in Cinnamon Applets settings.\n It does not change panel preferences or enable itself automatically.', destination))
    archive = destination / f'SysLogApp-{version}-source.tar.gz'
    names = ['LICENSE', 'AUTHORS', 'NOTICE.md', 'README.md', 'RELEASE.md', 'PERFORMANCE.md', 'COMPATIBILITY.md', 'install.sh',
             'uninstall.sh', 'run-preview.sh', 'syslogapp.py', 'syslogapp', 'cinnamon', 'scripts', 'tests', 'packaging']
    def clean(info):
        return None if '__pycache__' in Path(info.name).parts or info.name.endswith(('.pyc', '.pyo')) else info
    with tarfile.open(archive, 'w:gz') as output:
        for name in names:
            output.add(ROOT / name, arcname=f'SysLogApp-{version}/{name}', filter=clean)
    results.append(archive)
    write(destination / 'SHA256SUMS', ''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n' for path in results))
    print('Draft only; placeholder contact must not be published.' if draft else 'Local release artifacts built; nothing published.')
    print(destination)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--draft', action='store_true', help='Build private test artifacts with an explicitly invalid contact placeholder')
    args = parser.parse_args()
    build(draft=args.draft)
