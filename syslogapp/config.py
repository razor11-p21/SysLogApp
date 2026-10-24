# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import json
import os
import tempfile
from pathlib import Path

CONFIG_DIR = Path.home() / '.config' / 'syslogapp'
CONFIG_FILE = CONFIG_DIR / 'config.json'
DEFAULTS = {'log_lines': 400, 'window': {}, 'columns': {}, 'hosts': []}
COLUMN_NAMES = {
    'logs': ('Severity', 'Time', 'Source', 'Level', 'Message'),
    'network': ('Proto', 'State', 'Local address', 'Local port', 'Remote address', 'Remote port', 'PID', 'Process'),
    'overview': ('Field', 'Value'),
}


def log_capacity(config):
    try:
        return max(100, min(2000, int(config.get('log_lines', 400))))
    except (ValueError, TypeError, OverflowError):
        return 400


def normalized(config):
    if not isinstance(config, dict):
        config = {}
    result = {'log_lines': log_capacity(config), 'window': {}, 'columns': {}, 'hosts': []}
    window = config.get('window', {})
    if isinstance(window, dict):
        for key, minimum in (('width', 640), ('height', 480)):
            value = window.get(key)
            if type(value) is int:
                result['window'][key] = max(minimum, min(8192, value))
        if type(window.get('maximized')) is bool:
            result['window']['maximized'] = window['maximized']
    columns = config.get('columns', {})
    if isinstance(columns, dict):
        for page, names in COLUMN_NAMES.items():
            values = columns.get(page)
            if isinstance(values, dict):
                result['columns'][page] = {name: max(24, min(4096, value))
                    for name, value in values.items() if name in names and type(value) is int}
    hosts = config.get('hosts', [])
    if isinstance(hosts, list) and hosts:
        from .hosts import host_profile
        for profile in hosts[:64]:
            try:
                result['hosts'].append(host_profile(profile))
            except (ValueError, TypeError):
                pass
    return result


def column_widths(config, page):
    return normalized(config)['columns'].get(page, {})


def load_config():
    try:
        return normalized(json.loads(CONFIG_FILE.read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return normalized({})


def save_config(config):
    """Replace one settings file atomically, only when the app closes."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.config-', suffix='.json', dir=CONFIG_DIR)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(normalized(config), stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, CONFIG_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
