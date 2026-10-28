# SysLogApp 2.0.0 Alpha 1

**Early testing release**, based on Preview 70. Tested locally on Linux Mint 22.3;
Ubuntu, Debian and Fedora still need native validation. See
[compatibility and validation scope](COMPATIBILITY.md).

[Download Alpha 1](https://github.com/razor11-p21/SysLogApp/releases/tag/v2.0.0-alpha.1)
· [Watch the 31-second showcase](https://youtu.be/QMs4t9-B8qw)
· [Report an issue](https://github.com/razor11-p21/SysLogApp/issues)

### Quick install (Debian-family desktop)

Download `syslogapp_2.0.0-alpha1-1_all.deb` from the release, then run:

```bash
sudo apt install ./syslogapp_2.0.0-alpha1-1_all.deb
syslogapp
```

The Cinnamon applet package is optional. Source installation instructions are below.
Verify downloads with `sha256sum -c SHA256SUMS` in the directory containing all
release assets. Prior private preview .deb versions sort after this alpha in
Debian version ordering; source/per-user upgrades are the simplest transition
from those previews. The release does not automatically replace a per-user install.

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
without one. Packages and the source archive are generated in `dist/alpha1/`.
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


### Preview 49: journal history and resource budgets

Use **History…** in System logs for time-range and optional literal message search
on the selected host. It runs only when submitted. **Previous Boot** selects the
preceding boot; **Older** replaces the current bounded page with earlier matching
entries. **Live** returns to recent entries; **⋯ → Return to recent logs** clears
the historical range. Custom dates use this computer's local timezone, converted
to absolute timestamps for SSH. Message search needs journalctl --grep support
(systemd 237+); the existing search box still filters only loaded entries.

Local and SSH journal snapshots share a 16 MiB capture budget. Entries above
64 KiB are omitted with a visible count. Retained history and the live inbox each
have a 4 MiB serialized-data budget plus the existing entry-count limit. These
limits do not represent total process RAM; Python and GTK add overhead. Original
journal entries are unchanged. Narrow the filters/range if a snapshot exceeds its
capture limit. Live reads recover after oversized entries without buffering them.

Network automatic socket updates remain at two seconds while visible. Interfaces
and routes are cached for 30 seconds per page/host, with their collection timestamp
shown separately. Manual Refresh always reads all components. Hidden tabs do not
poll, and existing failure backoff still applies.


### Preview 50: stale connections remain visible

If a local or SSH socket read fails, Network retains the last successful connection
list, process metadata and timestamp. An amber **Stale connections** status shows
the last successful update and the collection error. Filters, selection and copy
continue working on these retained rows. Interfaces/routes may update separately;
their newer timestamp does not make retained connections appear fresh.

A first failed read shows **Connections unavailable**. A successful empty read
clears the table normally, and any successful socket read clears the stale warning.
Existing retry backoff and hidden-tab pause are unchanged; no extra polling is added.


### Preview 51: saved views and event bookmarks

In System logs or Network, use **⋯ → Save view…** to name the current filters,
and **⋯ → Saved views & bookmarks…** to apply or remove saved items. Views are
scoped to the local host or SSH username/address/port and to their tab. Applying a
view pauses Live. Saved log date ranges stay fixed; Older page positions are not
saved. Network views filter loaded sockets without a scan; Refresh collects newly
requested process details. Saving the same name replaces that host/tab's view.

Right-click a System logs event → **Bookmark event…**, or select an event and use
**⋯ → Bookmark selected event…**. The bookmark keeps its name, host, timestamp,
service, severity, journal cursor/boot ID and up to 8 KiB of original multiline
message text. Longer text is clearly labelled as an excerpt. Bookmarking the same
event updates its name. The manager supports Copy saved event and Remove.
**Locate event** reads the exact journal reference on demand; if it has rotated,
the saved text remains available. Opening the manager makes no remote query.

Saved investigations live in `~/.config/syslogapp/investigations.json`, written
atomically with user-only file permissions, separately from credentials/settings.
There are global limits of 100 views, 100 bookmarks and 1 MiB of stored data; no
silent eviction occurs. Corrupt/unsupported data is left unchanged. Saved items
remain local even for SSH hosts; no background monitoring is added.


### Preview 52: connection owners and related service logs

In Network, right-click a connection → **Process details…** or **Related service
logs…**. These actions are also in ⋯. Inspection pauses Network and opens a static,
selectable dialog; it adds no polling. Select a PID/descriptor if several processes
share the socket. The process tab shows executable, command, working directory,
UID, parent PID, memory, state and associated systemd unit. Refresh details repeats
the on-demand inspection. Copy shown text copies the active readout; normal mouse
selection and native Copy also work.

Before displaying details, the probe checks that the current descriptor is a
socket whose inode and endpoints match the selected row, and rechecks process
start ticks and the descriptor afterward. Stale, exited or inaccessible owners
show an explicit error instead of displaying an unrelated PID's details. Inspection
reads bounded /proc data for only the chosen PID. IPv4/IPv6 TCP and UDP are supported.
No sudo, process control, DNS lookup or background process scan is introduced.

The **Service logs** tab reads up to 400 bounded journal entries only when opened.
The exact unit and boot ID constrain the query; user units additionally match the
owner UID. Rows retain multiline messages, severity colors and selectable text.
A process without a systemd unit, unreadable ownership or unavailable journal is
reported clearly. There is no guessed service association from a process name.

The same standalone probe runs over the active SSH session, with bounded output
and an eight-second remote timeout. Remote inspection needs Python 3.8+ and readable
/proc data; related logs additionally need journalctl and suitable permissions.
Closed/TIME-WAIT sockets often have no visible owner. Choose Basic or Extended and
Refresh to collect process ownership when it is missing from the loaded snapshot.


### Preview 53: previewed JSONL and spreadsheet-safe CSV exports

Use **System logs → ⋯ → Export logs…** or **Network → ⋯ → Export connections…**.
The action pauses Live and freezes currently displayed entries in their current
sort order, without another host query. Choose all filtered loaded entries or the
selected entries. A mouse selection across several rows exports those whole rows,
including original multiline log messages, not just the highlighted characters.

JSONL begins with a metadata record followed by event/socket records. With redaction
off, it preserves every collected raw field (including journal cursors/binary values
or socket queue counts). Collection itself requests a subset of journal fields;
export does not retrieve additional fields or entries. Metadata includes source
host/user/SSH port, version, export timestamp/timezone, active filters, selection,
counts and stale/limited-data status. Journal entries also have time_iso with their
own historical UTC offset, so daylight-saving changes remain unambiguous.

CSV includes context columns and multiline messages. All cells are quoted, and
formula-like values receive an apostrophe prefix to reduce spreadsheet formula
interpretation, including leading whitespace/control characters. This can change
cell text; use unredacted JSONL for fidelity. Spreadsheet applications differ, so
do not assume the mitigation survives editing/re-saving in another application.

Optional redaction replaces recognizable IP addresses, source/context usernames,
known/context hostnames and domain-like names with consistent placeholders. You
can also supply up to 32 literal custom values. This is best effort, not a guarantee
of anonymity: encoded identifiers and unfamiliar free-text names can remain, and
some domain-like application identifiers may be replaced. Inspect the preview
before sharing. Binary fields are explicitly omitted when redaction is enabled;
the original collected data is never modified and alias mappings are not exported.

Click **Preview export** before Save. Preview pages hold at most 32,768 characters
and expose the entire generated file via Previous/Next. Changing options invalidates
the preview and disables saving until regenerated. Rendering runs off the GTK
thread with a 32 MiB output limit and 10,000-placeholder limit. Files are saved
atomically with user-only permissions; cancellation or failure preserves existing
files. Exports remain local, including SSH-host exports, with no new background work.


### Preview 54: Overview filesystems, failed services and reboot notices

Overview keeps its selectable terminal summary and manual Refresh. It now lists
mounted filesystems visible to the selected local or SSH host, with source/type,
used percentage, used/total bytes, available space and read-only state. Small
filesystems use MiB/KiB rather than rounding to zero GiB. Root usage remains in the
summary. **Virtual mounts** shows already-collected kernel mounts without a scan;
these report usage as not applicable rather than zero/healthy.

Network/FUSE mounts are listed but not contacted by default. Enable **Network/FUSE
on Refresh** and press Refresh to include their usage. Usage reads run in a separate
helper with a three-second caller budget, with local mounts checked first. Completed
results remain usable if a later check times out; unchecked/unavailable mounts are
labelled individually. Repeated bind mounts of the same filesystem/root reuse one
statvfs result. Lists are bounded to 128 retained mounts, with limits shown explicitly.
Mount information comes from [the kernel mountinfo interface](https://docs.kernel.org/filesystems/proc.html).

Failed system services are collected with a bounded, read-only systemctl query.
Select a **Service · …** row and press **Show service logs**, Enter, or right-click
**Show service logs** to open the matching unit in the current host's System logs.
Missing systemctl, inaccessible managers and command failures show Unavailable;
only a successful empty read says no failed services reported. Lists are bounded
to 128 services. No service is restarted or changed by Overview.

Reboot notices follow the [Ubuntu reboot-required marker](https://wiki.ubuntu.com/UpdateNotifier),
including Mint/Debian-family systems that provide it. Marker absence is labelled
as no notice reported, not proof that no reboot is needed. Unsupported indicators
or unreadable checks show Unavailable. No package scan or reboot command is run.

The same collector source runs over SSH with Python 3.8+, a ten-second outer capture
budget and a 256 KiB result limit. Snapshot errors retain the previous view and its
timestamp. New checks run on opening Overview or explicit Refresh, with no recurring
polling. Existing window/column preferences and snapshot copy remain available.


### Preview 55: SSH reliability and terminal controls

Reconnect the same host to retain tabs, filters, columns and loaded rows. Disconnected
snapshots remain visibly stale until refreshed; maintenance actions are never
repeated automatically. New remembered SSH passwords reach the keyring only after
successful authentication and capability checks. Idle master exit detection uses
Linux pidfd when available; older kernels detect loss on failed reads.

Choose Log limit (default 400, maximum 2000); it is remembered on close. Byte limits
still apply. Table scrollbars reserve space, and tooltips match the terminal theme.


### Preview 56: pointer-following tooltips

Hover boxes follow the pointer while visible, keep the terminal theme, and stay
within the monitor work area. Tracking uses mouse events with no polling timer or
input grab. Keyboard hints keep native positioning. Long hover previews are bounded;
full details remain available in event details and exports.


### Preview 57: native tooltip behavior restored

Tooltips wait for the normal GTK hover delay and use the original native
positioning and dismissal. The terminal colors remain. Preview 56's custom
pointer-following tooltip windows have been removed.


### Preview 58: original hover hints

Tooltip-specific styling has been removed. Hover hints use the original appearance
and native GTK behavior, including the normal delay before appearing.


### Preview 59: no hover info boxes

Hover info boxes have been removed throughout the application. Help and event
details remain available through their normal controls.


### Preview 60: stationary log previews

Keep the pointer still over a System logs row for three seconds to see a themed
preview. Moving the pointer dismisses it immediately. Clicking, scrolling, leaving
or switching tabs cancels the preview. This applies to local and remote logs;
other tabs and controls have no hover boxes.


### Preview 61: two-second hover delay

Log previews now appear after two seconds stationary. Pointer movement still hides
them immediately.


### Preview 62: resource and reliability review

Fixes retained GTK page callbacks during host changes, diagnostic descendant
cleanup, SSH descriptor cleanup and malformed journal field handling. Large network
updates sort once; sparse updates retain stable rows and selection. The two-second
log hover behavior remains. See PERFORMANCE.md for measured scope and limitations.


### Preview 63: horizontal resizing

Window and column-divider drags defer repeated text wrapping until a brief pause.
The final layout still wraps normally and manual widths are remembered immediately.
Redundant renderer style/text changes and full-viewport repaints are reduced.


### Preview 64: calmer Overview

Overview starts with six essential fields, the terminal logo and a compact notice
line. Expand System details for the full resizable table, mounted filesystems and
service logs. Copy snapshot includes all collected details. Collection remains
first-open/manual on both local and SSH hosts.


### Preview 65: clearer memory figures

Overview shows available RAM / total RAM for the selected host. System details
separates estimated RAM use, available RAM and occupied swap, with scope and meaning
explained. Swap occupancy is not a current activity measurement. Disabled and
unavailable swap are distinct. The existing single memory read is reused.


### Preview 66: connection troubleshooting filters

Expand Connection filters in Network to filter loaded rows by application name,
exact PID or exact local/remote/either port. Select a connection for Process details
or Related logs. App/PID filters depend on collected owner visibility; select Basic
or Extended and Refresh if needed. Filtering itself issues no new command. Saved
views and export metadata preserve these criteria on local and SSH hosts.

## Release verification

See [COMPATIBILITY.md](COMPATIBILITY.md) for the tested environment, SSH coverage,
Fedora installation prerequisites and outstanding native distro checks. Preview 67
adds distro-aware dependency guidance and a staged release integrity checker.
Other distributions are not marked tested based on Mint results.

## Journal read failures — Preview 68

Remote journal snapshots preserve stderr and use the same restricted-access checks
as local reads. A failed refresh keeps displayed entries and marks them stale.
The status shows the last successful read time; export metadata includes stale
state, the read error and an ISO timestamp. Successful refreshes (including empty
results) or received live events clear the read error. Unexpected live stops and
failed live starts also mark retained entries stale. No polling or queries were added.

## Display filtering and hidden-tab efficiency — Preview 69

System logs → Display filters offers exact service/source exclusions, a literal
case-insensitive message exclusion, and optional consecutive-repeat grouping.
Right-click Hide This Service/Message fills the filters. Clearing them restores
loaded events without another query. Saved views retain these settings per host.
Groups display [×N]; details list all original timestamps/messages, and exports
expand every group into its original events. Selecting a grouped row for export
includes every member. Copy Event includes every member; bookmarking uses the
first event. Distinct process/boot/user/invocation identities never combine.

Hidden System logs tabs retain bounded live history and defer GTK model updates
and wrapping until mapped again. The old model is cleared once on hiding to
release expired event references. Returning rebuilds it once without a host query.
The same behavior applies to SSH hosts. Grouping is off by default.

## Failed settings saves — Preview 70

A settings-save failure during normal close keeps the app open and shows the
error. Retry saves the current layout/settings again. Keep open (or dismissing
the dialog) returns to the app with sessions intact. Close without saving exits
without a second write attempt during shutdown. Maintenance still blocks close
while an operation is running.
