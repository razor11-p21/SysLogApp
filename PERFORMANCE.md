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
