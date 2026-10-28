# Preview 40 performance check

Measured on the user's Linux Mint desktop, 21 October 2026. Before is Preview 39;
after includes incremental socket updates, lazy sort comparisons, bounded parsing
caches and reused terminal palettes. Layout, data limits, filtering, coloring,
column order/alignment, saved sizes and maintenance behavior are retained.

## Local synthetic CPU results

Measurements are median process CPU time, in separate Python processes, without
cProfile. This deliberately exercises the supported maximum history/socket counts,
not the default 400-event history. Workloads do not run journalctl, ip, ss or any
maintenance action. They are not end-to-end latency or universal speed guarantees.

| Workload | Before | After | Less CPU time |
| --- | ---: | ---: | ---: |
| Load 2,000 log records | 318 ms | 90 ms | 72% |
| Append a 100-event burst with 2,000 retained logs | 22 ms | 9.5 ms | 57% |
| Load 1,000 sockets | 252 ms | 78 ms | 69% |
| Change one row among 1,000 sockets | 214 ms | 14 ms | 93% |
| Unchanged 1,000-socket refresh | 0.83 ms | 0.93 ms | Essentially unchanged |

The benchmark uses three samples per load/burst and five per sparse/unchanged
update. Timings vary with hardware, GTK theme, text size, column widths and load.
The initial cProfile run identified repeated GTK row reads and full socket-table
replacement as the main costs; profiling overhead is excluded from this table.

## Memory and idle behavior

A separate tracemalloc test called natural sorting on 256 unique 32 KiB strings,
then discarded the results. The old global cache retained **16.1 MiB**. The new
cache retained effectively **0 MiB** for those oversized inputs (0.11 MiB transient
peak). This measures cache retention, not the viewer's total RAM. Full messages
remain in retained records and continue to display/copy normally.

The synthetic GTK process used approximately 70 MiB resident memory after loading
both test tables. The old run was about 71.5 MiB; this small difference is within
normal allocator/theme variation and is not claimed as a general RAM reduction.
Record limits do not impose a byte limit on unusually large journal messages.

After a two-second layout settling period, the new process used about 0.28 ms CPU
over a 1.5-second idle GTK loop (roughly 0.02% of one core). Both versions were
near idle in this short check. No recurring timers or background probes were added.
This is an offscreen GTK smoke check, not a desktop compositor/GPU/power benchmark.

## Reproduce

```bash
/usr/bin/python3 scripts/benchmark_ui.py
/usr/bin/python3 scripts/benchmark_ui.py --profile
/usr/bin/python3 scripts/benchmark_ui.py --large-cache
# Compare to a separate source copy containing syslogapp/:
/usr/bin/python3 scripts/benchmark_ui.py --source /path/to/other/source
```

Use the same interpreter/display/theme and separate, sequential processes for
before/after comparisons. Do not compare profiled and unprofiled timings. Output
includes update CPU time, a settled idle interval, and Linux RSS/high-water values.
The script does not write app preferences or call administrative commands.

Regression coverage includes identical log/network sort keys for every sort
column, descending network sorts, duplicates, selection retention and exactly one
native row replacement for a one-socket change. The full suite also covers live
pause/hidden behavior, history limits, responsive wrapping and saved layouts.


## Follow-up efficiency review — 25 October 2026

Network filtering now reads the process-detail mode once per refresh, instead of
once per socket. Full journal filtering temporarily disables insertion-time sorting,
then restores the selected column and direction after loading the complete snapshot.
Live batches skip table eviction checks until history actually overflows; empty
drains return immediately. Existing bounded queues, hidden-tab pause, failure backoff,
cache limits and incremental socket updates remain in place.

In sequential local synthetic GTK runs, the baseline unchanged 1,000-socket refresh
used 1.19 ms median CPU; the final version used 0.47 ms. The 2,000-record journal
reload used 88 ms before and 75 ms in the final run; an earlier optimized run was
84 ms, so this modest gain is sensitive to run-to-run variation. The final live
100-event burst was 8.43 ms versus 8.94 ms before, with no meaningful burst speedup
claimed. Neither RAM nor idle CPU showed a material change. These results exclude
subprocess collection and desktop rendering, and do not predict whole-app speedups.
An iterator-based eviction experiment was discarded because it did not improve bursts.

Validation: 150 tests passed, including a new descending-sort/search regression.
After reverting the iterator experiment, all 14 journal UI behavior tests passed
again. The installed local copy matches the optimized source pages. No running
app was forcibly closed; reopen it to load the updated modules.

Remaining limitation: journal history is bounded by entry count, not record byte
size. Exceptionally large messages can still consume substantial memory; a complete
byte-budget policy would need to preserve useful detail and clearly explain any
truncation to users. No message truncation was introduced in this review.


## Horizontal resize responsiveness — 25 October 2026

Automatic table column widths now coalesce until 60 ms after the latest width
change. Initial fitting remains immediate. This prevents repeated wrapped-row
layout on each horizontal drag event; vertical allocations with the same widths
do not schedule work. Manual header widths remain respected, Fit columns resets
automatic fitting, and pending work is cancelled when pages are destroyed.
The same mechanism covers System logs, Network and Overview.

A sequential unprofiled offscreen GTK comparison used 1,000 synthetic journal
records with moderately long wrapped messages and 42 horizontal resize steps.
The previous code used 1,555 ms CPU and its slowest resize timer interval was
47.9 ms; the updated code used 324 ms CPU and its slowest interval was 21.3 ms.
This is approximately 79% less CPU in that specific synthetic workload. It does
not measure actual desktop compositor behavior, mouse latency or all app tabs.
Columns settle briefly after dragging rather than rewrapping every intermediate
width. No new polling timer or background sampling was added.

Reproduce with `/usr/bin/python3 scripts/benchmark_resize.py` and an optional
source-directory argument for the baseline. `--profile` enables cProfile; compare
unprofiled results to unprofiled results. The benchmark writes no preferences
and makes no real journal, network or maintenance calls.


## Preview 49 — bounded journal data and slower interface/route collection

Local journal capture now uses the same bounded pipe reader as other diagnostics,
with the same 16 MiB snapshot ceiling used for SSH journal reads. Retained history
and the live inbox each have a 4 MiB serialized UTF-8 data budget and their existing
entry-count limits. Entries above 64 KiB are omitted with an explicit count; live
reads discard oversized records in bounded chunks and recover at the next newline.
Python/GTK object and string overhead is additional, so these are not RSS ceilings.
Original system journals are unchanged. A capture that exceeds its total budget
fails visibly instead of presenting partial JSON as a successful empty result.

Network automatic refreshes reuse per-page/host interfaces and routes for 30
seconds. A cached refresh launches one ss command instead of ss plus three ip
commands. Manual Refresh bypasses this cache; hidden-tab pause and failure backoff
are preserved. Cached data has its own collection timestamp. This is a verified
reduction in command launches, not a measured whole-app CPU, GPU or battery claim.

Historical searches run on explicit submission, with frozen absolute time ranges,
literal case-insensitive message filters and optional previous-boot scope. Older
uses cursor-based reverse reads and replaces the current bounded page. Typing in
the existing loaded-row search performs no new subprocess or SSH query.

Regression coverage adds real bounded-child capture, oversized-stream recovery,
UTF-8 byte counting, retained/inbox byte limits, shared SSH capture ceilings,
time/message/boot arguments, chronological cursor paging, History dialog submission,
Live return to recent logs and manual/automatic cache expiry. A read-only local
journal smoke check returned 100 recent and 100 preceding records with no cursor
overlap. No live remote host or GPU/power benchmark was used for this change.


## Preview 50 — stale socket data

Failed socket reads retain the existing rows and metadata instead of replacing
them with an empty list. This stores only the already-retained bounded snapshot;
no extra snapshots, commands or timers are added. An explicit stale status carries
the last successful socket timestamp separately from interface/route timestamps.
Existing incremental filtering keeps native rows and selection when data is
unchanged, including during partial failures. Recovery accepts valid empty results.


## Preview 51 — saved investigations

Saved-view and bookmark dialogs/storage are loaded on demand. Startup and idle
monitoring gain no polling timers or remote reads. Each explicit save uses one
bounded atomic local-file replacement; the file is limited to 1 MiB, with at most
100 views and 100 bookmarks. Saved message text is capped at an explicitly labelled
8 KiB UTF-8 excerpt. The manager uses native GTK models and fetches a journal event
only after Locate event, allowing only one such request per dialog at a time.
Host identity excludes passwords/authentication method/key paths, and remote reads
remain routed through the selected SSH session. No CPU/GPU speedup is claimed.


## Preview 52 — on-demand connection inspection

Normal network polling performs no new process reads. Only an explicit process
or service-log action loads the inspector and reads /proc for one selected PID.
The descriptor's socket inode/endpoints and process start identity are verified.
Socket tables are limited to 2 MiB per family, other /proc records to 32 KiB,
command lines to 16 KiB, and remote probe output to 128 KiB with an eight-second
capture timeout. No process-directory enumeration or NSS/DNS lookup is performed.
Related service logs are loaded only on tab open and use the existing 400-entry,
4 MiB retained, 64 KiB record and 16 MiB snapshot limits. Static GTK TextViews wrap
and select text without ongoing refreshes. No CPU/GPU/battery speedup is claimed.


## Preview 53 — on-demand exports

Export helpers/UI load only on explicit action, pause Live and snapshot shown rows
without new commands or remote queries. Serialization/redaction runs on the existing
worker, with one in-flight preview per dialog and invalidation of changed options.
Output is limited to 32 MiB, redaction maps to 10,000 placeholders, custom literals
to 32×256 characters. The GTK preview holds at most 32,768 characters at a time.
These are data limits, not whole-process RSS ceilings: snapshot references, JSON,
serialization buffers and widgets add memory overhead. No idle work or CPU/GPU
speedup is claimed. Atomic file writes happen only after an explicit save.


## Preview 54 — Overview diagnostics on demand

Overview remains a first-open/manual snapshot with no repeating timer. One bounded
systemctl query lists failed system services, and a separate Python helper reads
filesystem usage with a three-second caller budget. Network/FUSE usage is opt-in;
virtual filesystems are never probed for capacity. Equivalent device/root/type
bind mounts reuse one read. Local filesystems are processed before network mounts.
Completed helper output survives timeout; missing results are explicitly unavailable
or unchecked. Kernel-uninterruptible I/O can delay actual helper termination, so the
caller timeout is not a kernel-I/O cancellation guarantee.

Mountinfo input is capped at 2 MiB, mount/service lists at 128 items, usage-helper
output at 64 KiB and service output at 128 KiB. SSH results are capped at 256 KiB
with a ten-second outer capture budget. These are data/caller budgets, not total
RSS limits or guarantees about remote kernel response times. Basic host/memory
information stays independent from failed checks. Toggling virtual mounts filters
retained data without any subprocess or SSH read. No CPU/GPU speedup is claimed.


## Preview 55 — SSH state and adjustable journal capacity

Master-loss detection uses a blocking Linux pidfd plus a cancellation pipe, with
one control-socket check at connection setup and no recurring app poll. Failed reads
check the existing control socket; ordinary remote command failures do not imply a
transport failure. Without pidfd support, loss is detected on failed reads.
Reconnect reuses widgets/data, invalidates queued reads and pauses monitoring until
the user requests fresh data. It never resubmits maintenance work.

The journal selector changes entry capacity from default 400 up to 2000; retained
history and pending batches retain their existing byte ceilings. Increasing capacity
can increase GTK row memory and rendering cost. Native non-overlay scrollbars and
static tooltip CSS add no timers or background work. No new performance benchmark
or CPU/GPU speedup is claimed.


## Preview 56 — event-driven tooltip positioning

Hover boxes move only on pointer events or popup allocation, and reuse one lazily
created native popup per hovered widget. There is no pointer polling, animation or
input grab. Text changes only when the hint changes, with a 4096-character/twelve-line
preview limit. Destroying a widget destroys its popup. No new performance benchmark
or reduction in CPU/GPU use is claimed.


## Preview 57 — native tooltips restored

Removed Preview 56's custom popup windows, recursive hint hooks and pointer-motion
tracking. GTK again owns hover delay, layout and dismissal; only CSS changes the
appearance. The table hover coordinate fix remains. No desktop setting is changed.


## Preview 58 — tooltip styling rollback

Removed the tooltip-specific CSS added in Preview 55. Native tooltip behavior is
retained, with no additional windows, handlers or timers. No performance claim.


## Preview 59 — remove hover info boxes

Removed application tooltip text and dynamic table hover handlers. There are no
custom hover popups or timers. No performance benchmark or speedup is claimed.


## Preview 60 — stationary log hover

A pending log hover uses a single 3000 ms GLib one-shot timer. Movement cancels it;
there is no recurring polling. A non-focusable popup is created only when needed
and reused until its log table is destroyed. Text is bounded to 4096 characters
and twelve lines. No new CPU/GPU performance benchmark or speedup is claimed.


## Preview 61 — two-second hover delay

The log hover one-shot timer now waits 2000 ms. No other resource behavior changes.


## Preview 62 — lifecycle, cleanup and bulk sorting audit

Measured on the user's Mint desktop on 25 October 2026, comparing installed
Preview 61 with Preview 62. Three alternating separate Python processes per version
ran scripts/benchmark_ui.py without profiling, using synthetic data and no host
commands or settings writes. Each process takes three load/burst samples and five
sparse/unchanged samples; the table gives medians across the three process reports.

| Workload | Before CPU | After CPU |
| --- | ---: | ---: |
| 1000-socket load | 75.370 ms | 66.944 ms |
| One socket change among 1000 | 13.405 ms | 13.609 ms |
| Unchanged 1000-socket refresh | 0.479 ms | 0.483 ms |
| 2000-log load | 87.247 ms | 84.362 ms |
| 100-event burst at 2000 retained logs | 10.746 ms | 9.882 ms |
| 1.5-second synthetic idle loop | 0.295 ms | 0.330 ms |

Only the bulk network sort is a deliberate CPU optimization here (about 11% less
CPU for this load). Other small differences are not claimed as speedups. The idle
loop contains no live collection. RSS medians were 71952 KiB before and 71896 KiB
after, effectively unchanged; this does not establish a general RAM reduction.
No GPU, compositor, SSH latency or real journal-throughput measurement was made.

The more significant memory fix concerns repeated page lifecycles: 21 rounds of
creating/destroying Logs, Network, Overview and Maintenance retained 63 of 84 page
wrappers before the fixes and zero afterwards. Descriptor counts remained 13 after
warmup and after the loop. The regression runs in an isolated GTK process and
checks for leaked page wrappers, descriptors and callback tracebacks.

Additional regression coverage checks diagnostic descendant termination even if
the parent already exited, cleanup after socket/pidfd setup failures, closed-session
state guards, malformed journal priorities/source fields, and bulk sort/selection/
duplicate preservation. Pending hover timers and native GTK callbacks are released
on destruction. Existing bounded journals, cached interface queries and explicit
maintenance scheduling remain; no new polling worker was added.

Validation: 252 tests passed with GTK and strict resource warnings; the loopback
SSH integration check also passed. Large-string natural-sort caching retained
0.000 MiB with a 0.111 MiB transient peak. These checks do not establish absence of
all bugs or compatibility with every remote distribution.


## Preview 63 — slower drag events and redundant painting

Three alternating separate-process samples per version used 1000 synthetic wrapped
log rows, 42 horizontal steps and --step-ms 80 in scripts/benchmark_resize.py.
The installed Preview 62 was the baseline. At that event spacing the old 60 ms
resize debounce repeatedly applied widths during dragging; 120 ms coalescing
substantially reduces repeated wrapping. Column-divider drags now use the same
coalescing while recording their manual width immediately. A 50 ms row-height
refresh follows the final width update.

| Slow-drag workload | Before | After |
| --- | ---: | ---: |
| Process CPU time | 4528.8 ms | 1150.3 ms |
| Wall time | 4545.3 ms | 3871.0 ms |
| Slowest scheduled step (80 ms target) | 109.2 ms | 89.9 ms |

The approximately 75% CPU reduction applies to this synthetic slow-drag workload.
Fast drag events already coalesced in the baseline and benefit much less. These
measurements do not establish compositor smoothness, real input latency, GPU load,
or equivalent speedups for every log length and desktop configuration.

GTK tables now redraw newly exposed areas on allocation changes instead of
requesting full-table repaint. Row/content changes still redraw as needed, following
[GTK's allocation redraw guidance](https://docs.gtk.org/gtk3/method.Widget.set_redraw_on_allocate.html).
Renderer callbacks skip unchanged foreground/weight properties and empty selection
attributes, and the timestamp callback avoids a redundant canonical-text assignment.
No continuous timer or polling worker was added.

### Actual running-app sample before Preview 63

A 15.03-second sample while System logs was selected measured 16.3% of one CPU core
including completed helpers, with a 57.9% half-second peak. A journalctl helper was
observed. This was an active-use sample, not an idle benchmark. App RSS was 74.16
MiB; proportional memory was approximately 43.32 MiB and private memory 38.86 MiB.
Summed app/helper peak RSS was 104.16 MiB (shared pages can be counted twice). The
app had seven threads, up to fifteen open descriptors, and no swap. Its physical
read_bytes/write_bytes counters did not increase during the sample.

No direct DRM/GPU context was detected for the app. The whole AMD GPU showed 3%
busy at a separate instant; that cannot be attributed to SysLogApp because Cinnamon
and other programs share the GPU. Installation files occupied 962560 bytes, settings
12288 bytes, rollback copies 24276992 bytes and local release artifacts 8278016 bytes
at measurement time. These storage figures precede installation of this update.

The final fast 16 ms-step comparison measured median CPU 354.4 ms before versus
265.2 ms after (three alternating processes per version); wall time was 1128.3
versus 1097.9 ms and the slowest step was 22.9 versus 21.7 ms. All 253 regression
tests passed with GTK and strict resource warnings. Synthetic narrow/wide screenshots
were inspected for wrapping, colors and stale-paint artifacts after settling.


## Preview 64 — compact Overview presentation

The initial Overview readout renders six fields in a selectable text view. The
existing bounded diagnostic table stays collapsed until opened. Expanding the
section performs no query or parsing; the full snapshot is already loaded. Host
collection, budgets, stale-data handling and first-open/manual scheduling are
unchanged. No polling timer or worker is added, and no benchmark speedup is claimed.

Validation: 256 tests passed with GTK and strict resource warnings, including the
isolated repeated-page lifecycle check. Synthetic 480/860-pixel Overview layouts
were visually checked for clipping and details visibility.


## Preview 65 — memory clarity without additional monitoring

The existing /proc/meminfo read supplies typed RAM and swap data. Only the four
needed fields are parsed; no process scan, additional command, sampling interval
or timer is introduced. RAM-used estimation is total minus kernel MemAvailable,
which includes reclaimable memory as described in the
[kernel documentation](https://docs.kernel.org/filesystems/proc.html#meminfo).
RAM and swap availability are independent; no fallback substitutes MemFree for
MemAvailable. Swap occupancy alone does not measure I/O rate or trigger an alert.
All 264 tests passed with GTK and strict resource warnings, including lifecycle
checks. No new CPU, RAM or GPU reduction is claimed.


## Preview 66 — loaded connection filters

Application/PID/port criteria operate only on the bounded loaded socket list,
before display-row formatting. PID and port parsing is performed once per filter
pass. Owner pairs are cached per loaded row only for process strings up to 4096
characters, with raw-value checking before reuse; longer strings are parsed on demand.
There is no global owner cache, host command, /proc scan or polling timer for filtering.

A synthetic pure-Python pass over 1000 rows with all three filters matched 32 rows
in 3.957 ms CPU cold and 2.226 ms median across ten warm passes. This excludes GTK
model updates/rendering and is not an end-to-end latency or general speedup claim.
Inspection and related logs continue to run only when explicitly opened. Saved
views/export metadata record filter context without collecting new host data.

All 276 tests passed with GTK and strict resource warnings, including repeated-page
lifecycle checks and verification that changing filters performs no host queries.
Synthetic narrow and wide layouts were visually checked.


## Preview 67 — release readiness

Only installer/build/test paths changed; dependency guidance reads os-release only
on installer preflight failure. No runtime monitoring or rendering work was added.
All 280 tests passed with GTK and strict resource warnings on Mint 22.3. The
loopback OpenSSH check passed without resource warnings. See COMPATIBILITY.md
for limits; no cross-distro or CPU/RAM speedup is claimed.


## Preview 68 — journal freshness and diagnostics

Remote journal reads return stderr from the existing bounded capture; no extra
SSH command is made. Freshness stores one timestamp and at most 1000 characters
of error per log page. Status updates occur on existing read/live callbacks.
No polling, additional worker or network query is introduced. All 292 tests passed
with GTK and strict resource warnings; loopback SSH diagnostic checks also passed.


## Preview 69 — hidden log table work and repeat groups

Hidden tabs continue the existing bounded journal reader/inbox draining. Table
filtering, model mutations, scrolling and reflow are deferred; unmapping clears
the old model once to release expired references. Returning rebuilds retained
history once without a journal/SSH read. Exclusion matching uses loaded data only.
The existing journal reads also request boot/user/invocation identity fields
within the existing capture and record limits. Optional repeat grouping stores references to retained original events; live
group counts update stable GTK rows. Grouping is off by default. No new timer,
worker, host query or runtime dependency is added.

Synthetic benchmark on this Mint desktop: 100 batches of 100 events, 2000 retained,
using scripts/benchmark_hidden_logs.py in separate processes against installed
Preview 68 and workspace Preview 69. Hidden processing CPU was 993.478 ms before
and 61.272 ms after; model mutations fell from 18000 to zero during collection.
Returning restored 2000 rows in 103.830 ms of callback CPU (before: 0.143 ms, since
the hidden model had already been maintained). This single synthetic run excludes
journal/SSH collection, compositor/GPU usage and subsequent painting; it does not
establish a general CPU, RAM or GPU reduction. Wide/narrow layouts were inspected.

Validation: all 309 tests passed with GTK and strict resource warnings, including
repeated-page lifecycle checks, hidden model inactivity, byte-budget enforcement
and release of expired row references.


## Preview 70 — close-time settings error handling

Settings-save errors are handled only during close. The existing atomic settings
write is retried only when the user chooses Retry. Keep open preserves active
sessions; explicit Close without saving suppresses the shutdown fallback write.
No timer, polling, background task, host query or runtime dependency is added.

All 310 tests passed with GTK and strict resource warnings, including six isolated
close/save scenarios. No CPU/RAM improvement is claimed for this change.
