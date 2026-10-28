# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Standalone, read-only /proc probe. The same source runs locally and over SSH."""
import ipaddress
import json
import os
from pathlib import Path
import sys
from datetime import datetime


def read(path, limit=32768):
    with open(path, 'rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Process data exceeded the inspection size limit')
    return data.decode('utf-8', 'replace')


def stat_identity(path):
    value = read(path)
    end = value.rfind(')')
    fields = value[end + 2:].split()
    if end < 0 or len(fields) < 20:
        raise ValueError('Unexpected process identity data')
    return fields[19], value[value.index('(') + 1:end], fields[1], fields[0]


def normalized_ip(value):
    if value == '*':
        return '*'
    ip = ipaddress.ip_address(value.split('%', 1)[0])
    return str(ip.ipv4_mapped or ip) if ip.version == 6 else str(ip)


def proc_endpoint(value):
    address, port = value.split(':')
    data = bytes.fromhex(address)
    if sys.byteorder == 'little':
        data = b''.join(data[i:i + 4][::-1] for i in range(0, len(data), 4))
    return normalized_ip(str(ipaddress.ip_address(data))), int(port, 16)


def endpoint_matches(actual, address, port):
    expected = normalized_ip(address)
    if expected == '*':
        matches = ipaddress.ip_address(actual[0]).is_unspecified
    else:
        matches = actual[0] == expected
    return matches and actual[1] == (0 if port == '*' else int(port))


def associated_unit(cgroup):
    for line in cgroup.splitlines():
        parts = line.split(':', 2)
        if len(parts) != 3:
            continue
        components = parts[2].split('/')
        # cgroup v1 named systemd hierarchy and cgroup v2 share unit paths.
        if parts[0] != '0' and 'name=systemd' not in parts[1].split(','):
            continue
        for component in reversed(components):
            if component.endswith(('.service', '.scope')):
                return component, 'user.slice' in components
    return None, False


def inspect_connection(payload, root='/proc'):
    pid, fd = payload['pid'], payload['fd']
    if type(pid) is not int or type(fd) is not int or not 0 < pid <= 2**31 or not 0 <= fd <= 2**31:
        raise ValueError('Invalid process or descriptor')
    protocol = payload['protocol'].lower()
    if protocol not in ('tcp', 'udp'):
        raise ValueError('Unsupported socket protocol')
    base = Path(root) / str(pid)
    before = stat_identity(base / 'stat')
    descriptor = base / 'fd' / str(fd)
    link = os.readlink(descriptor)
    if not link.startswith('socket:[') or not link.endswith(']'):
        raise ValueError('The descriptor no longer refers to this connection. Refresh Network.')
    inode = link[8:-1]
    verified = False
    for suffix in ('', '6'):
        try:
            table = read(base / 'net' / (protocol + suffix), 2 * 1024 * 1024)
        except FileNotFoundError:
            continue
        for line in table.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 10 or parts[9] != inode:
                continue
            if (endpoint_matches(proc_endpoint(parts[1]), payload['local'], payload['local_port']) and
                    endpoint_matches(proc_endpoint(parts[2]), payload['peer'], payload['peer_port'])):
                verified = True
                break
        if verified:
            break
    if not verified:
        raise ValueError('This process no longer owns the selected connection, or ownership cannot be verified. Refresh Network.')
    warnings = []
    def optional(label, function):
        try:
            return function()
        except (OSError, ValueError) as exc:
            warnings.append(f'{label}: {exc}')
            return 'Unavailable'
    status = optional('Status', lambda: read(base / 'status'))
    fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
    uid = fields.get('Uid', '').split()
    uid = uid[0] if uid else None
    cgroup = optional('Unit', lambda: read(base / 'cgroup'))
    unit, user_unit = associated_unit(cgroup)
    result = {'pid': pid, 'fd': fd, 'name': before[1], 'parent': before[2], 'state': before[3],
              'uid': uid, 'exe': optional('Executable', lambda: os.readlink(base / 'exe')),
              'cwd': optional('Working directory', lambda: os.readlink(base / 'cwd')),
              'command': optional('Command', lambda: read(base / 'cmdline', 16384).replace('\x00', ' ').strip()),
              'rss': fields.get('VmRSS', 'Unavailable').strip(), 'unit': unit, 'user_unit': user_unit,
              'boot': read(Path(root) / 'sys/kernel/random/boot_id', 128).strip().replace('-', ''),
              'start_ticks': before[0], 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
              'warnings': warnings}
    after = stat_identity(base / 'stat')
    if before[0] != after[0] or os.readlink(descriptor) != link:
        raise ValueError('The process or connection changed during inspection. Refresh Network and try again.')
    return result


if __name__ == '__main__':
    try:
        print(json.dumps(inspect_connection(json.loads(sys.argv[1]))))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
