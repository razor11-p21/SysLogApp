# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Validated logrotate profile writer. Invoked through pkexec only on Save."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

PROFILE = 'syslogapp'


def render(path, frequency, keep, compress, mode, size_mib=0):
    # No globbing, quoting or free-form directives are accepted from the editor.
    if not re.fullmatch(r'/var/log/[A-Za-z0-9_./@+-]+', path) or '..' in Path(path).parts:
        raise ValueError('Choose one absolute file under /var/log, without spaces or wildcards.')
    if frequency not in ('daily', 'weekly', 'monthly'):
        raise ValueError('Invalid rotation schedule')
    if not 1 <= int(keep) <= 52 or not 0 <= int(size_mib) <= 102400:
        raise ValueError('Keep must be 1–52; maximum size must be 0–102400 MiB.')
    if mode not in ('rename', 'copytruncate'):
        raise ValueError('Invalid rotation method')
    lines = ['# Managed by SysLogApp. Changes apply on the next logrotate run.',
             f'{path} {{', f'    {frequency}', f'    rotate {int(keep)}',
             '    missingok', '    notifempty', '    compress' if compress else '    nocompress']
    if compress:
        lines.append('    delaycompress')
    if int(size_mib):
        lines.append(f'    maxsize {int(size_mib)}M')
    lines.extend(['    copytruncate'] if mode == 'copytruncate' else ['    nocopytruncate', '    create'])
    return '\n'.join(lines + ['}', ''])


def _atomic_write(path, content):
    descriptor, temporary = tempfile.mkstemp(prefix='.syslogapp-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_config(content, log_path, root=Path('/'), validate_only=False):
    """Validate a staged full configuration before atomically changing one file."""
    root = Path(root)
    target_log = root / log_path.lstrip('/')
    if target_log.resolve() != target_log or not stat.S_ISREG(target_log.stat().st_mode):
        raise ValueError('The selected log must be an existing regular file, without symlinks.')
    directory = root / 'etc/logrotate.d'
    main = root / 'etc/logrotate.conf'
    target = directory / PROFILE
    if directory.is_symlink() or target.is_symlink():
        raise ValueError('Refusing to replace a symlinked configuration.')
    if target.exists() and not target.read_text().startswith('# Managed by SysLogApp.'):
        raise ValueError('The existing syslogapp profile is not app-managed; edit it manually.')
    main_text = main.read_text()
    include = re.compile(r'(?m)^(\s*include\s+)/etc/logrotate\.d/?\s*(?:#.*)?$')
    if len(include.findall(main_text)) != 1:
        raise ValueError('Expected one include /etc/logrotate.d in /etc/logrotate.conf. '
                         'This custom layout needs manual configuration.')
    executable = shutil.which('logrotate')
    if not executable:
        raise ValueError('logrotate is not installed')
    with tempfile.TemporaryDirectory(prefix='syslogapp-logrotate-') as temporary:
        staging = Path(temporary)
        configs = staging / 'rules'
        shutil.copytree(directory, configs, symlinks=True)
        candidate = configs / PROFILE
        candidate.unlink(missing_ok=True)
        candidate.write_text(content)
        candidate.chmod(0o644)
        validation = staging / 'logrotate.conf'
        validation.write_text(include.sub(lambda m: m[1] + str(configs), main_text))
        # --debug never rotates files, updates state or executes rotation scripts.
        with tempfile.TemporaryFile() as output:
            proc = subprocess.run([executable, '--debug', '--state', '/dev/null', str(validation)],
                                  stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                  timeout=15, check=False)
            if proc.returncode:
                length = output.tell()
                output.seek(max(0, length - 32000))
                raise ValueError('Configuration validation failed; nothing changed.\n' +
                                 output.read(32000).decode('utf-8', 'replace'))
    if validate_only:
        return 'Validation passed. No configuration, state or logs were changed.\n' + content
    # Preserve the old app-managed profile, leaving distro-owned rules untouched.
    if target.exists():
        backup_dir = root / 'var/backups/syslogapp'
        if backup_dir.is_symlink():
            raise ValueError('Refusing a symlinked backup directory')
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup = backup_dir / ('logrotate-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.conf')
        _atomic_write(backup, target.read_text())
    _atomic_write(target, content)
    return ('Saved /etc/logrotate.d/syslogapp. Validation passed. No logs were rotated.\n'
            'The system logrotate timer/cron schedule controls when rotation runs.\n' + content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--path', required=True)
    parser.add_argument('--frequency', choices=('daily', 'weekly', 'monthly'), required=True)
    parser.add_argument('--keep', type=int, required=True)
    parser.add_argument('--compress', choices=('yes', 'no'), required=True)
    parser.add_argument('--mode', choices=('rename', 'copytruncate'), required=True)
    parser.add_argument('--size-mib', type=int, default=0)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    try:
        content = render(args.path, args.frequency, args.keep, args.compress == 'yes', args.mode, args.size_mib)
        if os.geteuid() != 0:
            raise PermissionError('Administrator authentication is required.')
        print(apply_config(content, args.path, validate_only=args.validate_only))
    except Exception as exc:
        print(str(exc))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
