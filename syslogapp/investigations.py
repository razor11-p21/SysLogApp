# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""On-demand, bounded, private storage for saved journal investigations."""
import hashlib
import json
import os
import tempfile
from pathlib import Path

STORE_FILE = Path.home() / '.config/syslogapp/investigations.json'
MAX_FILE_BYTES = 1024 * 1024
MAX_ITEMS = 100
MAX_MESSAGE_BYTES = 8192
SCOPES = ('boot', 'previous', 'all')
PRIORITIES = ('All', 'Critical', 'Error', 'Warning', 'Notice', 'Info', 'Debug')


def text(value, limit):
    return str(value or '')[:limit].replace('\x00', '')


def host_identity(host=None):
    if host is None:
        return 'local', 'Local host'
    profile = host.profile
    identity = json.dumps([profile['username'], profile['hostname'], int(profile.get('port', 22))])
    return identity, text(getattr(host, 'label', None) or profile['hostname'], 160)


def view_settings(values):
    from .log_view import display_settings
    if not isinstance(values, dict):
        values = {}
    history = values.get('history', {})
    if not isinstance(history, dict):
        history = {}
    query = {}
    for key in ('since', 'until'):
        value = history.get(key)
        if isinstance(value, str) and value.startswith('@') and value[1:].lstrip('-').isdigit() and len(value) <= 24:
            query[key] = value
    if history.get('match'):
        query['match'] = text(history['match'], 512)
    if values.get('page') == 'network':
        return {'page': 'network', 'search': text(values.get('search'), 512),
                'kind': values.get('kind') if type(values.get('kind')) is int and values['kind'] in (0, 1, 2) else 1,
                'hide_time_wait': values.get('hide_time_wait') is True,
                'application': text(values.get('application'), 128),
                'pid': text(values.get('pid'), 10), 'port': text(values.get('port'), 5),
                'port_side': values.get('port_side') if values.get('port_side') in ('either', 'local', 'remote') else 'either',
                'processes': values.get('processes') if values.get('processes') in ('off', 'basic', 'extended') else 'basic'}
    return {'page': 'logs', 'scope': values.get('scope') if values.get('scope') in SCOPES else 'boot',
            'priority': values.get('priority') if values.get('priority') in PRIORITIES else 'All',
            'unit': text(values.get('unit'), 512), 'search': text(values.get('search'), 512),
            'history': query, **display_settings(values)}


def load():
    try:
        with STORE_FILE.open('rb') as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        return {'version': 1, 'views': [], 'bookmarks': []}
    if len(data) > MAX_FILE_BYTES:
        raise ValueError('Saved investigations exceed the 1 MiB storage limit.')
    try:
        result = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Saved investigations could not be read; the file was left unchanged.') from exc
    if (not isinstance(result, dict) or result.get('version') != 1 or
            any(not isinstance(result.get(key), list) or len(result[key]) > MAX_ITEMS
                or any(not isinstance(item, dict) or not isinstance(item.get('id'), str)
                       or not isinstance(item.get('host'), str) or not isinstance(item.get('name'), str)
                       for item in result[key]) for key in ('views', 'bookmarks'))):
        raise ValueError('Saved investigations have an unsupported format; the file was left unchanged.')
    return result


def _write(data):
    encoded = (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError('Saved investigations are full; remove an item before saving another.')
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.investigations-', dir=STORE_FILE.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, STORE_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _put(kind, item):
    data = load()
    items = data[kind]
    index = next((i for i, old in enumerate(items) if old['id'] == item['id']), None)
    if index is not None:
        items[index] = item
    elif len(items) >= MAX_ITEMS:
        raise ValueError(f'Limit of {MAX_ITEMS} {kind} reached; remove an item first.')
    else:
        items.append(item)
    _write(data)


def save_view(host, name, values):
    name = text(name, 80).strip()
    if not name:
        raise ValueError('Enter a name for this view.')
    history = values.get('history', {})
    for value in (values.get('unit', ''), values.get('search', ''), history.get('match', '') if isinstance(history, dict) else ''):
        if len(str(value or '')) > 512:
            raise ValueError('Saved filter fields are limited to 512 characters; shorten this filter before saving.')
    key, label = host_identity(host)
    item = {'id': hashlib.sha256((key + '\x00' + view_settings(values)['page'] + '\x00' + name).encode()).hexdigest(),
            'host': key, 'host_label': label, 'name': name, 'settings': view_settings(values)}
    _put('views', item)
    return item


def bookmark(host, name, row):
    name = text(name, 160).strip()
    if not name:
        raise ValueError('Enter a name for this bookmark.')
    key, label = host_identity(host)
    raw = row.get('raw') or {}
    cursor = text(raw.get('__CURSOR'), 4096)
    message = str(raw.get('MESSAGE', row.get('message', '')))
    encoded = message.encode('utf-8', 'replace')
    excerpt = encoded[:MAX_MESSAGE_BYTES].decode('utf-8', 'ignore')
    event = {'time': text(row.get('time'), 80), 'unit': text(row.get('unit'), 512),
             'level': text(row.get('level'), 24), 'message': excerpt,
             'cursor': cursor, 'boot': text(raw.get('_BOOT_ID'), 128),
             'excerpt': len(encoded) > MAX_MESSAGE_BYTES}
    identity = cursor or (json.dumps(event, sort_keys=True) + hashlib.sha256(encoded).hexdigest())
    item = {'id': hashlib.sha256((key + '\x00' + identity).encode()).hexdigest(),
            'host': key, 'host_label': label, 'name': name, 'event': event}
    _put('bookmarks', item)
    return item


def remove(kind, identity):
    if kind not in ('views', 'bookmarks'):
        raise ValueError('Unknown saved item type')
    data = load()
    data[kind] = [item for item in data[kind] if item['id'] != identity]
    _write(data)
