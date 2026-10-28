# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Literal connection filters over loaded snapshots; never runs host commands."""
import re
from .sorting import split_endpoint

_OWNER = re.compile(r'\("((?:\\.|[^"\\])*)",pid=([0-9]+)(?:,|\))')


class ConnectionFilter:
    def __init__(self, application='', pid='', port='', side='either'):
        self.application = application.strip().casefold()
        self.pid_text, self.port_text = pid.strip(), port.strip()
        self.side = side if side in ('either', 'local', 'remote') else 'either'
        self.error = ''
        self.pid = self._number(self.pid_text, 1, 2147483647, 'PID')
        self.port = self._number(self.port_text, 0, 65535, 'Port')
        self.needs_owners = bool(self.application or self.pid_text)
        self.count = sum(bool(value) for value in (self.application, self.pid_text, self.port_text))

    def _number(self, value, minimum, maximum, label):
        if not value:
            return None
        if not re.fullmatch('[0-9]{1,10}', value) or not minimum <= int(value) <= maximum:
            if not self.error:
                self.error = f'{label} must be a whole number from {minimum} to {maximum}.'
            return None
        return int(value)

    def matches(self, row):
        if self.error:
            return False
        if self.port is not None:
            endpoints = ('local', 'peer') if self.side == 'either' else (('local',) if self.side == 'local' else ('peer',))
            if not any(self._port_matches(split_endpoint(row[key])[1]) for key in endpoints):
                return False
        if not self.needs_owners:
            return True
        raw = row.get('process', '')
        cached = row.get('_filter_owners')
        if cached is not None and cached[0] == raw:
            owners = cached[1]
        else:
            owners = tuple((name.casefold(), pid) for name, pid in _OWNER.findall(raw))
            if len(raw) <= 4096:
                row['_filter_owners'] = (raw, owners)
        # Both constraints must refer to the same owner on a shared socket.
        return any((not self.application or self.application in name)
                   and (self.pid is None or pid.lstrip('0') == str(self.pid)) for name, pid in owners)

    def _port_matches(self, value):
        return bool(re.fullmatch('[0-9]{1,5}', value)) and int(value) == self.port
