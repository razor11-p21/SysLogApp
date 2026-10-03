# SysLogApp v2 — Preview 19

A focused Linux system-health and troubleshooting desktop application for GTK3, designed for Linux Mint / Ubuntu-family systems using systemd/journald.

## Preview 19 — Public beta preparation

Copyright (C) 2026 pit pitopoulos. Released under **GPL-3.0-or-later**; see
[LICENSE](LICENSE), [AUTHORS](AUTHORS), and [NOTICE.md](NOTICE.md).

- Separate Debian packages for the main app and optional Cinnamon launcher.
- Required dependencies include GTK3/Cairo, psutil, and the host diagnostics tools.
- Source upgrades validate and stage files, roll back failed replacements, and
  retain the previous installation after success. Existing settings are preserved.
- Missing maintenance tools disable their actions; maintenance tasks cannot overlap.
- Administrative commands wait for completion without a two-minute kill timeout.
- Event Details stays collapsed until a log entry is selected, with a close button.

See [RELEASE.md](RELEASE.md) for package installation, migration from a per-user
installation, maintenance limitations, and validation scope. Build packages with:

```bash
/usr/bin/python3 scripts/build_release.py
```

## Preview 18 — Health accuracy and responsive monitoring

- Failed or inaccessible checks display **Couldn't check** rather than a healthy zero.
- Journal counts count JSON events, including multiline events only once. Errors
  include Emergency through Error; warnings count only Warning events.
- Recent issues include Emergency events and match the current boot navigation.
- Live CPU/memory/disk metrics refresh independently of slower health checks.
  Health checks run every minute while the dashboard is visible; Refresh Now
  requests fresh metrics and health checks. Separate timestamps show data age.
- DNS resolution uses the system resolver through `getent` with a four-second
  subprocess timeout.
- Top-bar search has explicit Logs / Network targets. Log search covers loaded
  entries; network search covers the current connection snapshot. Existing page
  filters remain active.
- Metric cards and filter controls wrap, dashboard sections stack on narrower
  windows, and the sidebar switches to icons with tooltips below 1150 pixels.
- The requested minimum window size is now 800 × 580; pages support scrolling
  where content still needs more room.

Run this workspace copy without installing it:

```bash
./run-preview.sh
```

Regression checks (GTK bindings are required to run the UI behavior tests):

```bash
/usr/bin/python3 -m unittest discover -s tests -v
```

## Network v2 features inherited from Preview 17

The Network page retains the live troubleshooting features introduced in Preview 17.

### New Network v2 features

- **Pause / Resume live monitoring**
  - Pause freezes the current Network snapshot so rows, sorting, scrolling and details stay stable while you inspect them.
  - `Refresh Now` still takes a one-shot sample while paused without resuming the 2-second timer.
  - Resume establishes a fresh traffic-rate baseline before normal 2-second sampling continues.
- **Sortable connection/listener columns** by clicking table headers.
- **Connection scope classification**:
  - `Local` — loopback or another address on this host
  - `LAN` — RFC1918, link-local, CGNAT/Tailscale-style and other non-global addresses
  - `Internet` — globally routable remote addresses
  - `Unknown` — endpoints that cannot be classified
- **Scope filtering** alongside the existing protocol/state/search filters.
- **Richer connection details** with best-effort:
  - process name
  - PID
  - username
  - executable path
  - local interface
  - protocol / address family
  - scope and TCP state
  - local and remote endpoints
- **Context menu** on connection rows:
  - copy connection/listener
  - copy remote/local IP
  - copy port
  - filter by process
  - filter by remote IP
  - show only the selected scope
  - clear filters
- **Filter Process** and **Filter Remote** actions in Connection Details.
- **Selection and scroll preservation** across live refreshes.
- Filter counts now show `shown • total` when filters are active.
- Search also matches username, executable path and interface name.
- Primary-interface card exposes detected DNS servers as a tooltip.

SysLogApp remains non-root. Linux can hide PID/process metadata for sockets owned by other users, so these fields are deliberately best-effort rather than elevating the whole application.

## Main areas

### Dashboard
- CPU, memory, root filesystem, failed services, network and journal health cards
- System identity / kernel / boot / CPU information
- Recent warning/error journal events
- Lightweight live CPU graph
- Quick local diagnostics
- Clickable navigation cards

### Logs
- Current-boot or recent journal history
- Exact severity filters
- Optional systemd unit filtering
- Search across loaded events
- Live journal follow mode with Pause / Resume
- Severity-colored message text
- Responsive wrapped messages
- Scan-friendly timestamps such as `01:39:01 · Today`
- Event details, context actions, copy and CSV export

### Network
- Primary interface / gateway / DNS status
- Live RX/TX rates and adaptive traffic graph
- Live Connections
- Listening Ports
- Interface overview
- Pause / Resume
- Sorting and search/filter controls
- Local / LAN / Internet classification
- Rich connection details and context actions

### Diagnostics
- Failed services
- Disk capacity
- Internet reachability
- DNS resolution
- OOM indicators
- Recent journal errors
- Memory pressure
- Read-only technical details

### Maintenance
A deliberately small set of explicit actions:
- Vacuum old journal logs
- Clean APT package cache
- Reload systemd unit files
- Restart NetworkManager
- Finish interrupted `dpkg` configuration
- Show journal disk usage

Elevated maintenance operations use PolicyKit / `pkexec`. SysLogApp does not receive or store your sudo password.

### Settings
- System / Light / Dark theme
- Dashboard refresh interval
- Start page
- Log history size
- Compact mode

Settings are stored in:

```text
~/.config/syslogapp/config.json
```

## Requirements

```bash
sudo apt update
sudo apt install python3 python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-3.0 python3-psutil systemd iproute2 iputils-ping libc-bin pkexec polkitd
```

## Install / upgrade

For a per-user installation, extract the Preview 19 source archive and run:

```bash
cd SysLogApp-2.0.0~preview19-1
./install.sh
```

Then launch with:

```bash
syslogapp
```

The source installer uses:

```text
~/.local/bin/syslogapp
~/.local/share/syslogapp/
~/.local/share/applications/syslogapp.desktop
```

Source upgrades preserve an existing desktop entry to avoid unnecessary Cinnamon menu refreshes. The Debian packages use system-wide paths; see RELEASE.md before migrating.

## Architecture

```text
syslogapp/
├── app.py
├── config.py
├── services.py
├── styles.py
├── widgets.py
└── pages/
    ├── dashboard.py
    ├── logs.py
    ├── network.py
    ├── diagnostics.py
    ├── maintenance.py
    └── settings.py
```

Blocking collection work runs through the existing worker thread pool and returns to GTK through the main loop.

## Privacy

There is no AI/API integration. Log and network information remain local unless you explicitly copy or export it. Connectivity checks send ICMP probes to 1.1.1.1 and resolve example.com through your configured DNS resolver.

## Version

`2.0.0-preview19`
