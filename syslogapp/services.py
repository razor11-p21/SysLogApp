# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import json
import ipaddress
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None


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


def run_maintenance_command(args):
    """Wait for administrative work without killing it after a fixed deadline.

    A separate session lets an already-started operation survive the GUI being
    terminated. Use a file rather than a pipe so a closed GUI cannot break its
    output stream or require keeping the full output in memory.
    """
    try:
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            rc = process.wait()
            size = output.tell()
            limit = 1024 * 1024
            output.seek(max(0, size - limit))
            text = output.read(limit).decode('utf-8', errors='replace')
            if size > limit:
                text = '[Earlier output omitted; showing the last 1 MiB]\n' + text
            return rc, text, ''
    except FileNotFoundError:
        return 127, '', f'Command not found: {args[0]}'
    except Exception as exc:
        return 1, '', str(exc)


def _read_os_release():
    data = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k] = v.strip().strip('"')
    except Exception:
        pass
    return data


def human_bytes(num):
    try:
        num = float(num)
    except Exception:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if abs(num) < 1024.0 or unit == units[-1]:
            if unit in ("GB", "TB"):
                return f"{num:.1f} {unit}"
            return f"{num:.0f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def uptime_seconds():
    if psutil:
        try:
            return max(0, time.time() - psutil.boot_time())
        except Exception:
            pass
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except Exception:
        return 0.0


def human_uptime(seconds):
    seconds = int(max(0, seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {mins}m"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def cpu_model():
    try:
        for line in Path("/proc/cpuinfo").read_text(errors="replace").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "Unknown"


class CheckUnavailable(RuntimeError):
    """A check failed or returned incomplete data, rather than a healthy result."""


def failed_services():
    rc, out, err = run_command(["systemctl", "--failed", "--no-legend", "--plain", "--no-pager"], timeout=6)
    if rc != 0:
        raise CheckUnavailable(err.strip() or f"systemctl exited with code {rc}")
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        unit = line.split()[0]
        if unit.endswith(".service") or "." in unit:
            rows.append(unit)
    return rows


def journal_records(args, timeout=10):
    rc, out, err = run_command(["journalctl", *args, "--no-pager", "-o", "json"], timeout=timeout)
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


def journal_count(priority="err", since="24 hours ago"):
    # Errors include Emergency through Error; warnings are exclusively Warning.
    priorities = {"err": "emerg..err", "warning": "warning..warning"}
    return len(journal_records([
        "--since", since, "-p", priorities.get(priority, priority),
        "--output-fields=PRIORITY",
    ]))


def dns_available():
    # getent uses the host's configured resolver, with a bounded subprocess wait.
    rc, out, err = run_command(["getent", "ahosts", "example.com"], timeout=4)
    if rc != 0 or not out.strip():
        raise CheckUnavailable(err.strip() or "DNS lookup failed or timed out")
    return True


def network_status():
    status = {"connected": False, "dns": False, "gateway": "—", "interface": "—"}
    rc, out, err = run_command(["ip", "route", "show", "default"], timeout=3)
    status["route_error"] = (err.strip() or f"ip exited with code {rc}") if rc != 0 else None
    if rc != 0:
        status["connected"] = None
    if rc == 0 and out.strip():
        parts = out.strip().split()
        if "via" in parts:
            try:
                status["gateway"] = parts[parts.index("via") + 1]
            except Exception:
                pass
        if "dev" in parts:
            try:
                status["interface"] = parts[parts.index("dev") + 1]
            except Exception:
                pass
        status["connected"] = True
    try:
        dns_available()
        status["dns"] = True
    except Exception as exc:
        status["dns"] = False
        status["dns_error"] = str(exc)
    return status


def resource_snapshot():
    """Fast host metrics; no journal, DNS, or reachability checks."""
    osr = _read_os_release()

    if psutil:
        try:
            cpu = psutil.cpu_percent(interval=0.15)
        except Exception:
            cpu = None
        try:
            vm = psutil.virtual_memory()
            mem_used, mem_total, mem_pct = vm.used, vm.total, vm.percent
        except Exception:
            mem_used = mem_total = mem_pct = None
        try:
            sw = psutil.swap_memory()
            swap_used = sw.used
        except Exception:
            swap_used = None
        try:
            du = psutil.disk_usage("/")
            disk_pct, disk_free, disk_total = du.percent, du.free, du.total
        except Exception:
            disk_pct = disk_free = disk_total = None
    else:
        cpu = None
        mem_used = mem_total = mem_pct = swap_used = None
        try:
            du = shutil.disk_usage("/")
            disk_total, disk_free = du.total, du.free
            disk_pct = ((disk_total - disk_free) / disk_total * 100.0) if disk_total else None
        except OSError:
            disk_pct = disk_free = disk_total = None

    up = uptime_seconds()
    boot_ts = time.time() - up
    return {
        "cpu": cpu,
        "mem_used": mem_used,
        "mem_total": mem_total,
        "mem_pct": mem_pct,
        "swap_used": swap_used,
        "disk_pct": disk_pct,
        "disk_free": disk_free,
        "disk_total": disk_total,
        "hostname": socket.gethostname(),
        "os": osr.get("PRETTY_NAME") or platform.platform(),
        "kernel": platform.release(),
        "uptime": human_uptime(up),
        "last_boot": datetime.fromtimestamp(boot_ts).strftime("%Y-%m-%d %H:%M"),
        "cpu_model": cpu_model(),
        "load": os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0,
    }


def health_snapshot():
    """Slower checks, preserving individual failures so other results survive."""
    data = {"check_errors": {}}
    checks = {
        "failed_services": failed_services,
        "network": network_status,
        "error_count": lambda: journal_count("err"),
        "warning_count": lambda: journal_count("warning"),
        "issues": lambda: recent_issues(6),
    }
    for name, check in checks.items():
        try:
            data[name] = check()
        except Exception as exc:
            data[name] = None
            data["check_errors"][name] = str(exc)
    data["diagnostics"] = run_diagnostics(data)
    return data


def system_snapshot():
    return {**resource_snapshot(), **health_snapshot()}


PRIORITY_LABELS = {
    "0": "Emergency", "1": "Alert", "2": "Critical", "3": "Error",
    "4": "Warning", "5": "Notice", "6": "Info", "7": "Debug"
}


def recent_issues(limit=8):
    records = journal_records(["-b", "0", "-p", "emerg..warning", "-n", str(limit)])
    rows = []
    for obj in records:
        ts = obj.get("__REALTIME_TIMESTAMP")
        try:
            when = datetime.fromtimestamp(int(ts) / 1_000_000).strftime("%H:%M")
        except Exception:
            when = "—"
        pri = str(obj.get("PRIORITY", "6"))
        unit = obj.get("_SYSTEMD_UNIT") or obj.get("SYSLOG_IDENTIFIER") or obj.get("_COMM") or "system"
        msg = str(obj.get("MESSAGE", "")).replace("\n", " ").strip()
        rows.append({
            "time": when,
            "unit": unit,
            "message": msg,
            "priority": pri,
            "level": PRIORITY_LABELS.get(pri, "Info"),
        })
    return rows


def run_diagnostics(health=None):
    results = []

    try:
        failed = health["failed_services"] if health is not None else failed_services()
        if failed is None:
            raise CheckUnavailable(health["check_errors"].get("failed_services", "Unavailable"))
        if failed:
            results.append(("warning", "Failed services", f"{len(failed)} failed: {', '.join(failed[:3])}"))
        else:
            results.append(("ok", "Failed services", "No failed systemd units"))
    except Exception as exc:
        results.append(("info", "Failed services", f"Couldn't check: {exc}"))

    try:
        du = shutil.disk_usage("/")
        pct = (du.used / du.total * 100) if du.total else 0
        if pct >= 90:
            results.append(("error", "Disk space", f"Root filesystem is {pct:.0f}% full ({human_bytes(du.free)} free)"))
        elif pct >= 80:
            results.append(("warning", "Disk space", f"Root filesystem is {pct:.0f}% full ({human_bytes(du.free)} free)"))
        else:
            results.append(("ok", "Disk space", f"Healthy ({human_bytes(du.free)} free)"))
    except Exception as exc:
        results.append(("info", "Disk space", f"Couldn't check: {exc}"))

    rc, _, _ = run_command(["ping", "-c", "1", "-W", "2", "1.1.1.1"], timeout=4)
    results.append(("ok" if rc == 0 else "warning", "Internet connectivity", "Reachable" if rc == 0 else "No reply from 1.1.1.1"))

    try:
        if health is not None and health.get("network") is not None:
            if not health["network"]["dns"]:
                raise CheckUnavailable(health["network"].get("dns_error", "DNS lookup failed"))
        else:
            dns_available()
        results.append(("ok", "DNS resolution", "Resolving correctly"))
    except Exception as exc:
        results.append(("error", "DNS resolution", f"Resolution failed: {exc}"))

    try:
        records = journal_records(["-k", "--since", "today", "--output-fields=MESSAGE"])
        oom = sum(any(token in str(record.get("MESSAGE", "")).lower()
                      for token in ("out of memory", "oom-kill")) for record in records)
        results.append(("warning" if oom else "ok", "Recent OOM kills", f"{oom} related messages today" if oom else "None detected"))
    except Exception as exc:
        results.append(("info", "Recent OOM kills", f"Couldn't check: {exc}"))

    try:
        err_1h = journal_count("err", "1 hour ago")
        results.append(("warning" if err_1h else "ok", "Journal errors (1h)", f"{err_1h} error messages" if err_1h else "No errors"))
    except Exception as exc:
        results.append(("info", "Journal errors (1h)", f"Couldn't check: {exc}"))

    if psutil:
        try:
            vm = psutil.virtual_memory()
            state = "warning" if vm.percent >= 90 else "ok"
            results.append((state, "Memory pressure", f"{vm.percent:.0f}% in use"))
        except Exception as exc:
            results.append(("info", "Memory pressure", f"Couldn't check: {exc}"))
    else:
        results.append(("info", "Memory pressure", "Couldn't check: psutil is unavailable"))

    return results


def load_logs(limit=400, boot_only=True, priority="All", unit=None):
    args = ["-n", str(limit)]
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
    records = journal_records(args, timeout=15)
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


def _addr_text(addr):
    """Format a psutil address object/tuple for display."""
    if not addr:
        return "*"
    try:
        host = addr.ip
        port = addr.port
    except Exception:
        try:
            host, port = addr[0], addr[1]
        except Exception:
            return str(addr)
    host = str(host or "*")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}"


def _split_endpoint_text(text):
    """Return (host, port) from the display form used by SysLogApp."""
    text = str(text or "").strip()
    if not text or text in ("*", "*:*", "—"):
        return "*", 0
    if text.startswith("["):
        end = text.find("]")
        if end >= 0:
            host = text[1:end]
            rest = text[end + 1:]
            port = rest[1:] if rest.startswith(":") else "0"
            try:
                return host, int(port)
            except Exception:
                return host, 0
    # IPv4 / wildcard and the common ss output forms can safely be split from
    # the right.  Raw IPv6 without brackets also works because the final token
    # is the numeric port.
    if ":" in text:
        host, port = text.rsplit(":", 1)
        try:
            return host or "*", int(port)
        except Exception:
            return text, 0
    return text, 0


def _connection_scope(remote_ip, local_ips=None):
    """Classify a remote endpoint as Local, LAN, Internet or Unknown."""
    remote_ip = str(remote_ip or "").split("%", 1)[0].strip("[]")
    if not remote_ip or remote_ip in ("*", "0.0.0.0", "::"):
        return "Local"
    local_ips = local_ips or set()
    if remote_ip in local_ips:
        return "Local"
    try:
        addr = ipaddress.ip_address(remote_ip)
    except ValueError:
        return "Unknown"
    if addr.is_loopback or addr.is_unspecified:
        return "Local"
    # Treat any non-global address (RFC1918, link-local, CGNAT/Tailscale,
    # multicast, etc.) as local-network scope rather than public Internet.
    if not addr.is_global:
        return "LAN"
    return "Internet"


def _safe_process_info(pid, cache=None):
    """Best-effort process metadata without elevating privileges."""
    empty = {"name": "—", "user": "—", "exe": "—"}
    if not pid or not psutil:
        return empty.copy()
    if cache is not None and pid in cache:
        return cache[pid]
    info = empty.copy()
    try:
        proc = psutil.Process(pid)
        try:
            info["name"] = proc.name() or "—"
        except Exception:
            pass
        try:
            info["user"] = proc.username() or "—"
        except Exception:
            pass
        try:
            info["exe"] = proc.exe() or "—"
        except Exception:
            pass
    except Exception:
        pass
    if cache is not None:
        cache[pid] = info
    return info


def _connection_key(protocol, local, remote, state, pid):
    return f"{protocol}|{local}|{remote}|{state}|{pid or 0}"


def network_connections_snapshot(local_ips=None, ip_to_interface=None):
    """Return observable INET connections without requiring elevated access.

    Process/PID information is best-effort: Linux may hide ownership for
    sockets that belong to other users.  We deliberately do not elevate the
    whole application just to fill those fields.
    """
    rows = []
    if not psutil:
        return rows

    try:
        conns = psutil.net_connections(kind="inet")
    except Exception:
        return rows

    proc_cache = {}
    local_ips = set(local_ips or ())
    ip_to_interface = dict(ip_to_interface or {})
    for conn in conns:
        try:
            protocol = "TCP" if conn.type == socket.SOCK_STREAM else "UDP" if conn.type == socket.SOCK_DGRAM else "INET"
            local = _addr_text(conn.laddr)
            remote = _addr_text(conn.raddr) if conn.raddr else "*"
            state = str(conn.status or "NONE").upper()
            pid = int(conn.pid) if conn.pid else 0
            proc_info = _safe_process_info(pid, proc_cache)
            family = "IPv6" if conn.family == socket.AF_INET6 else "IPv4"
            is_listening = state == "LISTEN" or (protocol == "UDP" and not conn.raddr)
            local_ip, local_port = _split_endpoint_text(local)
            remote_ip, remote_port = _split_endpoint_text(remote)
            interface = ip_to_interface.get(str(local_ip).split("%", 1)[0], "—")
            if local_ip in ("*", "0.0.0.0", "::"):
                interface = "All"
            scope = _connection_scope(remote_ip, local_ips)
            rows.append({
                "key": _connection_key(protocol, local, remote, state, pid),
                "protocol": protocol,
                "family": family,
                "local": local,
                "remote": remote,
                "local_ip": local_ip,
                "local_port": local_port,
                "remote_ip": remote_ip,
                "remote_port": remote_port,
                "state": state,
                "scope": scope,
                "interface": interface,
                "pid": pid,
                "process": proc_info.get("name", "—"),
                "user": proc_info.get("user", "—"),
                "exe": proc_info.get("exe", "—"),
                "listening": bool(is_listening),
            })
        except Exception:
            continue

    # Some Linux configurations restrict /proc socket ownership enough that
    # psutil can return no system-wide rows. Fall back to ss so the page still
    # provides useful endpoint/state visibility (without process ownership).
    if not rows:
        rc, out, _ = run_command(["ss", "-H", "-tuna"], timeout=5)
        if rc == 0:
            for line in out.splitlines():
                parts = line.split()
                if len(parts) < 6:
                    continue
                protocol = parts[0].upper()
                if protocol not in ("TCP", "UDP"):
                    continue
                state = parts[1].upper()
                local = parts[4]
                remote = parts[5]
                family = "IPv6" if "[" in local or local.count(":") > 1 else "IPv4"
                is_listening = state == "LISTEN" or (protocol == "UDP" and state in ("UNCONN", "NONE"))
                local_ip, local_port = _split_endpoint_text(local)
                remote_ip, remote_port = _split_endpoint_text(remote)
                interface = ip_to_interface.get(str(local_ip).split("%", 1)[0], "—")
                if local_ip in ("*", "0.0.0.0", "::"):
                    interface = "All"
                rows.append({
                    "key": _connection_key(protocol, local, remote, state, 0),
                    "protocol": protocol,
                    "family": family,
                    "local": local,
                    "remote": remote,
                    "local_ip": local_ip,
                    "local_port": local_port,
                    "remote_ip": remote_ip,
                    "remote_port": remote_port,
                    "state": state,
                    "scope": _connection_scope(remote_ip, local_ips),
                    "interface": interface,
                    "pid": 0,
                    "process": "—",
                    "user": "—",
                    "exe": "—",
                    "listening": bool(is_listening),
                })

    # Put active connections first, then listeners/idle sockets, with stable
    # sorting so the table does not visually jump every refresh.
    state_order = {
        "ESTABLISHED": 0,
        "SYN_SENT": 1,
        "SYN_RECV": 2,
        "CLOSE_WAIT": 3,
        "FIN_WAIT1": 4,
        "FIN_WAIT2": 5,
        "TIME_WAIT": 6,
        "LISTEN": 7,
        "NONE": 8,
    }
    rows.sort(key=lambda r: (
        state_order.get(r["state"], 9),
        r["process"].lower(), r["local"], r["remote"]
    ))
    return rows


def network_interfaces_snapshot():
    """Return interface addresses, link information and cumulative traffic."""
    rows = []
    if not psutil:
        return rows
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        io = psutil.net_io_counters(pernic=True)
    except Exception:
        return rows

    for name in sorted(addrs):
        ipv4, ipv6, mac = [], [], "—"
        for addr in addrs.get(name, []):
            try:
                if addr.family == socket.AF_INET:
                    ipv4.append(addr.address)
                elif addr.family == socket.AF_INET6:
                    ipv6.append(str(addr.address).split("%", 1)[0])
                elif getattr(psutil, "AF_LINK", object()) == addr.family:
                    mac = addr.address or "—"
            except Exception:
                continue
        st = stats.get(name)
        counters = io.get(name)
        rows.append({
            "name": name,
            "up": bool(st.isup) if st else False,
            "speed_mbps": int(st.speed) if st and st.speed and st.speed > 0 else 0,
            "mtu": int(st.mtu) if st else 0,
            "ipv4": ipv4,
            "ipv6": ipv6,
            "mac": mac,
            "bytes_sent": int(counters.bytes_sent) if counters else 0,
            "bytes_recv": int(counters.bytes_recv) if counters else 0,
            "packets_sent": int(counters.packets_sent) if counters else 0,
            "packets_recv": int(counters.packets_recv) if counters else 0,
            "errin": int(counters.errin) if counters else 0,
            "errout": int(counters.errout) if counters else 0,
            "dropin": int(counters.dropin) if counters else 0,
            "dropout": int(counters.dropout) if counters else 0,
        })
    return rows


def _dns_servers():
    servers = []
    # resolv.conf is a dependable fallback even when systemd-resolved owns it.
    try:
        for line in Path("/etc/resolv.conf").read_text(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("nameserver "):
                value = line.split(None, 1)[1].strip()
                if value and value not in servers:
                    servers.append(value)
    except Exception:
        pass
    return servers


def network_overview():
    """Collect a complete snapshot used by the Network page."""
    net = network_status()
    interfaces = network_interfaces_snapshot()
    local_ips = set()
    ip_to_interface = {}
    for item in interfaces:
        for addr in item.get("ipv4", []) + item.get("ipv6", []):
            clean = str(addr).split("%", 1)[0]
            local_ips.add(clean)
            ip_to_interface[clean] = item.get("name", "—")
    connections = network_connections_snapshot(local_ips=local_ips, ip_to_interface=ip_to_interface)

    total_sent = total_recv = 0
    if psutil:
        try:
            total = psutil.net_io_counters()
            total_sent = int(total.bytes_sent)
            total_recv = int(total.bytes_recv)
        except Exception:
            pass

    established = sum(1 for row in connections if row["state"] == "ESTABLISHED")
    listening = sum(1 for row in connections if row["listening"])
    tcp_count = sum(1 for row in connections if row["protocol"] == "TCP")
    udp_count = sum(1 for row in connections if row["protocol"] == "UDP")

    primary = net.get("interface") or "—"
    primary_info = next((item for item in interfaces if item["name"] == primary), None)
    primary_ipv4 = "—"
    if primary_info and primary_info.get("ipv4"):
        primary_ipv4 = primary_info["ipv4"][0]

    return {
        "connected": net.get("connected"),
        "route_error": net.get("route_error"),
        "dns_ok": bool(net.get("dns")),
        "gateway": net.get("gateway", "—"),
        "primary_interface": primary,
        "primary_ipv4": primary_ipv4,
        "dns_servers": _dns_servers(),
        "bytes_sent": total_sent,
        "bytes_recv": total_recv,
        "established": established,
        "listening": listening,
        "tcp_count": tcp_count,
        "udp_count": udp_count,
        "connections": connections,
        "interfaces": interfaces,
        "timestamp": time.time(),
    }
