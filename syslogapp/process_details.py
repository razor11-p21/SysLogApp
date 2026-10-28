# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""On-demand connection-owner inspection; no /proc scans during polling."""
import json
import re
from pathlib import Path
from .process_probe import inspect_connection
from .services import CheckUnavailable, load_logs


def owners(values):
    # A socket can be shared by several PIDs/descriptors. Never guess the first
    # number from a display cell or treat a process name as executable code.
    return list(dict.fromkeys((int(pid), int(fd)) for pid, fd in
                re.findall(r'pid=(\d+),fd=(\d+)', values[8])))[:32]


def collect(values, owner, host=None):
    if owner not in owners(values):
        raise CheckUnavailable('No verified PID/descriptor in this connection snapshot.')
    payload = {'pid': owner[0], 'fd': owner[1], 'protocol': values[0],
               'local': values[2], 'local_port': values[3], 'peer': values[4], 'peer_port': values[5]}
    try:
        if host is None:
            return inspect_connection(payload)
        if not host.supports_python():
            raise CheckUnavailable('Remote process inspection requires Python 3.8 or later and readable /proc data.')
        source = Path(__file__).with_name('process_probe.py').read_text(encoding='utf-8')
        output, limited = host.capture([host.which('python3'), '-c', source, json.dumps(payload)],
                                       timeout=8, max_bytes=128 * 1024)
        if limited:
            raise CheckUnavailable('Process inspection exceeded its output limit.')
        result = json.loads(output)
        if not isinstance(result, dict) or result.get('pid') != owner[0] or result.get('fd') != owner[1]:
            raise ValueError('Unexpected process inspection result')
        return result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CheckUnavailable(f'Process details unavailable: {exc}') from exc


def related_logs(details, host=None):
    unit = details.get('unit')
    boot = details.get('boot')
    if not unit or not boot:
        raise CheckUnavailable('No associated systemd unit was found for this process.')
    fields = {'_BOOT_ID': boot}
    if details.get('user_unit'):
        if not details.get('uid'):
            raise CheckUnavailable('The user unit cannot be scoped without its UID.')
        fields.update(_SYSTEMD_USER_UNIT=unit, _UID=details['uid'])
    else:
        fields['_SYSTEMD_UNIT'] = unit
    return load_logs(400, boot_only=False, host=host, journal_match=fields)
