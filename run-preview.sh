#!/usr/bin/env bash
set -euo pipefail
PREVIEW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec /usr/bin/python3 "$PREVIEW_DIR/syslogapp.py" "$@"
