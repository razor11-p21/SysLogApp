# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Bounded, read-only network snapshots, collected only on demand."""
import json
import os
import selectors
import subprocess
import time
from datetime import datetime

MAX_BYTES = 512 * 1024
MAX_SOCKETS = 1000
MAX_INTERFACES = 128


def capture(args, timeout=3, max_bytes=MAX_BYTES, env=None, popen_factory=None):
    """Drain both pipes within a byte/time budget; never buffer unlimited output."""
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, start_new_session=True)
    if env is not None:
        kwargs['env'] = env
    proc = (popen_factory or subprocess.Popen)(args, **kwargs)
    chunks = {'out': bytearray(), 'err': bytearray()}
    truncated = False
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ, 'out')
            selector.register(proc.stderr, selectors.EVENT_READ, 'err')
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f'{args[0]} timed out')
                for key, _ in selector.select(remaining):
                    data = os.read(key.fileobj.fileno(), 16384)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    budget = max_bytes - sum(map(len, chunks.values()))
                    chunks[key.data].extend(data[:budget])
                    if len(data) > budget:
                        truncated = True
                        break
                if truncated:
                    break
            if not truncated:
                proc.wait(timeout=max(0.01, deadline - time.monotonic()))
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()
    out = chunks['out'].decode('utf-8', 'replace')
    error = chunks['err'].decode('utf-8', 'replace').strip()
    if not truncated and proc.returncode:
        raise RuntimeError(error or f'{args[0]} exited with status {proc.returncode}')
    if truncated and chunks['err'] and not chunks['out']:
        raise RuntimeError(error[:300] or 'Network diagnostic output exceeded size limit')
    # A byte cap may cut a socket row in half. Never display that partial row.
    if truncated:
        out = out.rsplit('\n', 1)[0] if '\n' in out else ''
    return out, truncated


def socket_rows(text, limit=MAX_SOCKETS):
    rows = []
    more = False
    for line in text.splitlines():
        if not line.strip():
            continue
        if len(rows) == limit:
            more = True
            break
        parts = line.split(None, 6)
        if len(parts) < 6:
            raise ValueError('Unexpected socket output')
        protocol, state, recv, send, local, peer = parts[:6]
        if protocol not in ('tcp', 'udp'):
            raise ValueError('Unexpected socket protocol')
        rows.append({'protocol': protocol.upper(), 'state': state,
                     'local': local, 'peer': peer,
                     'process': parts[6] if len(parts) == 7 else '',
                     'recv': recv, 'send': send})
    return rows, more


def _json_command(args, host=None):
    text, truncated = (host.capture if host else capture)(args)
    if truncated:
        raise RuntimeError('Network output exceeded the snapshot size limit')
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError('Unexpected network output')
    return data


def snapshot(include_processes=False, host=None):
    result = {'interfaces': None, 'sockets': None, 'routes': [], 'errors': [],
              'limited': False, 'time': datetime.now().strftime('%H:%M:%S'),
              'processes': include_processes}
    try:
        interfaces = _json_command(['ip', '-j', 'address', 'show'], host)
        result['limited'] = len(interfaces) > MAX_INTERFACES
        result['interfaces'] = interfaces[:MAX_INTERFACES]
    except Exception as exc:
        result['errors'].append(f'Interfaces: {str(exc)[:300]}')
    # Two cheap local route queries cover both address families; no reachability probes.
    for family in ('-4', '-6'):
        try:
            routes = _json_command(['ip', '-j', family, 'route', 'show', 'default'], host)
            result['routes'].extend(routes[:32])
            result['limited'] |= len(routes) > 32
        except Exception as exc:
            result['errors'].append(f'{family} routes: {str(exc)[:300]}')
    try:
        args = ['ss', '-H', '-t', '-u', '-n', '-a', '-O']
        if include_processes:
            args.append('-p')
        text, capped = (host.capture if host else capture)(args)
        result['sockets'], more = socket_rows(text)
        result['limited'] |= capped or more
    except Exception as exc:
        result['errors'].append(f'Sockets: {str(exc)[:300]}')
    return result


def host_lan_ip(interfaces, routes=(), preferred=None):
    """Choose a host address from collected data without DNS or new probes."""
    import ipaddress
    candidates = []
    default_devices = {route.get('dev') for route in routes}
    for interface in interfaces or ():
        name = interface.get('ifname', '')
        if ('LOOPBACK' in interface.get('flags', ()) or name == 'lo'
                or interface.get('operstate') == 'DOWN'):
            continue
        virtual = name.startswith(('docker', 'br-', 'veth', 'pvpn', 'proton', 'tun', 'wg', 'tailscale'))
        for address in interface.get('addr_info', ()):
            if address.get('scope') != 'global':
                continue
            try:
                ip = ipaddress.ip_address(address.get('local', ''))
            except ValueError:
                continue
            if ip.is_loopback or ip.is_link_local or ip.is_unspecified:
                continue
            # A matching SSH address is the most useful identity for remote hosts.
            rank = (str(ip) != preferred, virtual, ip.version != 4, name not in default_devices,
                    interface.get('link_type') != 'ether')
            candidates.append((rank, str(ip)))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None
