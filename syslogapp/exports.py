# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""On-demand, bounded exports. Redaction never edits the collected source data."""
import csv
from datetime import datetime
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import tempfile
from . import __version__

MAX_EXPORT_BYTES = 32 * 1024 * 1024
PREVIEW_CHARS = 32768
MAX_REDACTION_TOKENS = 10000
IGNORED_PREFIX = ''.join(chr(i) for i in range(33)) + '\ufeff\u200b\u200c\u200d\u2060'
IPV4 = re.compile(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w]|\.\d)')
IPV6 = re.compile(r'(?<![\w:])(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:.]*(?:%[\w.-]+)?(?!\w)')
HOST = re.compile(r'(?<![\w.-])[a-zA-Z0-9][a-zA-Z0-9.-]{0,253}(?![\w.-])')
USER = re.compile(r'(?i)(\b(?:user(?:name)?[=:]\s*|for (?:invalid user |user )|as user )|/home/)([a-zA-Z_][\w.-]*)')
AUTH_USER = re.compile(r'(?i)(\b(?:accepted|failed) (?:password|publickey|keyboard-interactive) for (?:invalid user )?)([a-zA-Z_][\w.-]*)')
AT_USER = re.compile(r'(?<![\w.-])([a-zA-Z_][\w.-]*)@(?=[a-zA-Z<])')
HOST_CONTEXT = re.compile(r'(?i)(\bhost(?:name)?[=:]\s*)([a-zA-Z0-9][\w.-]*)')
FILE_SUFFIXES = {'service', 'scope', 'slice', 'target', 'socket', 'timer', 'mount', 'automount',
                 'device', 'swap', 'path', 'log', 'conf', 'json', 'jsonl', 'csv', 'py', 'so', 'txt'}


class Redactor:
    def __init__(self, options, hosts=(), users=()):
        self.options = options
        self.maps = {key: {} for key in ('IP', 'HOST', 'USER', 'TEXT')}
        self.hosts = [name for name in hosts if name]
        self.users = [name for name in users if name]
        self.custom = list(dict.fromkeys(line.strip() for line in options.get('custom', '').splitlines() if line.strip()))
        if len(self.custom) > 32 or any(len(value) > 256 for value in self.custom):
            raise ValueError('Use up to 32 custom redactions, each at most 256 characters.')

    def token(self, kind, value):
        identity = value.casefold() if kind == 'HOST' else value
        mapping = self.maps[kind]
        if identity not in mapping:
            if sum(len(values) for values in self.maps.values()) >= MAX_REDACTION_TOKENS:
                raise ValueError('Too many distinct redaction values; select fewer entries or narrow the filters.')
            mapping[identity] = f'<{kind}{len(mapping) + 1}>'
        return mapping[identity]

    def _ip(self, match):
        value = match.group()
        suffix = ''
        try:
            ip = ipaddress.ip_address(value.split('%', 1)[0])
        except ValueError:
            candidate = value.rstrip('.:')
            suffix = value[len(candidate):]
            try:
                ip = ipaddress.ip_address(candidate.split('%', 1)[0])
            except ValueError:
                return value
        canonical = str(ip.ipv4_mapped or ip) if ip.version == 6 else str(ip)
        return self.token('IP', canonical) + suffix

    def _known(self, value, names, kind):
        for name in sorted(set(names), key=lambda item: (-len(item), item)):
            pattern = r'(?<![\w.-])' + re.escape(name) + r'(?![\w.-])'
            value = re.sub(pattern, lambda _: self.token(kind, name), value,
                           flags=re.IGNORECASE if kind == 'HOST' else 0)
        return value

    def _host(self, match):
        value = match[0]
        name = value.rstrip('.')
        labels = name.split('.')
        if (len(labels) < 2 or len(name) > 253 or not labels[-1].isalpha()
                or not 2 <= len(labels[-1]) <= 63 or labels[-1].lower() in FILE_SUFFIXES
                or any(not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label) for label in labels)):
            return value
        return self.token('HOST', name) + value[len(name):]

    def string(self, value):
        # Replace explicit custom strings before automatic patterns, so a user
        # can remove paths, identifiers or application-specific secrets too.
        for literal in sorted(self.custom, key=lambda item: (-len(item), item)):
            value = value.replace(literal, self.token('TEXT', literal))
        if self.options.get('ips'):
            value = IPV6.sub(self._ip, value)
            value = IPV4.sub(self._ip, value)
        if self.options.get('hosts'):
            known = []
            for name in self.hosts:
                try:
                    ipaddress.ip_address(name.strip('[]'))
                except ValueError:
                    known.append(name)
            value = self._known(value, known, 'HOST')
            value = HOST_CONTEXT.sub(lambda m: m[1] + self.token('HOST', m[2]), value)
            value = HOST.sub(self._host, value)
        if self.options.get('users'):
            value = self._known(value, self.users, 'USER')
            value = USER.sub(lambda m: m[1] + self.token('USER', m[2]), value)
            value = AUTH_USER.sub(lambda m: m[1] + self.token('USER', m[2]), value)
            value = AT_USER.sub(lambda m: self.token('USER', m[1]) + '@', value)
        return value

    def apply(self, value):
        if isinstance(value, str):
            return self.string(value)
        if isinstance(value, dict):
            return {key: self.apply(item) for key, item in value.items()}
        if isinstance(value, list):
            if value and all(type(item) is int and 0 <= item <= 255 for item in value):
                return '<BINARY OMITTED>'
            return [self.apply(item) for item in value]
        return value


def source_host(host=None):
    if host is None:
        return {'kind': 'local', 'hostname': socket.gethostname(), 'username': os.environ.get('USER', '')}
    profile = host.profile
    return {'kind': 'ssh', 'hostname': profile['hostname'], 'username': profile['username'],
            'port': profile.get('port', 22), 'label': getattr(host, 'label', profile['hostname'])}


def metadata(kind, host, filters, selected, shown, loaded, state=None):
    now = datetime.now().astimezone()
    return {'schema': 'syslogapp-export/v1', 'app_version': __version__, 'view': kind,
            'exported_at': now.isoformat(timespec='seconds'),
            'display_timezone': now.strftime('%Z (UTC%z)'),
            'timestamp_policy': 'Journal time_iso uses the local UTC offset at each event; display_timezone describes export time.', 'source': source_host(host),
            'filters': filters, 'selection': 'selected entries' if selected else 'all filtered loaded entries',
            'shown_count': shown, 'loaded_count': loaded, 'view_state': state or {}}


def safe_cell(value):
    text = str(value if value is not None else '')
    visible = text.lstrip(IGNORED_PREFIX)
    if visible.startswith(('=', '+', '-', '@')) or (text and ord(text[0]) < 32):
        return "'" + text
    return text


def render(records, meta, format_name='jsonl', options=None, hosts=(), users=()):
    if format_name not in ('jsonl', 'csv'):
        raise ValueError('Unknown export format')
    options = dict(options or {})
    redactor = Redactor(options, hosts, users)
    redacted = any(options.get(key) for key in ('ips', 'hosts', 'users')) or bool(redactor.custom)
    context = dict(meta, entry_count=len(records), redaction={key: bool(options.get(key)) for key in ('ips', 'hosts', 'users')})
    context['redaction'].update(custom_count=len(redactor.custom), best_effort=redacted,
                                binary_fields_omitted=redacted)
    if format_name == 'csv':
        context['csv_formula_policy'] = 'Formula-like cells prefixed with an apostrophe; all cells quoted'
    parts, size = [], 0
    def append(text):
        nonlocal size
        size += len(text.encode('utf-8'))
        if size > MAX_EXPORT_BYTES:
            raise ValueError('Export exceeds 32 MiB. Select fewer entries or narrow the filters.')
        parts.append(text)
    if redacted:
        for key in ('source', 'filters', 'view_state'):
            context[key] = redactor.apply(context[key])
        context['source']['kind'] = meta['source']['kind']
    if format_name == 'jsonl':
        append(json.dumps({'type': 'metadata', **context}, ensure_ascii=False) + '\n')
        for record in records:
            item = redactor.apply(record) if redacted else record
            if redacted and 'type' in record:
                item['type'] = record['type']
            append(json.dumps(item, ensure_ascii=False) + '\n')
    else:
        fields = (('time', 'Time'), ('time_iso', 'Time ISO 8601'), ('unit', 'Source'), ('level', 'Level'), ('message', 'Message')) if meta['view'] == 'logs' else (
            ('protocol', 'Proto'), ('state', 'State'), ('local_address', 'Local address'), ('local_port', 'Local port'),
            ('remote_address', 'Remote address'), ('remote_port', 'Remote port'), ('pid', 'PID'), ('process', 'Process'))
        prefix = ('Source host', 'Source user', 'Host kind', 'SSH port', 'Source label', 'App version', 'Exported entries', 'Timezone at export', 'Exported at', 'Active filters',
                  'Selection', 'View status', 'Redaction')
        buffer = io.StringIO(newline='')
        writer = csv.writer(buffer, quoting=csv.QUOTE_ALL)
        def csv_row(values):
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow([safe_cell(value) for value in values])
            append(buffer.getvalue())
        csv_row([*prefix, *(label for _, label in fields)])
        shared = [context['source'].get('hostname', ''), context['source'].get('username', ''), context['source']['kind'], context['source'].get('port', ''), context['source'].get('label', ''),
                  context['app_version'], context['entry_count'], context['display_timezone'], context['exported_at'], json.dumps(context['filters'], ensure_ascii=False),
                  context['selection'], json.dumps(context['view_state'], ensure_ascii=False), json.dumps(context['redaction'])]
        for record in records:
            item = redactor.apply(record) if redacted else record
            csv_row([*shared, *(item.get(key, '') for key, _ in fields)])
    return ''.join(parts)


def write_atomic(path, text):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.syslogapp-export-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
