# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Cheap local snapshot: no sampling loop, processes, DNS or journal scans."""
import os
import platform
import json
import re
import selectors
import shutil
import subprocess
import sys
import time
from datetime import datetime


def read_text(path):
    with open(path, encoding='utf-8', errors='replace') as stream:
        return stream.read(128 * 1024)


def size(value):
    for unit, scale in (('TiB', 1024**4), ('GiB', 1024**3), ('MiB', 1024**2), ('KiB', 1024)):
        if abs(value) >= scale:
            return f'{value / scale:.1f} {unit}'
    return f'{value} B'


def memory_snapshot(text=None):
    """One host-wide meminfo read, with independent RAM and swap availability."""
    result = dict(total=None, available=None, used=None, swap_total=None,
                  swap_used=None, ram_error=None, swap_error=None)
    try:
        text = read_text('/proc/meminfo') if text is None else text
    except OSError as error:
        result['ram_error'] = result['swap_error'] = str(error)
        return result
    wanted = {'MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'}
    values = {}
    for line in text.splitlines():
        key, separator, value = line.partition(':')
        if key not in wanted or not separator:
            continue
        parts = value.split()
        if len(parts) != 2 or parts[1] != 'kB' or not parts[0].isdecimal() or len(parts[0]) > 20:
            continue
        values[key] = int(parts[0]) * 1024
    total, available = values.get('MemTotal'), values.get('MemAvailable')
    if total is None or available is None:
        result['ram_error'] = 'Host did not report valid total and available RAM'
    elif total <= 0 or not 0 <= available <= total:
        result['ram_error'] = 'Host reported inconsistent RAM values'
    else:
        result.update(total=total, available=available, used=total - available)
    swap_total, swap_free = values.get('SwapTotal'), values.get('SwapFree')
    if swap_total is None or swap_free is None:
        result['swap_error'] = 'Host did not report valid swap values'
    elif not 0 <= swap_free <= swap_total:
        result['swap_error'] = 'Host reported inconsistent swap values'
    else:
        result.update(swap_total=swap_total, swap_used=swap_total - swap_free)
    return result


def snapshot(include_remote=False):
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

    collect('Host', platform.node, '#6aa8ff')
    collect('System', os_name)
    collect('Kernel', lambda: f'{platform.release()} · {platform.machine()}')
    collect('Uptime', uptime)
    collect('CPU', cpu)
    collect('Logical CPUs', lambda: os.cpu_count() or 'Unavailable')
    collect('Load · 1 / 5 / 15 min', lambda: ' / '.join(f'{v:.2f}' for v in os.getloadavg()), '#6aa8ff')
    memory = memory_snapshot()
    if memory['ram_error']:
        for label in ('Memory', 'Available RAM'):
            rows.append((label, 'Unavailable: ' + memory['ram_error'], '#ffb34c'))
    else:
        rows.append(('Memory', f"{size(memory['used'])} used (estimate) / {size(memory['total'])} total", '#b69cff'))
        rows.append(('Available RAM', f"{size(memory['available'])} available for applications", '#b69cff'))
    if memory['swap_error']:
        rows.append(('Swap', 'Unavailable: ' + memory['swap_error'], '#ffb34c'))
    elif memory['swap_total'] == 0:
        rows.append(('Swap', 'Disabled · no swap configured', '#96a79a'))
    else:
        rows.append(('Swap', f"{size(memory['swap_used'])} occupied / {size(memory['swap_total'])} total", '#b69cff'))

    filesystems = filesystem_snapshot(include_remote)
    root = next((item for item in filesystems['items'] if item['mount'] == '/'), None)
    rows.append(('Root filesystem', filesystem_value(root) if root else
                 'Unavailable: ' + (filesystems['error'] or 'root mount not reported'),
                 filesystem_color(root)))
    failed = failed_services()
    reboot = reboot_status()
    rows.append(('Reboot notice', reboot['message'], '#ffb34c' if reboot['state'] != 'not_reported' else '#c6d4c9'))
    return {'rows': rows, 'memory': memory, 'filesystems': filesystems, 'failed_services': failed,
            'reboot': reboot, 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}


MAX_MOUNTS = 128
MAX_SERVICES = 128
VIRTUAL_FS = {'proc', 'sysfs', 'devpts', 'cgroup', 'cgroup2', 'securityfs', 'debugfs',
              'tracefs', 'configfs', 'pstore', 'mqueue', 'hugetlbfs', 'rpc_pipefs',
              'binfmt_misc', 'fusectl', 'nsfs', 'bpf', 'selinuxfs', 'autofs'}
NETWORK_FS = {'nfs', 'nfs4', 'cifs', 'smb3', '9p', 'afs', 'ceph', 'glusterfs', 'davfs'}


def bounded_command(args, timeout=3, max_bytes=128 * 1024):
    """Return bounded partial output and an explicit error, including on timeout."""
    proc = None
    chunks = {'out': bytearray(), 'err': bytearray()}
    failure = None
    deadline = time.monotonic() + timeout
    try:
        env = dict(os.environ, LC_ALL='C', SYSTEMD_COLORS='0', SYSTEMD_URLIFY='0')
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, start_new_session=True)
        with selectors.DefaultSelector() as poll:
            poll.register(proc.stdout, selectors.EVENT_READ, 'out')
            poll.register(proc.stderr, selectors.EVENT_READ, 'err')
            while poll.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('check timed out')
                for key, _ in poll.select(remaining):
                    data = os.read(key.fileobj.fileno(), 16384)
                    if not data:
                        poll.unregister(key.fileobj)
                        continue
                    budget = max_bytes - sum(len(value) for value in chunks.values())
                    chunks[key.data].extend(data[:budget])
                    if len(data) > budget:
                        raise ValueError('output exceeded the check size limit')
            proc.wait(timeout=max(0.01, deadline - time.monotonic()))
        diagnostic = chunks['err'].decode('utf-8', 'replace').strip()[:300]
        if proc.returncode or diagnostic:
            failure = diagnostic or f'exited with code {proc.returncode}'
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired) as exc:
        failure = str(exc)[:300]
    finally:
        if proc:
            if proc.poll() is None:
                proc.kill()
            try:
                proc.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass  # A kernel-blocked filesystem call must not block the UI worker.
            proc.stdout.close()
            proc.stderr.close()
    return chunks['out'].decode('utf-8', 'replace'), failure


def _unescape(value):
    return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)


def parse_mounts(text):
    items = []
    for line in text.splitlines():
        left, separator, right = line.partition(' - ')
        fields, tail = left.split(), right.split()
        if not separator or len(fields) < 6 or len(tail) < 3:
            raise ValueError('Unexpected mount information')
        fs = tail[0]
        items.append({'mount': _unescape(fields[4]), 'source': _unescape(tail[1]), 'type': fs,
                      'device': fields[2], 'root': _unescape(fields[3]),
                      'read_only': 'ro' in fields[5].split(','),
                      'virtual': fs in VIRTUAL_FS,
                      'network': fs in NETWORK_FS or fs.startswith('fuse'), 'usage': None, 'error': None})
    if not items:
        raise ValueError('No mounted filesystems reported')
    return sorted(items, key=lambda item: (item['mount'] != '/', item['mount']))


STAT_SOURCE = r"""
import json, os, sys
for value in sys.argv[1:]:
    item = json.loads(value)
    print(json.dumps({'checking': item['id']}), flush=True)
    try:
        stat = os.statvfs(item['path'])
        total = stat.f_blocks * stat.f_frsize
        used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
        available = stat.f_bavail * stat.f_frsize
        if total <= 0 or min(used, available) < 0:
            raise ValueError('filesystem has no usable capacity statistics')
        result = {'id': item['id'], 'usage': {'total': total, 'used': used, 'available': available,
                   'percent': round(100 * used / (used + available), 1) if used + available else 100.0}}
    except (OSError, ValueError) as exc:
        result = {'id': item['id'], 'error': str(exc)[:200]}
    print(json.dumps(result), flush=True)
"""


def filesystem_snapshot(include_remote=False):
    result = {'items': [], 'total': None, 'limited': False, 'error': None}
    try:
        with open('/proc/self/mountinfo', 'rb') as stream:
            data = stream.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('mount list exceeded 2 MiB')
        all_items = parse_mounts(data.decode('utf-8', 'replace'))
        result.update(items=sorted(all_items, key=lambda item: item['virtual'])[:MAX_MOUNTS], total=len(all_items), limited=len(all_items) > MAX_MOUNTS)
    except (OSError, ValueError) as exc:
        result['error'] = str(exc)[:300]
        return result
    jobs, aliases = [], {}
    for index, item in enumerate(result['items']):
        if item['virtual']:
            item['error'] = 'Not applicable (virtual filesystem)'
            continue
        if item['network'] and not include_remote:
            item['error'] = 'Not checked (network/FUSE; enable usage check and Refresh)'
            continue
        key = item['device'], item['root'], item['type']
        if key not in aliases:
            aliases[key] = len(jobs)
            jobs.append({'id': len(jobs), 'path': item['mount'], 'network': item['network']})
        item['_job'] = aliases[key]
    if not jobs:
        return result
    output, error = bounded_command([sys.executable or 'python3', '-c', STAT_SOURCE,
                                     *(json.dumps(job) for job in sorted(jobs, key=lambda job: job['network']))], timeout=3, max_bytes=64 * 1024)
    completed, checking = {}, None
    for line in output.splitlines():
        try:
            value = json.loads(line)
            if 'checking' in value:
                checking = value['checking']
            elif 'id' in value:
                completed[value['id']] = value
        except (ValueError, TypeError):
            continue  # A stopped helper can end in a partial JSON line.
    for item in result['items']:
        job = item.pop('_job', None)
        if job is None:
            continue
        value = completed.get(job)
        if value:
            item['usage'] = value.get('usage')
            item['error'] = 'Unavailable: ' + value['error'] if value.get('error') else None
        else:
            item['error'] = ('Unavailable: ' if job == checking else 'Not checked: ') + (error or 'incomplete usage response')
    return result


def filesystem_value(item):
    if not item:
        return 'Unavailable'
    prefix = f"{item['type']} · {item['source']}" + (' · read-only' if item['read_only'] else '')
    usage = item.get('usage')
    if usage:
        return (f"{prefix} · {usage['percent']:.1f}% used · {size(usage['used'])} / {size(usage['total'])}"
                f" · {size(usage['available'])} available")
    return prefix + ' · ' + (item.get('error') or 'Unavailable')


def filesystem_color(item):
    if not item or not item.get('usage'):
        return '#9aa8b7' if item and item.get('virtual') else '#ffb34c'
    percent = item['usage']['percent']
    return '#ff8188' if percent >= 95 else '#ffb34c' if percent >= 85 else '#6aa8ff'


def failed_services():
    result = {'items': [], 'limited': False, 'error': None}
    program = shutil.which('systemctl')
    if not program:
        result['error'] = 'systemctl is not installed'
        return result
    output, error = bounded_command([program, '--system', '--failed', '--type=service', '--all',
                                      '--plain', '--no-legend', '--no-pager', '--full'], timeout=3)
    if error:
        result['error'] = error
        return result
    try:
        for line in output.splitlines():
            if not line.strip():
                continue
            fields = line.split(None, 4)
            if len(fields) < 4 or not fields[0].endswith('.service') or fields[2] != 'failed':
                raise ValueError('unexpected failed-service response')
            if len(result['items']) == MAX_SERVICES:
                result['limited'] = True
                break
            result['items'].append({'unit': fields[0], 'load': fields[1], 'active': fields[2],
                                    'sub': fields[3], 'description': fields[4][:256] if len(fields) > 4 else ''})
    except ValueError as exc:
        result['items'] = []
        result['error'] = str(exc)
    return result


def reboot_status():
    for marker in ('/run/reboot-required', '/var/run/reboot-required'):
        try:
            os.stat(marker)
            return {'state': 'required', 'message': f'Reboot requested by {marker}'}
        except FileNotFoundError:
            continue
        except OSError as exc:
            return {'state': 'unavailable', 'message': f'Unavailable: {exc}'}
    try:
        release = dict(line.split('=', 1) for line in read_text('/etc/os-release').splitlines() if '=' in line)
        families = (release.get('ID', '') + ' ' + release.get('ID_LIKE', '')).replace('"', '').split()
    except (OSError, ValueError):
        families = []
    if any(family in ('ubuntu', 'debian', 'linuxmint') for family in families):
        return {'state': 'not_reported', 'message': 'No reboot notice reported (reboot-required marker absent; not a complete reboot assessment)'}
    return {'state': 'unavailable', 'message': 'Unavailable: this distribution has no supported reboot-notice indicator'}
