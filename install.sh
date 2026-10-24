#!/usr/bin/env bash
set -euo pipefail
INSTALL_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x /usr/bin/python3 ]]; then
    echo 'Python 3 is required. Install python3 with your package manager.' >&2
    exit 1
fi
exec /usr/bin/python3 "$INSTALL_SOURCE/scripts/install_user.py"
