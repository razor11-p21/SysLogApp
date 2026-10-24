# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Explicit maintenance operations; never run automatically."""
from dataclasses import dataclass
import shutil
import subprocess
import tempfile


@dataclass(frozen=True)
class Action:
    title: str
    description: str
    command: tuple
    privileged: bool = True


ACTIONS = (
    Action('Journal disk usage', 'Read journal storage usage; no changes.',
           ('journalctl', '--disk-usage'), False),
    Action('Vacuum journal', 'Permanently delete archived journal files older than 7 days. '
           'Active journal files are retained.', ('journalctl', '--vacuum-time=7d')),
    Action('Clean APT cache', 'Delete downloaded package archives. Installed packages are retained.',
           ('apt-get', 'clean')),
    Action('Reload systemd', 'Reload unit definitions; does not restart running services.',
           ('systemctl', 'daemon-reload')),
    Action('Restart NetworkManager', 'Restart NetworkManager. Active network connections may be interrupted.',
           ('systemctl', 'restart', 'NetworkManager.service')),
    Action('Configure pending packages', 'Run pending package configuration. Package scripts may change '
           'the system and take several minutes. If input is required, use sudo dpkg --configure -a '
           'in a terminal instead.', ('dpkg', '--configure', '-a')),
)


def resolve(action):
    executable = shutil.which(action.command[0])
    if not executable:
        return None, f'{action.command[0]} is not installed'
    args = [executable, *action.command[1:]]
    if action.privileged:
        pkexec = shutil.which('pkexec')
        if not pkexec:
            return None, 'pkexec is not installed; administrator authentication unavailable'
        args.insert(0, pkexec)
    return args, ''


def run_action(args, privileged=True, on_output=None):
    if on_output is not None:
        return stream_process(args, on_output, timeout=None if privileged else 5)
    if not privileged:
        from .network import capture
        output, limited = capture(args, timeout=5, max_bytes=64 * 1024)
        return 0, output + ('\n[Output limited]' if limited else '')
    # A package operation must not be killed by an arbitrary timeout. Redirect to
    # disk so closing a pipe cannot interrupt it; retain only a bounded text tail.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        code = process.wait()
        length = output.tell()
        limit = 128 * 1024
        output.seek(max(0, length - limit))
        text = output.read(limit).decode('utf-8', 'replace')
        if length > limit:
            text = '[Earlier output omitted]\n' + text
        return code, text


def vacuum_action(mode, value):
    if mode not in ('age', 'size') or type(value) is not int or not 1 <= value <= 102400:
        raise ValueError('Choose an age or size between 1 and 102400.')
    option = f'--vacuum-time={value}d' if mode == 'age' else f'--vacuum-size={value}M'
    policy = f'older than {value} days' if mode == 'age' else f'to target {value} MiB of journal storage'
    return Action('Vacuum journal', f'Permanently remove archived journal files {policy}. '
                  'Active files are retained; the target may not be reached. No exact reclaim estimate is available.',
                  ('journalctl', option))


def stream_process(args, on_output, spawn=None, password=None, timeout=None):
    """Stream a bounded tail; administrative commands have no runtime deadline."""
    import codecs
    import os
    import selectors
    import signal
    import time
    spawn = spawn or subprocess.Popen
    process = spawn(args, stdin=subprocess.PIPE if password is not None else subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    if password is not None:
        try:
            process.stdin.write((password + '\n').encode())
            process.stdin.close()
        except BrokenPipeError:
            pass
        password = None
    tail = bytearray()
    total = 0
    deadline = time.monotonic() + timeout if timeout else None
    decoder = codecs.getincrementaldecoder('utf-8')('replace')
    def emit(text):
        try:
            on_output(text)
        except Exception:
            # Losing progress display must not interrupt a package operation.
            pass
    def remaining():
        return max(0, deadline - time.monotonic()) if deadline else None
    def terminate():
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
    try:
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if deadline and remaining() <= 0:
                    raise TimeoutError('Read-only check timed out')
                events = selector.select(min(.25, remaining()) if deadline else .25)
                if not events and process.poll() is not None:
                    break
                for key, _ in events:
                    chunk = os.read(key.fd, 16384)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    tail.extend(chunk)
                    del tail[:-128 * 1024]
                    text = decoder.decode(chunk)
                    if text:
                        emit(text)
            last = decoder.decode(b'', final=True)
            if last:
                emit(last)
        try:
            code = process.wait(timeout=remaining()) if deadline else process.wait()
        except subprocess.TimeoutExpired:
            raise TimeoutError('Read-only check timed out') from None
    except Exception as error:
        if process.poll() is None:
            terminate()
        error.output = tail.decode('utf-8', 'replace')
        raise
    finally:
        process.stdout.close()
    text = tail.decode('utf-8', 'replace')
    if total > len(tail):
        text = '[Earlier output omitted]\n' + text
    return code, text
