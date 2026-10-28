#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check release integrity and staged .deb contents without installing packages."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile


def check_release(directory):
    directory = Path(directory)
    entries = []
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.lstrip('*')
        if Path(name).name != name:
            raise ValueError('Checksum entry must be a filename')
        path = directory / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f'Checksum mismatch: {name}')
        entries.append(path)
    if len(entries) != 3 or len(set(entries)) != 3:
        raise ValueError('Expected main .deb, applet .deb and source archive')
    with tempfile.TemporaryDirectory(prefix='syslogapp-release-check-') as temporary:
        root = Path(temporary)
        for package in (path for path in entries if path.suffix == '.deb'):
            stage = root / package.stem
            subprocess.run(['dpkg-deb', '--extract', str(package), str(stage)], check=True)
            subprocess.run(['dpkg-deb', '--control', str(package), str(stage / 'DEBIAN')], check=True)
            for line in (stage / 'DEBIAN/md5sums').read_text().splitlines():
                digest, name = line.split(maxsplit=1)
                if hashlib.md5((stage / name).read_bytes()).hexdigest() != digest:
                    raise ValueError(f'Package file checksum mismatch: {name}')
            if 'syslogapp-cinnamon-applet_' not in package.name:
                program = stage / 'usr/share/syslogapp'
                for source in program.rglob('*.py'):
                    compile(source.read_text(), str(source), 'exec')
                subprocess.run(['desktop-file-validate', str(stage / 'usr/share/applications/syslogapp.desktop')], check=True)
                launcher = stage / 'usr/bin/syslogapp'
                if launcher.stat().st_mode & 0o111 != 0o111:
                    raise ValueError('Launcher must be executable')
                control = (stage / 'DEBIAN/control').read_text()
                for dependency in ('python3 (>= 3.9)', 'python3-gi', 'gir1.2-gtk-3.0', 'iproute2', 'openssh-client'):
                    if dependency not in control:
                        raise ValueError(f'Missing dependency: {dependency}')
                for script in ('preinst', 'postinst', 'prerm', 'postrm'):
                    if (stage / 'DEBIAN' / script).exists():
                        raise ValueError('Review newly added package lifecycle script: ' + script)
        archives = [path for path in entries if path.name.endswith('-source.tar.gz')]
        if len(archives) != 1:
            raise ValueError('Expected one source archive')
        with tarfile.open(archives[0]) as archive:
            for item in archive.getmembers():
                parts = PurePosixPath(item.name).parts
                if item.name.startswith('/') or '..' in parts or item.issym() or item.islnk():
                    raise ValueError('Unsafe source archive member: ' + item.name)
                if any(part in ('.git', '.aws', '.codex', 'backups', '__pycache__') for part in parts):
                    raise ValueError('Private or generated source archive member: ' + item.name)
    print('PASS: release hashes, package file checksums, Python syntax, desktop entry,')
    print('      launcher permissions, dependencies and source archive hygiene.')
    print('Staging checks only: no package installation or distro compatibility claim.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    check_release(parser.parse_args().directory)
