# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Bounded cached sort keys: numeric endpoints and real journal timestamps."""
from datetime import datetime
from functools import lru_cache
import ipaddress
import re


def _natural_key(value):
    return tuple((1, int(part)) if part.isdecimal() else (0, part.casefold())
                 for part in re.split(r'(\d+)', value))


_cached_natural_key = lru_cache(maxsize=2048)(_natural_key)


def natural_key(value):
    value = str(value)
    # Long journal messages should leave memory when their records are evicted,
    # rather than being retained by a global sorting cache.
    return _cached_natural_key(value) if len(value) <= 256 else _natural_key(value)


@lru_cache(maxsize=2048)
def endpoint_key(value):
    host, separator, port = str(value).rpartition(':')
    if not separator:
        host, port = str(value), ''
    host = host.strip('[]')
    address, _, scope = host.partition('%')
    try:
        ip = ipaddress.ip_address(address)
        family, number = ip.version, int(ip)
    except ValueError:
        family, number = (0, 0) if address in ('*', '') else (9, 0)
        scope = address + '%' + scope
    port_key = (int(port) if port.isdecimal() else -1, natural_key(port))
    return family, number, natural_key(scope), port_key


@lru_cache(maxsize=2048)
def timestamp_key(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        try:
            return int(datetime.fromisoformat(str(value)).timestamp() * 1_000_000)
        except ValueError:
            return -1


STATE_ORDER = {name: index for index, name in enumerate((
    'ESTAB', 'LISTEN', 'SYN-SENT', 'SYN-RECV', 'CLOSE-WAIT',
    'FIN-WAIT-1', 'FIN-WAIT-2', 'LAST-ACK', 'CLOSING', 'TIME-WAIT', 'UNCONN', 'CLOSE'))}


@lru_cache(maxsize=2048)
def split_endpoint(value):
    host, separator, port = value.rpartition(':')
    return (host.strip('[]'), port) if separator else (value, '')


@lru_cache(maxsize=2048)
def address_key(value):
    return endpoint_key(f'[{value}]:0')[:3]


def _process_fields(value):
    matches = re.findall(r'\("((?:\\.|[^"\\])*)",pid=(\d+)', value)
    pids = ', '.join(str(pid) for pid in sorted({int(pid) for _, pid in matches}))
    names = ', '.join(sorted({name for name, _ in matches}, key=natural_key))
    return pids, names


_cached_process_fields = lru_cache(maxsize=2048)(_process_fields)


def process_fields(value):
    return _cached_process_fields(value) if len(value) <= 4096 else _process_fields(value)


def network_display_row(row, extended=False):
    local, local_port = split_endpoint(row['local'])
    remote, remote_port = split_endpoint(row['peer'])
    pids, names = process_fields(row['process'])
    process = row['process'] if extended else names
    return (row['protocol'], row['state'], local, local_port, remote, remote_port,
            pids or '—', process or '—', row['process'])


def network_field_key(value, column, raw_process=''):
    if column == 1:
        return STATE_ORDER.get(value, 99), natural_key(value)
    if column in (2, 4):
        return address_key(value)
    if column in (3, 5):
        return int(value) if value.isdecimal() else -1
    if column == 7 and raw_process:
        value = process_fields(raw_process)[1]
    return natural_key(value)


def network_sort_key(values, column):
    raw = values[8] if len(values) > 8 else ''
    keys = tuple(network_field_key(value, index, raw) for index, value in enumerate(values[:8]))
    return keys[column], (keys[1], keys[0], *keys[2:])


def log_sort_key(values, column):
    when, unit, level, message, priority, raw = values[:6]
    timestamp = timestamp_key(str(raw.get('__REALTIME_TIMESTAMP', when))) if isinstance(raw, dict) else timestamp_key(when)
    primary = (timestamp, natural_key(unit), int(priority), natural_key(message))[column]
    return primary, timestamp, natural_key(unit), natural_key(message)


def compare(left, right):
    return (left > right) - (left < right)
