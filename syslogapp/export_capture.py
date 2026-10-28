# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Freeze currently displayed rows on the GTK thread, without new host reads."""
from collections import defaultdict, deque
from datetime import datetime
import os
import socket
from .exports import metadata
from .sorting import network_display_row


def event_time_iso(raw):
    try:
        seconds, micros = divmod(int(raw['__REALTIME_TIMESTAMP']), 1_000_000)
        return datetime.fromtimestamp(seconds).replace(microsecond=micros).astimezone().isoformat(timespec='microseconds')
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return None


def snapshot(page):
    kind = 'network' if getattr(page, 'SAVED_PAGE', 'logs') == 'network' else 'logs'
    records = []
    selected = page.text_access.selected_row_indices()
    if kind == 'logs':
        from gi.repository import Gtk
        if page._view_dirty:
            page._apply_filter(force=True)
        column, order = page.store.get_sort_column_id()
        selected_rows = set(selected)
        selected = []
        for index, row in enumerate(page.store):
            events = row[page.COL_EVENTS] or (dict(time=row[0], unit=row[1], level=row[2],
                                                  message=row[3], priority=row[4], raw=row[5]),)
            if column == page.COL_TIME and order == Gtk.SortType.DESCENDING:
                events = reversed(events)
            for event in events:
                raw = event['raw']
                if index in selected_rows:
                    selected.append(len(records))
                records.append({'type': 'event', 'time': event['time'], 'time_iso': event_time_iso(raw),
                                'unit': event['unit'], 'level': event['level'], 'priority': event['priority'],
                                'message': str(raw.get('MESSAGE', event['message'])), 'raw': raw})
        filters = {'scope': page.scope.get_active_id(), 'priority': page.priority.get_active_text(),
                   'unit': page.unit.get_text(), 'loaded_text': page.search.get_text(),
                   'journal_history': dict(page._history_query), 'page_before_cursor': page._before,
                   **page._display_settings()}
        loaded = len(page._all_rows)
        state = {'stale': bool(getattr(page, '_remote_stale', False) or page._log_error),
                 'error': page._log_error, 'last_successful_read': page._last_successful_read,
                 'omitted_by_byte_limits': page._memory_omitted, 'live': page.live.get_active(),
                 'timestamp_basis': 'Event times displayed in the exporting computer’s local timezone'}
    else:
        raw_rows = defaultdict(deque)
        for row in page._rows:
            raw_rows[page._row_identity(network_display_row(row))].append(row)
        for row in page.store:
            matches = raw_rows[page._row_identity(row)]
            records.append({'type': 'socket', 'protocol': row[0], 'state': row[1],
                            'local_address': row[2], 'local_port': row[3], 'remote_address': row[4],
                            'remote_port': row[5], 'pid': row[6], 'process': row[7],
                            'raw': matches.popleft() if matches else {'process': row[8]}})
        filters = {'kind': page.kind.get_active_text(), 'loaded_text': page.search.get_text(),
                   'hide_time_wait': page.hide_time_wait.get_active(), 'process_details': page.process_details.get_active_id(),
                   'application': page.application_filter.get_text(), 'pid': page.pid_filter.get_text(),
                   'port': page.port_filter.get_text(), 'port_side': page.port_side.get_active_id()}
        loaded = len(page._rows)
        state = {'live': page.live.get_active(), 'stale': bool(page._last_error or page._socket_error),
                 'error': page._last_error or page._socket_error,
                 'last_successful_socket_update': page._socket_success_time,
                 'interfaces_routes_update': (page._snapshot or {}).get('details_time'),
                 'snapshot_limited': page._socket_limited}
    host = page.host
    profile = getattr(host, 'profile', {}) if host else {}
    hosts = [socket.gethostname(), profile.get('hostname'), getattr(host, 'hostname', None)]
    users = [os.environ.get('USER'), profile.get('username')]
    return {'kind': kind, 'records': records, 'selected': selected,
            'metadata': metadata(kind, host, filters, False, len(records), loaded, state),
            'hosts': hosts, 'users': users}
