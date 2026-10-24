# SysLogApp — Preview 48

A terminal-style **system journal and network viewer** for systemd-based Linux
desktops, with Overview and Maintenance tabs. Extra pages load only when opened;
there are no resource graphs or background health checks.

Copyright (C) 2026 pit pitopoulos. GPL-3.0-or-later; see LICENSE and NOTICE.md.

## Interface

- Flat charcoal background, monospace text and restrained severity colors.
- Current boot / recent history, exact severity and systemd service filters.
- Search the loaded history locally; typing never spawns a new journal command.
- Messages wrap to fit the window; double-click a row to open its full message and process details.
  Single-click selects a row; details stay collapsed until double-click or Enter. Escape closes them.
- One Live / Paused toggle, copy and CSV export.
- Ctrl+K or Ctrl+F focuses search. Ctrl+R refreshes the selected tab.
- Minimum window size: 640 × 480; controls wrap on narrow windows.

## Local and SSH hosts

The Hosts sidebar selects Local host or a saved SSH profile. Add one with **+ SSH
host**, then enter its name/address, SSH username, port and authentication method.
Choose Password or SSH key/agent; an optional private-key file can be selected.
Password and encrypted-key passphrase dialogs appear when SSH requests them.
For password authentication, check **Remember password in desktop keyring** to reuse
the password on reconnect. **Edit host → Forget saved password** removes it.
This optional feature uses libsecret (`gir1.2-secret-1`) and your desktop Secret
Service keyring (such as GNOME Keyring on Mint); it has no plaintext fallback.
A locked keyring may ask you to unlock it. Rejected cached passwords are removed
before prompting again. Passphrases, verification codes and sudo passwords are not saved.
Profiles save connection details and the key filename, never passwords, passphrases
or key contents. Reconnect retries authentication; Disconnect returns to Local.
The Hosts button collapses the sidebar when you need more table space.

System logs, Network, Overview and Maintenance use the selected host. Log Live,
search/filters, network Live/Pause, process lookup, copy/export, colors, resizing
and saved widths stay available. Remote network snapshots use the server's ip/ss;
Overview runs its collector there. Remote log browsing/rotation uses remote paths.
The selected host is always shown above the tabs. Maintenance confirmations name
the exact target. Administrator operations use local pkexec or remote sudo/root;
remote sudo credentials are passed through stdin and never saved.

The client uses OpenSSH, one private multiplexed session per active host and no
agent/X11/port forwarding. Unknown host fingerprints require explicit trust;
changed keys are rejected. Normal SSH known-host/config rules apply. Switching
hosts destroys the previous pages/history, closes its live readers/session and
ignores late callbacks. Switching/disconnecting/closing is blocked during a
maintenance action. Saved remote profiles never auto-connect at startup.

Remote prerequisites depend on the feature:

- SSH server and a usable shell for connection/command execution.
- systemd journalctl and journal access for System logs (non-systemd text-log
  fallback is not implemented).
- iproute2 ip/ss for Network.
- Python 3.8+ for Overview and logrotate configuration helpers.
- The relevant maintenance tools; sudo permission or root login for changes.
  APT/dpkg actions apply only where those commands exist. Missing features report
  Unavailable or disable the relevant action; nothing falls back to local data.

Remote snapshots are bounded and command channels reuse the authenticated session.
No software is installed on the server. Read-only commands have time/output limits;
administrative commands have no arbitrary timeout. An SSH failure during an
administrative operation can leave it running remotely: inspect the server before
retrying. Raw remote journal snapshots have a 16 MiB output limit and fail explicitly
if exceeded. Displayed journal times use the client's local timezone.

## Compact rows and sorting

Rows use reduced padding while keeping the same readable monospace font. Today’s
log entries show just the clock; older entries include a date. Full timestamps
remain in tooltips, event details and exports. Messages still wrap with the window.

Drag table header dividers in System logs, Network or Overview to resize columns.
Manual widths survive window resizes, data refreshes and app restarts; text
rewraps with the columns. Window size and maximized state are saved on close.
Each tab remembers its own manual widths, including tabs not opened this run.
⋯ → Fit columns clears that tab’s saved overrides and restores automatic fitting. Manual widths may use
horizontal scrolling. The Overview logo divider is draggable too.

Click a sortable table header to sort and click again to reverse it. Logs open oldest
first (newest last), use full dates and microsecond journal timestamps for chronological order,
and sort severity by journal priority (Emergency through Debug). Source and
message sorting are case-insensitive and treat embedded numbers numerically.
Enabling Live restores ascending Time order and jumps to the newest entry.
Live auto-scroll follows the newest entry only while sorted by Time; other sorts
stay in place for inspection. Rolling history eviction works with every sort.

Network address and port columns sort independently by numeric IPv4/IPv6 address
and numeric port. State
sorting groups established connections, listeners, handshakes, closing states and
unconnected sockets, with stable numeric endpoint ties. The chosen sort survives
refresh and Live updates. PIDs and process names have separate columns; Copy socket retains
the original process information. Interfaces/routes are in a collapsed expander
to leave more room for sockets. Sort-key caches have bounded sizes.

## Network

The Network page is created only when first opened. It reads local interfaces,
IPv4/IPv6 addresses, default routes and TCP/UDP sockets using `ip` and `ss`.
Network opens with **Live**, **Connections** and **Process details: Basic** selected.
Live refreshes approximately every 2 seconds while Network is visible. The Live / Paused
button freezes or resumes collection. Switching away suspends automatic reads, and reopening resumes them.
Refresh still performs one explicit read while paused. Search and connection/listener filters
operate locally; columns can be sorted, endpoints wrap on resize, and selected
sockets can be copied. Ctrl+K/Ctrl+F and Ctrl+R work on the selected tab.

Hide TIME-WAIT hides closed TCP connections awaiting expiry. It is off by default,
filters already loaded data without an extra scan, and stays applied across Refresh
and Live updates while the app is open. Uncheck it to restore the rows. It combines
with search and socket-type filters; the status still reports shown/loaded counts.

Both address columns fit the first loaded snapshot to keep each port nearby; spare
space stays after the data. Widths remain steady between refreshes, with new values
wrapping as needed. Resize the window, change process mode or use ⋯ → Fit columns
to fit again. Long values still wrap on small windows. Manual column widths take precedence.
PID/Process columns start hidden until process data has been requested and loaded.

The Network table uses Proto, State, Local address, Local port, Remote address,
Remote port, Process and PID columns. Flat headers explicitly identify each
Local/Remote address and port. Process and PID stay together at the end;
all column headers and values align left, including wrapped text. All eight columns fit at the minimum 640-pixel window width
without horizontal scrolling in automatic fit mode. Long values wrap like log messages. PIDs sort
numerically and process names have their own column. Copy socket follows this
visual order and retains full metadata. Ports are amber, process
names are purple and PIDs are blue. Full metadata remains on hover and copy.
Resizing reflows are debounced, and address/port sorting remains numeric.

Process details has Off / Basic / Extended options. Basic is the default. Off skips
process collection. Choose Basic or Extended, then Refresh to collect accessible
PID/process information. Switching Basic/Extended on an already loaded process
snapshot only changes the display, preserving selection and sort. Extended shows
full socket process metadata, including file descriptors. Off hides Process/PID
immediately and omits process collection from subsequent snapshots.
Permissions may hide processes owned by other
users. Queries use numeric endpoints, never DNS resolution, ping or remote probes.
UNKNOWN interface operational state is displayed as UNKNOWN, including on tunnels
and loopback, rather than interpreted as a failed connection.

The Live timer is removed when paused, hidden or disabled. Reads never overlap,
errors trigger backoff (up to 30 seconds), and unchanged tables are not rebuilt.
There are no animated traffic graphs. Each command has
a 3-second timeout and a 512 KiB output budget. Snapshots retain at most 1000 sockets,
128 interfaces and 32 default routes per address family; limits and failures are
shown explicitly. Refreshing does not overlap an existing network read. Existing
journal Live following continues if you enabled it, even with Network selected.

The Network palette follows log levels: blue for active connections, purple for
listeners/handshakes, gray for idle/closing sockets and amber for CLOSE-WAIT.
Ordinary host values use quieter text colors. Ports use amber, process names
purple, and PIDs blue as field categories, rather than health indicators. Interface UP is blue; an administratively up link reporting DOWN is red;
DORMANT is amber and administrative DOWN/UNKNOWN is gray. These describe state,
not the result of connectivity tests.

## Overview and Maintenance

Overview reads a local snapshot once when first opened, then only on Refresh.
It shows host, OS/kernel, uptime, CPU model/count, 1/5/15-minute load averages,
memory, swap and root filesystem space. Load is not a CPU percentage. Missing
readings explicitly say Unavailable. Values wrap to fit and can be copied.
The neofetch-style printout uses a built-in colored ASCII logo and adjustable
Field/Value columns; neofetch is not installed or executed. No process scan,
journal scan, external command or recurring sampling is used.

Maintenance groups actions into Diagnostics, Cleanup, Services and Text log rotation.
NetworkManager restart and pending package configuration are under collapsed
**Advanced · Services and Packages** groups. Every action names its target host.
Unavailable commands have inline explanations; non-APT hosts retain the other
features. Remote network restart prominently warns that SSH may disconnect.

Journal cleanup supports retention by age (days) or storage target (MiB). Choosing
Vacuum journal first reads current journal usage, then shows the target, usage and
proposed policy before confirmation. Active journal files are retained, so a size
target may not be reached; no exact reclaim estimate is claimed.

Nothing runs automatically. Changes require confirmation, then local pkexec or
remote sudo/root authentication. A PolicyKit agent is needed for local administrator
actions. Administrative operations have no fixed runtime timeout; keep the app
open until completion. Closing or switching hosts is blocked during an action.
Interactive package repair belongs in a terminal.

A separate worker streams command output to a resizable lower pane, coalescing GUI
updates. Commands may buffer their own output. Elapsed time updates once per second
only while an action runs; final status includes host and exit code. The backend
retains the last 128 KiB; the live view holds at most 128K characters. No growing
temporary output file is used by the interactive streaming path. Read-only usage
checks have a five-second deadline. The timer stops at completion.

The output **⋯** menu offers Copy, Save output and Clear. Save writes the displayed
output to a user-chosen file on this computer, including for remote actions. Clear
is disabled while running. Select text normally with the mouse or Ctrl+A/Ctrl+C.
The history selector keeps the last ten results across host switches for this app
session, including action, target, start time, duration, exit code and a bounded
32K-character output tail. History is not written to disk automatically; Clear
output retains history, and exiting the app clears the session.

F5, Ctrl+R or Refresh availability rechecks command availability on the selected
host; it never performs a maintenance change.

## Text log rotation

Expand Text log rotation configuration in Maintenance to manage one custom file
under `/var/log`. Choose daily/weekly/monthly, archive count, compression,
optional max size in MiB and rename or copy/truncate. Rename requires the writer
to reopen its log; no reopen hook is added. Copy/truncate can lose writes during
copying. Size and schedule are evaluated by the system logrotate timer/cron job.

The editor shows a plain-language summary and generated configuration preview.
**Validate only** checks the staged full configuration in logrotate debug mode,
with administrator authentication to read protected rules. It does not write the
profile, backups, logrotate state or logs. **Review and save** separately shows the
exact configuration before administrator authentication.
Only `/etc/logrotate.d/syslogapp` is managed. Existing app-generated settings load
into the editor; previous versions are backed up in `/var/backups/syslogapp/`.
The helper stages the full configuration and runs logrotate in debug mode before
an atomic save, rejecting duplicate rules and validation failures without changes.
Distro-owned rules are left untouched. Unsupported main configuration layouts are
reported. Missing logrotate/pkexec disables saving. Saving never rotates logs.

## Cinnamon taskbar icon

The optional `syslogapp@razor` panel applet provides a custom log-lines-and-network-nodes icon that launches
or focuses SysLogApp. On Mint/Cinnamon, explicitly install and enable it with:

```bash
/usr/bin/python3 scripts/install_mint_desktop.py
```

This installs the current workspace, backs up the previous installation and panel
settings, and adds one applet if it is not already enabled. The ordinary installer
and Debian package do not change panel preferences.

## Performance checks

Table updates retain unchanged socket rows and selection. Sorting reads only the
fields needed to determine order. Long messages and socket process strings bypass
sort caches so evicted records are not kept alive there. No message is truncated.
Date parsing uses a bounded cache and terminal palettes are reused across cells.

See [PERFORMANCE.md](PERFORMANCE.md) for local synthetic before/after results.
Reproduce UI timings on a GTK desktop with `/usr/bin/python3 scripts/benchmark_ui.py`;
`--profile` adds profiling overhead. `--large-cache` checks retained cache memory
without GTK. Benchmarks use synthetic rows and never change system settings.

## Resource use

The viewer loads one snapshot at startup. There are **no repeating refresh timers**
in snapshot mode. Live uses one blocking `journalctl --follow` reader, waking the
GTK UI only when records arrive. Records are delivered in batches at most once per
100 ms, with one scroll/status update per batch. A quiet live stream has no update
timer running. GTK3 renders the visible table rows without browser/webview overhead,
custom graphs, animation or shadows. Message wrapping is recalculated in a
debounced pass after resizing, not through periodic polling.

History and the pending live queue each hold at most `log_lines` records (400 by
default, clamped to 100–2000). If incoming events overflow the live queue, the oldest
pending events are discarded and the status reports the skipped count. The system
journal is untouched: reload or use journalctl to investigate older records. This
is a bounded viewer, not a lossless log recorder. Memory also depends on record size.
Paused stops the journal follower and keeps displayed rows still. Live resumes from the last cursor when available.

Only fields used by the viewer are requested from journalctl. There is no psutil,
Cairo drawing, network probing or telemetry. Elevation is used only for explicitly
confirmed maintenance actions. Normal GTK
and desktop compositor rendering still uses resources; actual CPU/GPU/power usage
depends on the desktop, log rate and hardware.

## Run and install

On Linux Mint / Ubuntu / Debian:

```bash
sudo apt install python3 python3-gi gir1.2-gtk-3.0 systemd iproute2 openssh-client
bash ./run-preview.sh
```

For a per-user installation or upgrade:

```bash
bash ./install.sh
syslogapp
```

The existing launcher and optional Cinnamon applet continue opening SysLogApp.
Source upgrades preserve settings and retain the previous app for rollback.
The app runs as your normal user; SSH commands run as the configured SSH user.
Journal visibility depends on that user’s permissions;
errors and restricted access are reported rather than shown as an empty success.

Settings are stored in `~/.config/syslogapp/config.json`. Window size, maximized
state and manual widths in Logs, Network and Overview are saved atomically on
normal close, with no recurring writes while resizing. Automatic widths keep
adapting to the window unless you drag a divider. Saved window sizes are limited
to the current display’s work area when reopening. Optional history setting:

```json
{"log_lines": 400}
```

Old theme, dashboard and start-page preferences are ignored. The terminal design
always uses a dark palette. No shell commands can be entered into this viewer.

## Validate and package

```bash
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 scripts/build_release.py
```

GTK interaction tests need access to a desktop display; they are explicitly skipped
without one. Packages and the source archive are generated in `dist/preview48/`.
See RELEASE.md for installation and validation scope. Generated files and old-page
backups are excluded from the repository.

Readout selection and copy controls (all hosts):

- Drag over text and continue across columns and rows to select the characters and lines you want. Ctrl+C or right-click Copy selected text copies the range. Ctrl+A selects all shown text. Double-click selects a word; triple-click selects a row. Text stays visible and read-only; no cell editor or separate window is used. Esc clears text selection.
- Right-click a row to copy a cell, row, or all shown rows. Select all shown text selects the entire visible table in place. Exports follow the current sorting, filters and visible columns. System logs retain service/severity filter shortcuts.
- Overview text, interface summaries, status labels, Help and Maintenance output support native mouse selection and right-click Copy. Tables, log details, Help and Maintenance output also support Ctrl+A / Ctrl+C.
- Drag selection pauses Live in System logs and Network; F7 resumes. Log history remains bounded. Table selection uses native text highlights and two row references, without extra widgets or duplicated readout buffers.
- Network and Overview keep the previous completed status during refresh; readouts have extra space at the bottom.

Open **Help** with **F1** for the full guide. Main shortcuts: **F5** refresh, **Ctrl+F** search, **F6** Live on/off, **F7** pause/resume, **Ctrl+1–5** choose a tab, **Ctrl+B** show/hide hosts, **Ctrl+C** copy selected text, **Esc** finish selection/close details. Existing Ctrl+R and Ctrl+K aliases remain available. Shortcuts work on local and SSH hosts; none executes a maintenance action or opens a connection.

Toolbars use two compact groups: wrapping primary controls and a search row that
expands with the window. System logs and Network each have one **Live / Paused** toggle (F6 or F7). Green means active
Live and amber means paused. Export logs and Fit columns are under **⋯**; Network
Copy selected socket is there too. Ordinary controls keep muted square borders,
monospace text and static icons; there is no new background sampling.
