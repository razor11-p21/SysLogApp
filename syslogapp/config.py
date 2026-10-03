# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "syslogapp"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "theme": "system",
    "refresh_interval": 5,
    "start_page": "dashboard",
    "compact_mode": False,
    "log_lines": 400,
}


def load_config():
    cfg = DEFAULTS.copy()
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    except Exception:
        pass
    return cfg


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = DEFAULTS.copy()
    payload.update({k: v for k, v in cfg.items() if k in DEFAULTS})
    CONFIG_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
