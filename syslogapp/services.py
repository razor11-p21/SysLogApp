# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Journal-only backend: no resource sampling, network probes or privilege tools."""
import json
import subprocess
import re
from .network import capture
from datetime import datetime


# Budgets refer to serialized UTF-8 data, not total process RSS. Parsed objects
# and GTK text add overhead, but all retained collections are bounded.
MAX_CAPTURE_BYTES = 16 * 1024 * 1024
MAX_RECORD_BYTES = 64 * 1024
MAX_HISTORY_BYTES = 4 * 1024 * 1024
JOURNAL_OUTPUT_FIELDS = ('__REALTIME_TIMESTAMP,PRIORITY,_SYSTEMD_UNIT,SYSLOG_IDENTIFIER,'
                         '_COMM,_PID,_BOOT_ID,_UID,_SYSTEMD_INVOCATION_ID,MESSAGE')


class JournalRows(list):
    omitted = 0


def row_bytes(row):
    if '_bytes' not in row:
        row['_bytes'] = len(json.dumps(row.get('raw', row), ensure_ascii=False).encode('utf-8'))
    return row['_bytes']


def bound_rows(rows, limit=2000, newest=True):
    result = JournalRows()
    result.omitted = getattr(rows, 'omitted', 0)
    size = 0
    candidates = reversed(rows) if newest else iter(rows)
    for row in candidates:
        cost = row_bytes(row)
        if cost > MAX_RECORD_BYTES or len(result) >= limit or size + cost > MAX_HISTORY_BYTES:
            result.omitted += 1
            continue
        result.append(row)
        size += cost
    if newest:
        result.reverse()
    return result


def bounded_lines(stream):
    """Read binary journal lines without allowing readline to grow unbounded.

    None means one oversized record was discarded, including its continuation.
    """
    discarding = False
    while True:
        chunk = stream.readline(MAX_RECORD_BYTES + 1)
        if not chunk:
            return
        if discarding:
            discarding = not chunk.endswith(b'\n')
            continue
        if len(chunk) > MAX_RECORD_BYTES:
            yield None
            discarding = not chunk.endswith(b'\n')
            continue
        yield chunk.decode('utf-8', 'replace')


def run_command(args, timeout=8):
    try:
        out, limited, err = capture(args, timeout=timeout, max_bytes=MAX_CAPTURE_BYTES,
                                    return_stderr=True)
        if limited:
            return 1, '', 'Journal snapshot exceeded 16 MiB; narrow the time range or filters.'
        return 0, out, err
    except FileNotFoundError:
        return 127, '', f'Command not found: {args[0]}'
    except (TimeoutError, subprocess.TimeoutExpired):
        return 124, '', 'Command timed out'
    except Exception as exc:
        return 1, '', str(exc)


class CheckUnavailable(RuntimeError):
    """A check failed or returned incomplete data, rather than a healthy result."""


def journal_records(args, timeout=10, host=None):
    command = ['journalctl', *args, '--no-pager', '-o', 'json']
    if host:
        try:
            out, limited, err = host.capture(command, timeout=timeout, max_bytes=MAX_CAPTURE_BYTES,
                                             return_stderr=True)
            if limited:
                raise CheckUnavailable('Journal snapshot exceeded 16 MiB; narrow the time range or filters.')
            rc = 0
        except Exception as exc:
            raise CheckUnavailable(str(exc)) from exc
    else:
        rc, out, err = run_command(command, timeout=timeout)
    if rc != 0 or any(hint in err.lower() for hint in (
        "permission", "access denied", "not seeing messages", "no journal files were opened",
    )):
        raise CheckUnavailable(err.strip() or f"journalctl exited with code {rc}")
    try:
        records = JournalRows()
        for line in out.splitlines():
            if not line.strip():
                continue
            if len(line.encode('utf-8')) > MAX_RECORD_BYTES:
                records.omitted += 1
                continue
            record = json.loads(line)
            records.append(record)
        if any(not isinstance(record, dict) for record in records):
            raise ValueError("Expected journal objects")
        return records
    except (ValueError, TypeError) as exc:
        raise CheckUnavailable("Unable to parse journal entries") from exc


PRIORITY_LABELS = {
    "0": "Emergency", "1": "Alert", "2": "Critical", "3": "Error",
    "4": "Warning", "5": "Notice", "6": "Info", "7": "Debug"
}


def load_logs(limit=400, boot_only=True, priority="All", unit=None, host=None,
              since=None, until=None, match=None, before=None, boot=None, journal_match=None):
    args = ["-n", str(max(100, min(2000, int(limit)))),
            '--output-fields=' + JOURNAL_OUTPUT_FIELDS]
    if boot is not None or boot_only:
        args += ["-b", str(boot if boot is not None else 0)]
    for option, value in (('--since', since), ('--until', until)):
        if value is not None:
            args += [option, str(value)]
    if match:
        # Search literal message text, without treating user input as a regex.
        args += ['--grep', re.escape(match), '--case-sensitive=no']
    if before:
        args += ['--cursor', before, '--reverse']
        args[1] = str(max(100, min(2000, int(limit))) + 1)
    # A single journalctl priority is cumulative (e.g. ``err`` also includes
    # Critical/Alert/Emergency).  Use explicit ranges so UI categories behave
    # as users expect.  Critical intentionally groups Emergency + Alert + Critical.
    prio_map = {
        "Critical": "emerg..crit",
        "Error": "err..err",
        "Warning": "warning..warning",
        "Notice": "notice..notice",
        "Info": "info..info",
        "Debug": "debug..debug",
    }
    if priority in prio_map:
        args += ["-p", prio_map[priority]]
    if unit:
        args += ["-u", unit]
    if journal_match:
        allowed = {'_BOOT_ID', '_SYSTEMD_UNIT', '_SYSTEMD_USER_UNIT', '_UID'}
        for field, value in journal_match.items():
            if field not in allowed or not isinstance(value, str) or not value or len(value) > 512 or '\x00' in value:
                raise CheckUnavailable('Invalid related journal field')
            args.append(f'{field}={value}')
    records = journal_records(args, timeout=15, host=host)
    rows = JournalRows()
    rows.omitted = records.omitted
    if before:
        records.reverse()
    rows.extend(journal_row(obj) for obj in records
                if not before or obj.get('__CURSOR') != before)
    return bound_rows(rows, max(100, min(2000, int(limit))), newest=not bool(before))




def journal_row(obj):
    """Normalize journal field types once for both history and live records."""
    try:
        dt = datetime.fromtimestamp(int(obj.get('__REALTIME_TIMESTAMP')) / 1_000_000)
        when = dt.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError, OverflowError, OSError):
        when = '—'
    priority = str(obj.get('PRIORITY', '6'))
    # Journal fields can contain arrays, binary values or malformed priorities.
    # GTK's priority column must receive a small integer, never arbitrary input.
    priority = int(priority) if priority in PRIORITY_LABELS else 6
    unit = obj.get('_SYSTEMD_UNIT') or obj.get('SYSLOG_IDENTIFIER') or obj.get('_COMM') or 'system'
    message = str(obj.get('MESSAGE', '')).replace('\x00', ' ').replace('\n', ' ').strip()
    return {'time': when, 'unit': str(unit), 'level': PRIORITY_LABELS[str(priority)],
            'priority': priority, 'message': message, 'raw': obj}
