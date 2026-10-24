# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Cheap local snapshot: no sampling loop, processes, DNS or journal scans."""
import os
import platform
from datetime import datetime


def read_text(path):
    with open(path, encoding='utf-8', errors='replace') as stream:
        return stream.read(128 * 1024)


def size(value):
    return f'{value / (1024 ** 3):.1f} GiB'


def snapshot():
    rows = []

    def collect(label, func, color='#c6d4c9'):
        try:
            value = str(func())
            rows.append((label, value, color))
        except (OSError, ValueError, KeyError, IndexError) as exc:
            rows.append((label, f'Unavailable: {exc}', '#ffb34c'))

    def os_name():
        fields = dict(line.split('=', 1) for line in read_text('/etc/os-release').splitlines()
                      if '=' in line)
        return fields['PRETTY_NAME'].strip('"')

    def uptime():
        minutes = int(float(read_text('/proc/uptime').split()[0])) // 60
        return f'{minutes // 1440}d {minutes // 60 % 24}h {minutes % 60}m'

    def cpu():
        for line in read_text('/proc/cpuinfo').splitlines():
            if line.startswith(('model name', 'Hardware')) and ':' in line:
                return line.split(':', 1)[1].strip()
        return platform.machine()

    def memory():
        values = {}
        for line in read_text('/proc/meminfo').splitlines():
            key, value = line.split(':', 1)
            values[key] = int(value.split()[0]) * 1024
        total, available = values['MemTotal'], values['MemAvailable']
        return (f'{size(total - available)} used / {size(total)} total · '
                f'{size(available)} available'), values

    collect('Host', platform.node, '#6aa8ff')
    collect('System', os_name)
    collect('Kernel', lambda: f'{platform.release()} · {platform.machine()}')
    collect('Uptime', uptime)
    collect('CPU', cpu)
    collect('Logical CPUs', lambda: os.cpu_count() or 'Unavailable')
    collect('Load · 1 / 5 / 15 min', lambda: ' / '.join(f'{v:.2f}' for v in os.getloadavg()), '#6aa8ff')
    try:
        text, values = memory()
        rows.append(('Memory', text, '#b69cff'))
        rows.append(('Swap', f"{size(values['SwapTotal'] - values['SwapFree'])} used / "
                     f"{size(values['SwapTotal'])} total", '#b69cff'))
    except (OSError, ValueError, KeyError) as exc:
        for label in ('Memory', 'Swap'):
            rows.append((label, f'Unavailable: {exc}', '#ffb34c'))

    def disk():
        stat = os.statvfs('/')
        total = stat.f_blocks * stat.f_frsize
        used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
        available = stat.f_bavail * stat.f_frsize
        return f'{size(used)} used / {size(total)} total · {size(available)} available'

    collect('Root filesystem', disk, '#ffb34c')
    return {'rows': rows, 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
