# Preview 48 — live controls, themed menus and responsive resizing

System logs and Network use one Live / Paused button, with F6/F7 shortcuts.
Selecting table text pauses Live. The obsolete Follow latest control and separate
scroll-hold state are removed. Event details open on double-click or Enter;
single-click selects a row. Tabs clear row selections and text highlights before
painting, with focus restored to a control to avoid transient text selection.

Network shows the selected host's hostname in purple and LAN IP in blue at the
right of the Live toolbar. IP selection reuses collected interface data, and SSH
hostname collection shares the existing capability probe. Dropdown and context
menus use the app's dark monospace theme. Redundant page title bars are removed.

Horizontal resizing coalesces automatic column fitting after 60 ms without a new
width change, preserving wrapping and manually resized columns. Synthetic GTK
measurements showed substantially lower resize CPU time; see PERFORMANCE.md for
workload and limits. Pending resize callbacks are cancelled when pages close.

Validation: 153 tests passed, covering local/SSH routing, Live pause/resume,
details activation, selection reset, themes/layout, wrapping and resize cleanup.
Existing settings are preserved. Reopen the installed app to load updated modules.

## Earlier changes — local/SSH host sidebar

A collapsible host sidebar selects Local or saved SSH profiles. Password, private
key and agent authentication use OpenSSH with explicit unknown-key trust and
changed-key rejection. No credentials/key contents are persisted. A single active
multiplexed SSH session serves all four tabs; switching frees old views, closes
live streams and discards stale callbacks. Host selection is always visible.

Logs and network collection run on the selected host, including Live/Pause,
filtering, process metadata, copy/export, colors and saved column widths. Overview
uses remote Python; maintenance resolves remote tools, confirms the named target
and authenticates through sudo/root. Logrotate configuration and its file browser
operate on remote paths. No remote software is installed automatically.

Remote journalctl/ip/ss permissions and tools still apply. Overview/rotation need
Python 3.8+. APT/dpkg-specific maintenance is disabled on hosts without those tools;
non-systemd text-log fallback is not implemented. Missing data never falls back to
Local. SSH connection failures are reported; administrative commands may continue
remotely if transport fails, so check before retrying. Host changes and closing
are blocked while maintenance runs. Local installation now requires openssh-client.

Validation includes mock password/askpass tests, real loopback key and encrypted-key
logins, new/changed host-key checks, authentication cancellation, read-only remote
logs/network/overview, stream cleanup, and isolated GTK host-switch tests. No real
maintenance change or external server authentication was performed by these checks.
Run `/usr/bin/python3 tests/ssh_integration_check.py` for the disposable loopback
check (requires sshd/ssh-keygen; it never edits system SSH configuration).

Network updates now keep unchanged GTK rows, including selection, rather than
rebuilding the table for small socket changes. Duplicate sockets retain their
counts. Network and log comparisons fetch only enough fields to decide order;
full tie-break semantics are preserved. Large messages/process strings bypass
global sorting caches instead of remaining retained after history eviction.
Timestamp parsing is cached with a fixed bound, and terminal palettes are reused.
See PERFORMANCE.md and scripts/benchmark_ui.py for local synthetic measurements.

All Network headers and values now align left, including multiline addresses
and process names. Column order, sorting, colors and saved widths are retained.

Normal closing now saves window size, maximized state and manual widths for Logs,
Network and Overview. Startup restores them, including lazily opened tabs. Tabs
not visited retain their saved settings. Fit columns clears saved overrides.
Only close/shutdown writes settings, using an atomic replacement; corrupt or old
settings fall back safely and restored windows fit the current display work area.

Network groups Proto/State, Local address/port, Remote address/port and finally
Process/PID. The shared group-header row has been removed, restoring the flat
Local address/port and Remote address/port headers. Process/PID remain at the end.
Both endpoint pairs use the same content-fitting rules, with trailing spare space
instead of stretched port columns. Explicit Local/Remote headers and aligned
numeric fields improve scanning. Process collection stays optional; sorting,
manual widths, responsive wrapping and Copy socket follow the displayed layout.

Network now has a Hide TIME-WAIT checkbox. It filters loaded rows locally, combines
with existing search/type filters and stays applied across snapshot/live updates.
It defaults off and is reversible without another scan.

GTK scroll-edge undershoot decorations are suppressed to remove the dashed lines
Mint themes draw at table boundaries. Scrolling, focus and selection are retained.

The app has System logs, Network, Overview and Maintenance tabs. Network loads only when opened, then
refreshes on demand or with optional Live/Pause. It has no graphs, DNS lookups or
external probes. Live reads only while visible, approximately every 2 seconds
after completion, without overlap; errors back off up to 30 seconds. Pause holds
the snapshot and discards in-flight automatic updates.
Process lookup is optional. The Cinnamon launcher remains a separate package.

## Debian-family packages

Build with `/usr/bin/python3 scripts/build_release.py`. The main package depends
on Python 3.9+, PyGObject, GTK3, journalctl (systemd), iproute2 (ip/ss) and OpenSSH client. It does
not require psutil, Cairo Python bindings or ping. APT/dpkg actions are optional;
administrator maintenance actions require pkexec and a PolicyKit authentication agent.
Do not remove shared system packages to reduce the dependency list; other desktop
software may still require them.

Install the generated package using APT so dependencies are resolved:

```bash
sudo apt install ./dist/preview48/syslogapp_2.0.0~preview48-1_all.deb
```

Install the matching `syslogapp-cinnamon-applet` package only on Cinnamon if wanted.
Enable it through Cinnamon's Applets settings. Package installation does not
change your panel preferences.

If migrating from a per-user installation, first run `bash ./uninstall.sh` from
that source copy to remove the launcher that would otherwise shadow `/usr/bin`.
Settings are preserved. The Debian package uses `/usr/share/syslogapp` and
`/usr/bin/syslogapp`; source installation uses `~/.local/share/syslogapp` and
`~/.local/bin/syslogapp`. Existing user configuration is preserved; `log_lines`, window geometry and manual column
widths apply to this version.

## Overview and Maintenance

Overview is a manual local snapshot of OS, uptime, CPU/load, memory/swap and root
filesystem space. It uses bounded proc-file reads and no sampling loop or commands.
Maintenance loads on demand and runs only explicitly selected actions. Changes
require confirmation and pkexec authentication; unavailable tools are disabled.
Administrative work uses a separate thread and no fixed timeout. Closing is blocked
while an action runs. Only a 128 KiB output tail is displayed; a temporary file
stores command output until completion. Read-only journal usage has a 5-second
and 64 KiB bound. No maintenance action is executed during build or GUI validation.

## Adjustable columns and Live

Drag header dividers in System logs, Network and Overview. Manual widths survive
refresh and window changes; Fit columns restores the automatic responsive layout.
Text wrapping is coalesced after width changes. Enabling Live restores ascending
Time sort and jumps to the newest visible row at the bottom. Other manual sorts
remain available during live collection.

Overview includes a built-in colored ASCII logo, without a neofetch subprocess.
Maintenance includes an optional text-log rotation editor for one `/var/log` file.
It controls schedule, archives, compression, size threshold and rename/copytruncate.
Saving requires review/authentication, validates the staged full config with
logrotate --debug, backs up prior app-managed settings and atomically saves only
/etc/logrotate.d/syslogapp. Failed validation and duplicate rules leave it unchanged.
Saving never triggers a rotation. Copytruncate can lose concurrent writes; rename
requires the log writer to reopen. System timer/cron frequency controls evaluation.
Logrotate is optional and suggested by the Debian package.

## Network readout

The table separates Local address/Port and Remote address/Port while keeping
wrapped text and separate PID/process columns. Widths are recalculated from
the viewport, including with process data enabled, so all columns fit at 640px.
Address and port headers sort independently and numerically. Blue active, purple
listener/handshake, gray idle/closing and amber CLOSE-WAIT states follow the log
palette, with quiet host text, amber ports, blue PIDs and purple process names. Process collection still takes effect on the
next refresh and remains optional, subject to ordinary user permissions.

The optional Extended processes checkbox shows full socket process metadata,
including file descriptors, using already loaded data. It defaults off, needs no
extra scan, and keeps selection and sort order. PID sorting is numeric.

## Compact output and sorting

Less row/toolbar padding, clock-only timestamps for today and a collapsed network
overview leave more room for output. Wrapping and full event details are preserved.
Logs open oldest first (newest last) and sort by full timestamp or actual severity. Network
addresses and ports sort numerically, with logical state grouping and stable ties.
Custom sorts survive live updates; history eviction is independent of display order.
Cached sort keys are bounded and require no additional dependency.

## Resource and data limits

Snapshot mode does not poll. Live mode reads journalctl output through a blocking
reader and delivers bounded batches to GTK at most every 100 ms while events
arrive. The pending queue and retained history each have a record limit, default
400 and maximum 2000. Overload skips the oldest pending records and reports it.
Normal rolling history eviction is intentional. Full retained messages remain
available in the inspector; the table wraps messages to the available width. Timestamp colors match event
severity. Resize reflow is debounced to avoid repeated full-history layout passes.

Network snapshots cap each command at 512 KiB and 3 seconds, retain at most 1000
sockets and 128 interfaces, and report partial collection failures. Socket filters
and searches do not launch commands. IPv4 and IPv6 default routes are included.
No process scan is done unless Processes is checked before a refresh.
Color-coded socket/interface states share the terminal palette. Unchanged tables
are not rebuilt; changing tabs, pausing or disabling Live removes its timer.

## Validation

The regression suite covers installer rollback, exact journal severity filters,
restricted access/errors, bounded bursts, stale callbacks, queue cleanup, local
search eviction, lazy network initialization, and collapsed event details. Display tests
require a GTK desktop. Local rendering and quiet-idle measurements are smoke
checks, not guarantees of CPU/GPU use on all desktops. Installation on clean
Debian/Ubuntu VMs and other compositors still needs independent testing before
public release. Nothing is published by the build script.

Preview48 groups Maintenance actions, adds a separate bounded streaming output
pane with elapsed time/exit status and Copy/Save/Clear, explicit age/size journal
cleanup with usage review, inline availability reasons, rotation summary/preview
and validation-only mode, and ten in-memory history records shared across hosts.
Network restart warnings identify SSH disconnect risk. Validation tests use
temporary fixture files; no cleanup, service restart or package repair is run.
