# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Journal-only backend: no resource sampling, network probes or privilege tools."""
import json
import subprocess
from datetime import datetime


def run_command(args, timeout=8):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except FileNotFoundError:
        return 127, "", f"Command not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "Command timed out"
    except Exception as exc:
        return 1, "", str(exc)


class CheckUnavailable(RuntimeError):
    """A check failed or returned incomplete data, rather than a healthy result."""


def journal_records(args, timeout=10, host=None):
    command = ['journalctl', *args, '--no-pager', '-o', 'json']
    if host:
        try:
            out, limited = host.capture(command, timeout=timeout, max_bytes=16 * 1024 * 1024)
            if limited:
                raise CheckUnavailable('Remote journal snapshot exceeded 16 MiB; lower the history limit.')
            rc, err = 0, ''
        except Exception as exc:
            raise CheckUnavailable(str(exc)) from exc
    else:
        rc, out, err = run_command(command, timeout=timeout)
    if rc != 0 or any(hint in err.lower() for hint in (
        "permission", "access denied", "not seeing messages", "no journal files were opened",
    )):
        raise CheckUnavailable(err.strip() or f"journalctl exited with code {rc}")
    try:
        records = [json.loads(line) for line in out.splitlines() if line.strip()]
        if any(not isinstance(record, dict) for record in records):
            raise ValueError("Expected journal objects")
        return records
    except (ValueError, TypeError) as exc:
        raise CheckUnavailable("Unable to parse journal entries") from exc


PRIORITY_LABELS = {
    "0": "Emergency", "1": "Alert", "2": "Critical", "3": "Error",
    "4": "Warning", "5": "Notice", "6": "Info", "7": "Debug"
}


def load_logs(limit=400, boot_only=True, priority="All", unit=None, host=None):
    args = ["-n", str(max(100, min(2000, int(limit)))),
            "--output-fields=__REALTIME_TIMESTAMP,PRIORITY,_SYSTEMD_UNIT,SYSLOG_IDENTIFIER,_COMM,_PID,MESSAGE"]
    if boot_only:
        args += ["-b", "0"]
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
    records = journal_records(args, timeout=15, host=host)
    rows = []
    for obj in records:
        ts = obj.get("__REALTIME_TIMESTAMP")
        try:
            dt = datetime.fromtimestamp(int(ts) / 1_000_000)
            when = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            when = "—"
        pri = str(obj.get("PRIORITY", "6"))
        unit_name = obj.get("_SYSTEMD_UNIT") or obj.get("SYSLOG_IDENTIFIER") or obj.get("_COMM") or "system"
        msg = str(obj.get("MESSAGE", "")).replace("\x00", " ").replace("\n", " ").strip()
        rows.append({
            "time": when,
            "unit": unit_name,
            "level": PRIORITY_LABELS.get(pri, "Info"),
            "priority": int(pri) if pri.isdigit() else 6,
            "message": msg,
            "raw": obj,
        })
    return rows


