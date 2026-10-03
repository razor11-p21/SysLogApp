#!/usr/bin/env bash
set -euo pipefail
rm -rf "$HOME/.local/share/syslogapp"
rm -f "$HOME/.local/bin/syslogapp"
rm -f "$HOME/.local/share/applications/syslogapp.desktop"
echo "SysLogApp application files removed."
echo "Preferences were kept at ~/.config/syslogapp. Remove that directory manually if you also want to delete settings."
