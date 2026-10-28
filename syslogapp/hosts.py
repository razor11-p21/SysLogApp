# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""One explicit, multiplexed OpenSSH session for the selected remote host."""
import json
import ipaddress
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import weakref
import selectors

TOOLS = ('journalctl', 'ip', 'ss', 'python3', 'sudo', 'apt-get',
         'systemctl', 'dpkg', 'logrotate', 'cat', 'find')
REMOTE_PATH = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'


def host_profile(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid host profile')
    host = str(data.get('hostname', '')).strip()
    user = str(data.get('username', '')).strip()
    if host.startswith('[') and host.endswith(']'):
        host = host[1:-1]
    valid = bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,252}', host))
    if ':' in host and re.fullmatch(r'[A-Za-z0-9_.:%-]{1,253}', host):
        try:
            ipaddress.IPv6Address(host)
            valid = True
        except ValueError:
            pass
    if not valid:
        raise ValueError('Enter a hostname, IP address or SSH host alias (without user@).')
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]{0,63}', user):
        raise ValueError('Enter a valid SSH username.')
    try:
        port = int(data.get('port', 22))
    except (TypeError, ValueError, OverflowError):
        raise ValueError('SSH port must be between 1 and 65535')
    if not 1 <= port <= 65535:
        raise ValueError('SSH port must be between 1 and 65535')
    auth = data.get('auth', 'key')
    if auth not in ('key', 'password'):
        raise ValueError('Choose key or password authentication')
    key = str(data.get('key_file', ''))[:4096]
    if '\x00' in key or '\n' in key:
        raise ValueError('Invalid key path')
    label = str(data.get('label', '')).strip()[:80] or f'{user}@{host}'
    label = ''.join(char for char in label if char.isprintable())
    return {'label': label, 'hostname': host, 'username': user,
            'port': port, 'auth': auth, 'key_file': key}


class SSHHost:
    remote = True

    def __init__(self, profile, known_hosts=None):
        self.profile = host_profile(profile)
        self.label = self.profile['label']
        address = self.profile["hostname"]
        if ":" in address:
            address = "[" + address + "]"
        self.target = f"{self.profile['username']}@{address}:{self.profile['port']}"
        self._directory = tempfile.TemporaryDirectory(prefix='sla-ssh-')
        self.control = str(Path(self._directory.name) / 's')
        self.known_hosts = known_hosts
        self.connected = False
        self.state = 'disconnected'
        self.state_handler = None
        self.credential_warning = None
        self._state_lock = threading.Lock()
        self._health_lock = threading.Lock()
        self._watch_stop = None
        self._closed = False
        self._lock = threading.Lock()
        self._children = weakref.WeakSet()
        self._connect_proc = None
        self.tools = {}
        self.uid = None
        self.python_version = None
        self.hostname = None
        self.rotation_text = ''
        wrapper = Path(self._directory.name) / 'askpass'
        helper = Path(__file__).with_name('ssh_askpass.py')
        wrapper.write_text('#!/bin/sh\nexec /usr/bin/python3 ' + shlex.quote(str(helper)) + ' "$@"\n')
        wrapper.chmod(0o700)
        self.askpass = str(wrapper)

    def _options(self):
        args = [shutil.which('ssh') or 'ssh', '-S', self.control, '-p', str(self.profile['port']),
                '-l', self.profile['username'], '-o', 'ConnectTimeout=15', '-o', 'ConnectionAttempts=1',
                '-o', 'ForwardAgent=no', '-o', 'AddKeysToAgent=no', '-o', 'ForwardX11=no', '-o', 'ClearAllForwardings=yes',
                '-o', 'PermitLocalCommand=no', '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=2']
        if self.known_hosts is not None:
            args += ['-o', 'UserKnownHostsFile=' + str(self.known_hosts)]
        return args

    def connect(self):
        self._set_state('connecting')
        if not shutil.which('ssh'):
            raise RuntimeError('Install the OpenSSH client to connect to remote hosts.')
        args = self._options() + ['-M', '-N', '-f', '-o', 'ControlPersist=no',
                '-o', 'StrictHostKeyChecking=ask', '-o', 'NumberOfPasswordPrompts=3']
        if self.profile['auth'] == 'password':
            args += ['-o', 'PreferredAuthentications=keyboard-interactive,password', '-o', 'PubkeyAuthentication=no']
        else:
            args += ['-o', 'PreferredAuthentications=publickey', '-o', 'PasswordAuthentication=no']
            if self.profile['key_file']:
                key = Path(self.profile['key_file']).expanduser()
                if not key.is_file():
                    raise ValueError('SSH key file does not exist')
                args += ['-i', str(key), '-o', 'IdentitiesOnly=yes']
        args += ['--', self.profile['hostname']]
        environment = dict(os.environ, SSH_ASKPASS=self.askpass, SSH_ASKPASS_REQUIRE='force',
                           SYSLOGAPP_SSH_TARGET=self.target, LC_ALL='C',
                           SYSLOGAPP_SSH_AUTH=self.profile['auth'],
                           SYSLOGAPP_SSH_ACCOUNT=json.dumps({key: self.profile[key] for key in ('hostname', 'username', 'port')}),
                           SYSLOGAPP_SSH_ATTEMPT=str(Path(self._directory.name) / 'password-attempt'))
        pending = None
        if self.profile['auth'] == 'password':
            from .pending_password import PendingPassword
            try:
                pending = PendingPassword(self._directory.name)
                environment['SYSLOGAPP_SSH_PENDING'] = str(pending.path)
            except OSError:
                self.credential_warning = 'Password saving is unavailable for this connection.'
        try:
            # A background SSH master retains its descriptors. Use a file for
            # diagnostics instead of pipes that would never reach EOF after -f.
            with tempfile.TemporaryFile() as output:
                proc = self._spawn(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=output, env=environment, start_new_session=True)
                self._connect_proc = proc
                code = proc.wait(timeout=180)
                if code:
                    length = output.tell()
                    output.seek(max(0, length - 128 * 1024))
                    raise RuntimeError(output.read(128 * 1024).decode('utf-8', 'replace').strip()
                                       or f'SSH connection failed (exit {code})')
            if self._closed:
                raise RuntimeError('Connection cancelled')
            self.connected = True
            self._probe()
            self._set_state('connected')
            self._watch_master()
            if not self.connected:
                raise RuntimeError('SSH connection was lost while connecting')
            if pending:
                secret = pending.take()
                if secret is not None:
                    try:
                        from .credentials import PasswordStore
                        PasswordStore(self.profile).save(secret)
                    except Exception:
                        self.credential_warning = 'Connected, but the password could not be saved in the desktop keyring.'
                    finally:
                        secret = None
            return self
        except Exception:
            self.close()
            raise
        finally:
            if pending:
                pending.close()
            self._connect_proc = None

    def _spawn(self, command, **kwargs):
        with self._lock:
            if self._closed:
                raise RuntimeError('SSH session is closed; reconnect to continue.')
            proc = subprocess.Popen(command, **kwargs)
            self._children.add(proc)
            return proc

    def command(self, args, tty=False):
        if not self.connected or self._closed:
            raise RuntimeError('SSH session is not connected')
        # Existing master only: never silently start a new authenticated session
        # after the socket disappears. Arguments are quoted for the remote shell.
        return self._options() + ['-tt' if tty else '-T', '-o', 'ControlMaster=no',
            '-o', 'BatchMode=yes', '-o', 'ProxyCommand=false', '-o', 'StrictHostKeyChecking=yes',
            '--', self.profile['hostname'],
            'env LC_ALL=C PATH=' + REMOTE_PATH + ' ' + shlex.join([str(arg) for arg in args])]

    def popen(self, args, **kwargs):
        kwargs.setdefault('stdin', subprocess.DEVNULL)
        return self._spawn(self.command(args, tty=True), **kwargs)

    def capture(self, args, timeout=5, max_bytes=512 * 1024, return_stderr=False):
        from .network import capture
        try:
            return capture(self.command(args), timeout=timeout, max_bytes=max_bytes,
                           popen_factory=self._spawn, return_stderr=return_stderr)
        except Exception:
            self.check_transport()
            raise

    def _set_state(self, state, reason=''):
        with self._state_lock:
            if self._closed and state != 'disconnected':
                return
            self.connected = state == 'connected'
            if self.state == state:
                return
            self.state = state
            callback = self.state_handler
        if callback:
            callback(self, state, reason)

    def _control_check(self):
        from .network import capture
        _out, limited, diagnostic = capture(self._options() + ['-O', 'check', '--', self.profile['hostname']],
                                           timeout=2, max_bytes=4096, return_stderr=True)
        if limited:
            raise RuntimeError('SSH control check exceeded its output limit')
        return diagnostic

    def check_transport(self):
        # Only failed reads request a control check. Successful monitoring adds
        # no probes. Never confuse an ordinary command failure with SSH loss.
        if self._closed or not self.connected or not self._health_lock.acquire(False):
            return
        try:
            self._control_check()
        except Exception:
            self._set_state('disconnected', 'SSH transport is unavailable')
        finally:
            self._health_lock.release()

    def _watch_master(self):
        diagnostic = self._control_check()
        match = re.search(r'Master running \(pid=(\d+)\)', diagnostic)
        if not match or not hasattr(os, 'pidfd_open'):
            return  # Older kernels still detect loss on the next failed read.
        try:
            descriptor = os.pidfd_open(int(match[1]))
        except OSError:
            return
        try:
            reader, writer = os.pipe()
        except OSError:
            os.close(descriptor)
            return  # Failed-read transport checks remain available.
        self._watch_stop = writer
        def wait():
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(descriptor, selectors.EVENT_READ, 'master')
                    selector.register(reader, selectors.EVENT_READ, 'stop')
                    events = selector.select()
                    if any(key.data == 'master' for key, _ in events) and not self._closed:
                        self._set_state('disconnected', 'SSH connection lost')
            finally:
                os.close(descriptor)
                os.close(reader)
                with self._state_lock:
                    self._watch_stop = None
                    os.close(writer)
        threading.Thread(target=wait, name='ssh-master-exit', daemon=True).start()

    def _probe(self):
        script = 'for tool in ' + ' '.join(dict.fromkeys(TOOLS)) + '; do printf "%s=" "$tool"; command -v "$tool" || true; done; printf "uid="; id -u'
        version = shlex.quote('import sys; print(str(sys.version_info[0])+"."+str(sys.version_info[1]))')
        script += '; printf "hostname="; cat /proc/sys/kernel/hostname 2>/dev/null || true'
        script += '; if command -v python3 >/dev/null 2>&1; then printf "python-version="; python3 -c ' + version + '; fi'
        text, limited = self.capture(['sh', '-c', script], timeout=10, max_bytes=16384)
        if limited:
            raise RuntimeError('Remote capability output exceeded its limit')
        self.tools = {}
        for line in text.splitlines():
            name, _, value = line.partition('=')
            if name == 'uid':
                self.uid = int(value)
            elif name == 'hostname':
                self.hostname = value.strip()[:253] or None
            elif name == 'python-version':
                try:
                    self.python_version = tuple(map(int, value.split('.')))
                except ValueError:
                    self.python_version = None
            elif name in TOOLS and value.startswith('/'):
                self.tools[name] = value
        try:
            text, _ = self.capture(['cat', '/etc/logrotate.d/syslogapp'], timeout=5, max_bytes=8192)
            self.rotation_text = text
        except Exception:
            self.rotation_text = ''

    def which(self, program):
        return self.tools.get(program)

    @property
    def python_ready(self):
        return bool(self.which('python3') and self.python_version and self.python_version >= (3, 8))

    def overview(self, include_remote=False):
        if not self.python_ready:
            raise RuntimeError('Overview requires Python 3.8 or newer on the remote host.')
        source = Path(__file__).with_name('overview.py').read_text()
        text, limited = self.capture([self.which('python3'), '-c', source + f'\nimport json; print(json.dumps(snapshot(include_remote={bool(include_remote)!r}), ensure_ascii=False))'],
                                     timeout=10, max_bytes=256 * 1024)
        if limited:
            raise RuntimeError('Remote overview exceeded its output limit')
        result = json.loads(text)
        if not isinstance(result, dict) or not isinstance(result.get('rows'), list):
            raise RuntimeError('Invalid remote overview response')
        return result

    def resolve_action(self, action):
        args = list(action.command)
        if len(args) > 1 and str(args[1]).endswith('/logrotate_config.py'):
            python = self.which('python3')
            if not self.python_ready or not self.which('logrotate'):
                return None, 'Remote logrotate and Python 3.8+ are required'
            args = [python, '-c', Path(__file__).with_name('logrotate_config.py').read_text(), *args[2:]]
        else:
            executable = self.which(args[0])
            if not executable:
                return None, f'{args[0]} is unavailable on {self.target}'
            args[0] = executable
        if action.privileged and self.uid != 0:
            if not self.which('sudo'):
                return None, 'Administrator actions need sudo or an SSH root login on this host'
            args = [self.which('sudo'), '-S', '-p', '', '--', 'sh', '-c',
                    'exec "$@" </dev/null', 'syslogapp', *args]
        return args, ''

    def maintenance(self, args, password=None, on_output=None, timeout=None):
        if on_output is not None:
            from .maintenance import stream_process
            code, text = stream_process(self.command(args), on_output, spawn=self._spawn, password=password, timeout=timeout)
            if code == 255:
                text += "\nSSH connection lost. The remote operation may still be running; check the host before retrying."
            return code, text
        # No fixed timeout for administrative/package work. Only output's tail
        # is brought into RAM; password is sent through stdin, never argv/env.
        with tempfile.TemporaryFile() as output:
            proc = self._spawn(self.command(args), stdin=subprocess.PIPE if password is not None else subprocess.DEVNULL,
                               stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            if password is not None:
                try:
                    proc.stdin.write((password + '\n').encode())
                    proc.stdin.close()
                except BrokenPipeError:
                    pass
                password = None
            code = proc.wait()
            length = output.tell()
            output.seek(max(0, length - 128 * 1024))
            text = output.read(128 * 1024).decode('utf-8', 'replace')
            if length > 128 * 1024:
                text = '[Earlier output omitted]\n' + text
            if code == 255:
                text += '\nSSH connection lost. The remote operation may still be running; check the host before retrying.'
            return code, text

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for proc in list(self._children):
                if proc.poll() is None or proc is self._connect_proc:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
        with self._state_lock:
            if self._watch_stop is not None:
                try:
                    os.write(self._watch_stop, b'x')
                except OSError:
                    pass
        if self.connected or Path(self.control).exists():
            try:
                subprocess.run(self._options() + ['-O', 'exit', '--', self.profile['hostname']],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
        self._set_state('disconnected', 'SSH session closed')
        self._directory.cleanup()


class HostContext:
    """Page scope: a late callback from a former host cannot update the new host."""
    def __init__(self, application, host):
        self.application = application
        self.host = host
        self.active = True
        self.generation = 0

    @property
    def config(self):
        return self.application.config

    @property
    def window(self):
        return self.application.window

    @property
    def _closing(self):
        return not self.active or self.application._closing

    def run_async(self, function, callback):
        generation = self.generation
        def finished(result, error):
            if not self._closing and generation == self.generation:
                return callback(result, error)
            return False
        def scoped():
            if self._closing or generation != self.generation:
                raise RuntimeError('Obsolete host read cancelled')
            if self.host and not getattr(self.host, 'connected', True):
                raise RuntimeError('SSH disconnected; reconnect before reading current data.')
            return function()
        self.application.run_async(scoped, finished)
