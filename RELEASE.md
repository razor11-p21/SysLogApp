# SysLogApp 2.0.0 Alpha 1

First public alpha, tagged `v2.0.0-alpha.1`, based on Preview 70. Runtime behavior
is unchanged from Preview 70; version labels, packaging and public release
information are updated. The source is GPL-3.0-or-later.

Validation: all 310 regression tests passed with GTK and strict resource warnings
under a hard 1 GiB per-process address-space limit. The main and optional applet
packages and source archive pass the staged release checker.

Downloads include the main .deb, optional Cinnamon applet .deb, clean source
archive and SHA256SUMS. Local settings, SSH profiles/credentials, captured logs,
backup folders and showcase work files are excluded.

See COMPATIBILITY.md for actual coverage and outstanding native distro/SSH
password/keyring checks. This is an early testing release, not a stable release.

## Preview 70 — visible settings-save failures

Normal close now waits for a successful settings save or an explicit choice to
close without saving. Failed saves show a modal error with Retry, Keep open and
Close without saving. Dismissing the dialog keeps the app open. Retry captures
the latest settings again; repeated failures show the updated error. SSH sessions
and readers are left running while close is canceled. Closing without saving
skips the shutdown fallback write. Reentrant close requests do not duplicate the
prompt, and running maintenance continues to block close.

Validation: all 310 regression tests passed with GTK and strict resource warnings.
The close test includes six isolated GTK scenarios covering retry, repeated
failure, keeping open, dialog dismissal, explicit discard without a fallback write,
maintenance/reentrancy guards and real modal dialog buttons/default response.

## Preview 69 — quieter log views and hidden-tab efficiency

Hidden System logs tabs keep bounded live collection but defer model/filter/wrap
work until shown. Hiding releases old GTK model references; returning rebuilds
once from retained history without reloading the host. Paused tabs restore their
scroll position; Live tabs follow the latest retained entry.

A collapsed Display filters section offers exact service/source exclusions, a
literal case-insensitive message exclusion and optional consecutive-repeat groups.
Right-click shortcuts fill exclusions; clearing restores retained events. Grouping
is off by default and respects source, severity, message, boot, PID, UID and service
invocation. Intervening hidden events break runs. Stable group rows update in place
as new events arrive. Group details and Copy Event expose original members.
Saved views retain display options; exports expand original events, including all
members of selected groups. Bookmarking a group stores its first event.

Validation: all 309 tests passed with GTK and strict resource warnings, including
hidden/visible transitions, model inactivity while hidden, row/byte limits, expired
reference cleanup, local/remote behavior, filter reversibility, group identities,
stable live group rows, original-preserving selected exports, sorting and saved
views. Synthetic 480/1000-pixel layouts were visually checked. See PERFORMANCE.md
for the bounded synthetic benchmark and its limitations.

## Preview 68 — trustworthy journal read status

SSH journal snapshots preserve successful-command stderr, so restricted-access
warnings produce the same unavailable result as local journal queries. Other SSH
capture callers retain the existing two-value response by default.

Failed log refreshes retain the displayed rows and show stale status plus the
last successful read time. Exports include stale state, error and full timestamp.
Successful empty snapshots and received live batches clear read failures. Failed
live starts and unexpected live stops mark retained data stale. An obsolete
history failure cannot overwrite the status of an active live feed. No additional
query, timer or background worker is introduced.

Validation: all 292 tests passed with GTK and strict resource warnings. New
coverage includes local/remote permission-warning parity, retained rows and export
staleness after failure, successful empty recovery, obsolete history callbacks,
live startup/exit failures and live recovery. The disposable loopback SSH check
confirmed successful-command stderr preservation without resource warnings.

## Preview 67 — release readiness audit

The installer now gives dependency guidance using the detected distro family,
including Fedora package names and a generic fallback. Release archives include
COMPATIBILITY.md with explicit tested/pending coverage. A new check_release.py
checks staged Debian packages and source archive integrity without installation.
Changelog lines are wrapped and the loopback SSH fixture closes its live stream.
New tests cover clean installation followed by two upgrades, retained settings
and backups, dependency hints and Debian/Fedora remote capability scenarios.
No monitoring timer, host query or runtime dependency was added.

Validation on Mint 22.3: all 280 GTK/unit tests passed with strict resource
warnings. The isolated OpenSSH integration check also passed without resource
warnings. Other distributions and successful real password login remain pending;
see COMPATIBILITY.md for the exact scope.

## Preview 66 — connection troubleshooting filters

Network adds a collapsed Connection filters section with a literal, case-insensitive
application-name filter, exact PID and exact port. Ports can match either endpoint,
local only or remote only. Filters combine with loaded text search, connection type
and Hide TIME-WAIT. Their active count stays visible when collapsed. Invalid numeric
input is explained rather than silently ignored. Clear fields resets these criteria.

App/PID filtering uses collected process owners and reports when owner data needs
Basic/Extended plus Refresh. Shared sockets require app and PID to match the same
owner. Port filters work without process visibility. Small owner parses are cached
only in their bounded loaded row, and invalidated if raw process metadata changes.
No /proc scan, DNS lookup, network command or SSH request runs to apply a filter.

Select a connection to enable direct Process details and Related logs buttons.
They use the existing on-demand ownership verification and boot/unit-scoped log
reader on the selected local or SSH host. Opening pauses Network Live; no automatic
process-details/log polling is added. Existing context and more-menu actions remain.
Saved Network views and export metadata retain app/PID/port/endpoint-side criteria;
older saved views default to empty criteria.

Validation: all 276 tests passed with GTK and strict resource warnings. Coverage
includes exact matching, shared-owner consistency, filtering without queries,
saved views, export metadata and remote-host inspection routing. Synthetic narrow
and wide layouts were visually checked.

## Preview 65 — clearer memory figures

The compact Overview now shows available RAM / total RAM. A visible scope note
identifies memory as belonging to the selected host, not SysLogApp. System details
separates estimated RAM use, available RAM and swap occupancy. Used RAM is explicitly
an estimate based on total minus MemAvailable. Available includes memory the kernel
expects can be reclaimed for applications. Occupied swap is labelled as stored data,
not a current activity rate; occupancy alone does not produce an alert.

No configured swap shows Disabled; missing, invalid or inconsistent data shows
Unavailable. RAM and swap failures are handled independently, preserving whichever
check succeeded. One existing /proc/meminfo read supplies the typed snapshot data
on both local and remote hosts. The compact layout, manual refresh and no-polling
behavior remain. Full snapshot copying includes the scope and interpretation note.

Validation: all 264 tests passed with GTK and strict resource warnings. Coverage
includes available-versus-free RAM, disabled/missing/invalid swap, independent
partial failures, one memory read, snapshot labels, summary scope and no false
swap-activity alert. Synthetic narrow/wide layouts were visually checked.

Memory interpretation follows the [Linux kernel meminfo documentation](https://docs.kernel.org/filesystems/proc.html#meminfo).

## Preview 64 — calmer Overview

Overview opens with six essential fields beside the terminal logo: host, system,
uptime, CPU, memory and root disk usage. Values are selectable and wrap in narrow
windows. A short notice line keeps failed services, unavailable checks, high disk
usage and reboot requests visible without presenting the entire diagnostic table.
It does not claim universal system health.

The full resizable Field/Value table is under System details, collapsed by default.
Service log navigation, virtual mounts, network/FUSE opt-in and Fit columns live
inside that section. The top toolbar keeps Refresh and Copy snapshot. Copy snapshot
still includes the complete loaded snapshot, including collapsed details. Expanding
performs no command; collection remains first-open/manual, with no new polling.
Local and SSH hosts share the layout and retained/stale snapshot behavior.

Validation: all 256 tests passed with GTK and strict resource warnings. Coverage
includes closed details, full snapshot preservation, visible failure/reboot notices,
service navigation, local virtual filtering and long-value wrapping in a 480-pixel
page. Synthetic 480/860-pixel layouts were visually checked in both detail states.

## Preview 63 — horizontal resizing

Window and column-divider resizing now coalesces wrapped-column updates until
120 ms after the last width change, followed by a 50 ms row-height refresh. Manual
widths are remembered immediately. This avoids repeated rewrapping when drag events
arrive more slowly than the old 60 ms interval. Logs, Network and Overview avoid
repainting their entire native table solely because the viewport width changed;
content and final wrapping still invalidate the necessary rows.

Reused log/network renderers skip unchanged foreground/weight updates, and table
text selection avoids clearing already-empty Pango attributes. Timestamps are
formatted once per cell instead of first binding a canonical string and replacing
it. Colors, wrapping, mouse selection, saved widths and two-second hover previews
remain available.

Three alternating synthetic slow-drag samples per version (1000 wrapped log rows,
42 width steps spaced 80 ms apart) measured median CPU time of 4528.8 ms before and
1150.3 ms after, about 75% less. Median wall time was 4545.3 versus 3871.0 ms, and
the slowest scheduled step was 109.2 versus 89.9 ms. These are offscreen GTK results,
not measurements of real pointer latency or compositor/GPU use; no universal
speedup is claimed.

The fast 16 ms-step comparison also improved: median CPU 354.4 to 265.2 ms.
Validation: all 253 tests passed with GTK and strict resource warnings. Narrow
640-pixel and wide 1050-pixel layouts were visually checked with synthetic colored
logs after resizing. No real app window was moved or resized for these checks.

## Preview 62 — resource and reliability review

Destroyed table pages now release GTK sorting, cell, width, selection and model
callbacks, including nested Overview tables. The repeated lifecycle check creates
and destroys 84 pages: retained page wrappers fell from 63 to zero, with 13 open
file descriptors before and after. This addresses growth across repeated host
changes; it is not a universal RSS ceiling.

Read-only capture now terminates the entire private local process group on timeout
or output-limit failure, including helpers whose parent has already exited. This
does not alter maintenance operation deadlines or retry any remote action.
Failed password-handoff setup closes its socket and removes only an owned path;
failed SSH watcher pipe setup releases its pidfd. Closed SSH sessions ignore late
connection-state notifications. Invalid nonfinite saved SSH ports are skipped
instead of breaking configuration loading.

Historical and live journal parsing now share field normalization. Malformed or
array-valued priorities fall back to Info, source values become safe display text,
and raw journal fields remain intact. Bulk network replacements sort once after
mutation while sparse changes retain incremental row updates, duplicate sockets,
selection and the active sort. The obsolete maintenance focus-chain override was
removed; the window already focuses the current tab's main control.

Three alternating unprofiled synthetic samples per version measured a median
1000-socket load at 75.370 ms CPU before and 66.944 ms after (about 11% less).
Sparse/unchanged refreshes and single-process RSS were essentially unchanged;
these are local synthetic results, not end-to-end or GPU measurements.
The two-second log hover behavior is retained, with additional cleanup for
model/adjustment callbacks and dismissal when its table loses keyboard focus.

Validation: all 252 tests passed with GTK enabled and ResourceWarning treated as
an error. The disposable loopback SSH integration check passed host-key rejection,
key/passphrase authentication, cancellation, collectors, streams and cleanup. No
actual maintenance operation was run. The large-string cache check retained
0.000 MiB after collection (0.111 MiB transient peak).

## Preview 61 — two-second log hover delay

Log previews appear after two seconds stationary instead of three. Moving the
pointer still hides them immediately. The terminal theme and other behavior remain.
Validation: the four GTK hover regression tests passed with the updated delay.

## Preview 60 — stationary log hover previews

System log rows show a terminal-themed info box only after the pointer remains
stationary over a log for three seconds. Any pointer movement hides it immediately
and starts a new three-second wait over a valid row. Leaving, clicking, scrolling,
keyboard input, tab hiding and destruction cancel the preview. Visible previews
are dismissed when their model changes. Local and SSH log tabs use the same code.
Other tabs and controls retain no hover info boxes.

The preview shows timestamp, severity, service and message as literal text, bounded
to 4096 characters and twelve lines. Full details remain available by opening the
event. It uses a dark background, muted green border and readable monospace text,
reserves a gap from the cursor and clamps to screen edges. The popup cannot take
focus and uses no input grab. One one-shot timer runs only while a hover is pending;
there is no pointer polling or continuous timer.

Validation: all 243 regression tests passed with GTK enabled. The four hover tests
also passed after the final click-dismissal adjustment, covering the 3000 ms timer,
movement, selection, cancellation, bounded literal text and cleanup.

## Preview 59 — remove hover info boxes

Removed all application tooltip text, dynamic log/network hover queries and tooltip
activation. This includes table headers, toolbar controls, status labels, host rows,
and Maintenance/Overview options, on both local and remote tabs. No custom hover
popup or tooltip-specific styling remains. Help and click-opened event details
remain available.

Validation: all 239 remaining regression tests passed with GTK enabled.

## Preview 58 — original hover hints restored completely

Removed the tooltip-specific CSS introduced in Preview 55. Hover boxes again use
the original appearance, native GTK delay, positioning and dismissal. The custom
pointer-following implementation remains removed. Other app styling and features
are unchanged. This restores the tooltip setup from before the theming changes.

Validation: all 240 regression tests passed with GTK enabled.

## Preview 57 — restore native hover behavior

Hover hints again use GTK's original hover delay, positioning and dismissal.
The custom pointer-following windows and motion handlers introduced in Preview 56
are removed. Terminal tooltip colors, borders and fonts are retained. Corrected
scrolling-table row hit testing is also retained. Local and remote tabs use the
same native behavior. No custom tooltip timer or desktop setting is added.

Validation: all 241 tests passed with GTK enabled, including native tooltip-window
use, correct hovered-row text and terminal tooltip colors.

## Preview 56 — pointer-following hover boxes

Terminal-themed hover boxes follow pointer motion while visible, with a gap from
the cursor and screen-edge clamping. The same helper covers static control hints
and dynamic System logs/Network readouts on local and remote hosts. Native GTK
still controls hover delays and hiding. Popups cannot take focus, create no input
grabs and use no polling or animation timer. Keyboard hints keep native anchoring.
Widgets release their popup on destruction, including host switches.

Hover previews are limited to 4096 characters and twelve lines; full event details
and exports are unchanged. Table tooltip hit testing now converts widget coordinates
to the scrolling content coordinates so the hovered row matches the shown entry.

Validation: all 243 tests passed with GTK enabled, including popup movement,
non-focusable/no-grab behavior, literal and bounded text, widget cleanup,
monitor-edge positioning and correct log-row hit testing.

## Preview 55 — SSH reliability and terminal controls

SSH shows explicit connection states and offers Reconnect. Reconnecting the same
target retains the current tab, filters, column widths and loaded rows. Disconnect
retains readouts with a persistent stale notice; each successful tab refresh clears
its own notice. Queued reads and late callbacks from the old session are ignored.
Maintenance actions are never retried automatically, and offline actions are blocked.
An interrupted remote operation may still be running; inspect before retrying.

New remembered passwords are held through a private Unix socket and saved in the
desktop keyring only after authentication and capability checks succeed. Rejected
attempts and canceled prompts are discarded. No password file is created.
On Linux with pidfd support, master exit detection blocks on a descriptor instead
of polling. Older kernels detect loss on failed reads. OpenSSH keepalive settings
still govern detection of an unresponsive peer.

System logs adds a remembered Log limit control: default 400, up to 2000 entries.
Existing serialized-byte limits still apply. Log, Network and Overview table
scrollbars reserve layout space instead of overlaying the final row. Hover tooltips
use a dark terminal background, square muted green borders and monospace text,
including popups outside the main window and SSH authentication dialogs.

Validation: all 240 tests passed with GTK enabled, including private password
handoff, failed authentication, master exit detection, stale snapshots, reconnect
state preservation, log limits and computed tooltip colors. A disposable loopback
SSH server also verified authentication, host-key checks, quoting, read-only
collectors, streams and cleanup. No actual maintenance operation was run.

## Preview 54 — on-demand Overview diagnostics

Overview adds visible mounted-filesystem usage, failed system services with links
to their logs, and reboot notices where supported. The terminal summary, selectable
readouts, saved/resizable Field/Value columns and snapshot copy are retained.
There is no recurring poll or background sampling. Refresh coalesces while busy;
late callbacks are ignored, and full failures retain the previous snapshot/time.

Filesystem rows show source/type, percentage, used/total, available space and
read-only state. Virtual mounts are hidden by default and can be shown without a
new read; their capacity is not applicable. Network/FUSE mounts are listed but not
contacted unless explicitly enabled for Refresh. A separate three-second usage
helper preserves completed results and labels timed-out/unattempted checks.
Equivalent bind roots reuse statistics. Mount/service lists are capped at 128,
with explicit list-limit notices and smaller capacity units for small filesystems.

Failed-service checks distinguish successful empty results from unavailable or
malformed reads. Select a failed-service row and use Show service logs, Enter or
its context action to navigate to that unit on the same host. Overview performs
no service-control or privileged operation. Reboot markers report a notice, not a
universal reboot assessment; unsupported/unreadable indicators are Unavailable.

Local and SSH hosts use the same collector source. Remote Overview keeps its
Python 3.8+ requirement, with a ten-second outer budget and 256 KiB output cap.
No dependency, elevated privilege or recurring timer was added.

Validation: all 233 tests passed with GTK enabled. Coverage includes mount parsing,
escaped paths, virtual/network policy, reused bind statistics, partial timeouts,
list limits, failed/empty/unavailable service reads, reboot states, remote capture
budgets, host-scoped log navigation, local virtual filtering, retained snapshots
and late callbacks. The updated terminal layout was visually checked at 1050×700
with synthetic data. Live remote SSH was not used. Reopen the installed app to
load the updated collector and Overview page.

## Preview 53 — selection exports, JSONL, redaction and paged previews

System logs and Network add a preview-before-save workflow for selected entries
or all filtered loaded entries, preserving current order. Dragging text across rows
selects complete entries for export. Opening pauses Live and freezes the shown
snapshot without querying a host. JSONL preserves all collected raw fields when
redaction is off and starts with a metadata record. CSV quotes all cells and
prefixes formula-like cells with an apostrophe, including whitespace/control-led
values. JSONL is the fidelity option; spreadsheet handling can vary.

Source host/user/SSH port, timezone, filters, version, selection, counts and stale
snapshot state accompany exports. Journal time_iso includes the offset at each
event, including historical daylight-saving changes. Optional best-effort IP,
hostname and username redaction and custom literal replacement apply to metadata
and raw fields too. Binary fields are omitted while redacting. Original data is
unchanged; no alias mapping is exported. Review before sharing; redaction cannot
guarantee anonymity for all free-text/encoded identifiers.

Preview generation is explicit and runs off the GTK thread; stale preview results
are discarded. Pages display at most 32,768 characters, with navigation through
the full output. Limits are 32 MiB serialized output, 10,000 aliases and 32 custom
values of up to 256 characters. Option changes require a new preview before Save.
Atomic user-only files, overwrite confirmation and failure cleanup preserve
existing output. No recurring timer, remote query or dependency was introduced.

Validation: all 220 tests passed with GTK enabled, covering raw JSONL fidelity,
CSV formula prefixes/quoting, recursive redaction and source immutability, binary
handling, historical DST offsets, limits, atomic-write failure, selected ranges
and sort order, stale network/queue data, preview invalidation/paging, cancellation
and late callbacks. The terminal preview was visually checked with synthetic
redacted data at 900×650. Reopen the installed app to load the update.

## Preview 52 — on-demand connection and service inspection

Network context/⋯ actions open Process details… or Related service logs… for the
selected connection. Shared sockets expose an explicit PID/descriptor choice.
The terminal-themed dialog has static, selectable process details and a Service
logs tab with severity colors and original multiline messages. Network pauses on
inspection. Process reads and journal reads occur only on explicit action/tab open
or Refresh details; there is no new polling or process-control action.

A bounded /proc probe verifies the descriptor's socket inode and selected endpoints,
then checks process start identity and descriptor again after reading metadata.
This rejects stale ownership and changes during inspection. Optional fields report
permission errors without inventing values. The identical standalone Python probe
runs locally and over SSH. Remote reads have an eight-second/128 KiB output budget;
remote Python 3.8+ and readable /proc data are required.

Related journal queries use an exact system or user unit and the process boot ID,
including UID for user units. They retain existing snapshot/history/record budgets.
Missing units and inaccessible/exited processes are explicit. Late results cannot
update closed dialogs or overwrite a different process selection; rapid owner
changes coalesce while a probe is in flight. No elevated privileges are requested.

Validation: all 205 tests passed with GTK enabled. Coverage includes real IPv4/IPv6
loopback ownership, stale descriptors/endpoints, PID/descriptor changes, bounded
reads, optional permission failures, cgroup v1/v2 unit mapping, SSH command routing,
exact journal fields, demand-only service reads, shared-owner changes, multiline
severity-colored text and late callbacks. The dialog was visually checked with
synthetic data at 800×570. Remote transport was tested with mocks; no live SSH
host was used. Reopen the installed app to load the new modules.

## Preview 51 — saved views and event bookmarks

System logs and Network add ⋯ → Save view… and Saved views & bookmarks….
Views restore current filters for the matching host and tab in Paused mode. Log
history date ranges remain fixed; page cursors and Live state are not restored.
Network views apply to loaded data without polling; Refresh collects changed
process-detail settings. Names replace an existing view on the same host/tab.

System logs adds Bookmark event… to its context menu and a selected-event action
in ⋯. Bookmarks preserve original multiline text up to an explicitly labelled
8 KiB excerpt plus timestamp, host, service, severity, journal cursor and boot ID.
The manager supports saved-text copy, removal and an on-demand Locate event read.
It verifies the exact cursor/boot instead of substituting a nearby event after
rotation. Late reads cannot overwrite another selection or update a closed dialog.

Storage is local, private and atomic, bounded to 100 views, 100 bookmarks and
1 MiB. Limits refuse additional saves rather than silently deleting older items.
Credentials/key paths are excluded; unsupported/corrupt files remain unchanged.
No recurring timer or background query is added. Opening the manager reads only
its local data file. Existing app settings and taskbar launchers are preserved.

Validation: all 187 tests passed with GTK enabled, covering atomic persistence,
storage limits, host/tab isolation, multiline excerpts, cancellation, exact event
lookup, paused filter restore, local-only Network filtering and late callbacks.
An exact-cursor read was verified against the local journal. The saved-items
dialog was visually checked with synthetic data in the terminal theme.

## Preview 50 — retain connections after failed refreshes

Network preserves the last successful socket rows and their process metadata when
ss fails during an otherwise partial snapshot. Full refresh failures retain the
previous snapshot as before, now with an explicit amber Stale connections label
and last successful socket update time. Interface/route updates never advance
that socket timestamp. This shared page behavior applies to local and SSH hosts.

A first failed socket read is shown as Connections unavailable, rather than an
empty successful connection list. A successful empty result clears retained rows;
a subsequent successful read clears stale status and warning color. Existing row
selection, sorting, filters, copy, widths, retry backoff and hidden-tab pause are
preserved. No new command, polling timer or snapshot history was introduced.

Validation: all 173 tests passed with GTK enabled, including partial/full failures,
first-read failure, empty recovery, process metadata, preserved native rows and
selection, independent interface failure and shared SSH-page behavior. Reopen the
installed app to load the update.

## Preview 49 — bounded journal memory, historical search and cheaper Network updates

System logs adds History… for explicit time-range and literal, case-insensitive
message searches on the selected local or SSH host. Choose 15 minutes, one hour,
24 hours, seven days, any time or a custom range. Custom dates use this computer's
local timezone, converted to absolute Unix timestamps before querying the host.
Current Boot, Previous Boot and Recent History constrain the query. Older replaces
the displayed page with preceding matching events using a journal cursor; it does
not accumulate unbounded history. Live returns to recent events. The ordinary
search box continues filtering loaded rows without subprocesses or SSH traffic.
The ⋯ menu offers Return to recent logs. History message matching requires the
host's journalctl to support --grep (systemd 237+); unsupported queries report errors.

Journal snapshots have a shared 16 MiB capture limit for local and remote hosts.
Entries above 64 KiB are omitted with an explicit count, not silently shortened.
Retained history and the live inbox each have a 4 MiB serialized-data budget in
addition to their existing entry limits. Parsed objects, displayed strings and GTK
add overhead; these budgets are not a hard limit on total application RSS. Live
reads discard oversized lines in bounded chunks and recover at the next record.
Original journal data is never changed. A snapshot that exceeds its capture budget
reports failure and retains the previous view; narrow the range/filters to retry.

Network keeps its Live / Connections / Basic defaults. Automatic socket reads
remain at two seconds while visible, subject to existing completion/backoff rules.
Interface and default-route data is reused for 30 seconds per page/host, with its
own collection timestamp. Manual Refresh always collects all components. Existing
hidden-tab pause, process options, colors, column widths and incremental updates
remain in place. No background worker or polling timer was added.


Validation: all 167 tests passed with the GTK desktop enabled. Read-only local
journal paging verified 100 recent and 100 preceding entries without overlap.
The toolbar was visually checked at 1050×700. Existing settings are preserved;
reopen the installed app to load the updated modules.

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
sudo apt install ./dist/alpha1/syslogapp_2.0.0-alpha1-1_all.deb
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
