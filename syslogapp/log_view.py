# SPDX-License-Identifier: GPL-3.0-or-later
"""Loaded-data filters and consecutive repeat grouping; no host access."""


def display_settings(values):
    values = values if isinstance(values, dict) else {}
    units = values.get('exclude_units', [])
    if not isinstance(units, list):
        units = []
    retained = []
    for unit in units:
        value = str(unit).strip()[:256]
        if value and value not in retained:
            retained.append(value)
        if len(retained) == 32:
            break
    return dict(exclude_units=retained,
                exclude_message=str(values.get('exclude_message') or '')[:512],
                group_repeats=values.get('group_repeats') is True)


class LogFilter:
    def __init__(self, search='', exclude_units=(), exclude_message='', **_):
        self.search = search.strip().lower()
        self.units = frozenset(exclude_units)
        self.message = exclude_message.casefold()

    def matches(self, row):
        if row['unit'] in self.units:
            return False
        if self.message and self.message in row['message'].casefold():
            return False
        return not self.search or self.search in f"{row['time']} {row['unit']} {row['level']} {row['message']}".lower()


def repeat_key(row):
    raw = row['raw']
    # Distinct boots, processes, users and service invocations stay separate.
    return (row['unit'], row['priority'], row['message'],
            *(str(raw.get(field, '')) for field in ('_BOOT_ID', '_PID', '_UID', '_SYSTEMD_INVOCATION_ID')))


def groups(rows, filters):
    result = []
    previous = None
    for row in rows:
        if not filters.matches(row):
            # A hidden intervening event still breaks a consecutive run.
            previous = None
            continue
        key = repeat_key(row)
        if result and previous == key:
            result[-1].append(row)
        else:
            result.append([row])
        previous = key
    return [tuple(group) for group in result]
