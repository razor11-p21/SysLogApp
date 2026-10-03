# Preview 19 release preparation

Copyright (C) 2026 pit pitopoulos. License: GPL-3.0-or-later (see LICENSE).
Maintainer identity: pit pitopoulos
<218387257+razor11-p21@users.noreply.github.com>.
This GitHub noreply identity preserves email privacy; it is not a support inbox.

## Packages

Build locally with `/usr/bin/python3 scripts/build_release.py`.
Outputs are written to `dist/preview19/`:

- `syslogapp_2.0.0~preview19-1_all.deb`: main application.
- `syslogapp-cinnamon-applet_2.0.0~preview19-1_all.deb`: optional Cinnamon applet.
- Source archive and SHA256SUMS.

Install the main package using APT so dependencies are resolved:

```bash
sudo apt install ./syslogapp_2.0.0~preview19-1_all.deb
```

Install the applet package only if you use Cinnamon and want its launcher:

```bash
sudo apt install ./syslogapp-cinnamon-applet_2.0.0~preview19-1_all.deb
```

Then open Cinnamon System Settings → Applets, find SysLogApp and add it to your
panel. Installation never edits anyone's panel settings. The applet package is
optional; the main application does not depend on Cinnamon.

Packages install program files under `/usr/share/syslogapp`, the launcher under
`/usr/bin/syslogapp`, and the desktop entry under `/usr/share/applications`.
The source installer remains available for per-user installations.

## Migrating from a per-user installation

The existing `~/.local/bin/syslogapp`, user desktop entry, and user applet can
shadow their system-installed replacements. Before switching to Debian packages,
close SysLogApp, remove its applet from the panel, then run `./uninstall.sh` from
the source folder. It retains preferences. Remove the old user applet folder only
if it is your SysLogApp applet, then install the packages and optionally enable
the system applet. Do not run the source installer again over a package install.

## Maintenance behavior

Administrative actions use absolute executable paths and PolicyKit; the app
never handles a password. Missing tools disable their actions. Only one
maintenance action can run at a time. Write operations wait for completion
without a fixed timeout and run in a separate process session, so terminating
the GUI does not intentionally terminate an already-started operation. Output
capture uses a temporary file and displays at most the last 1 MiB.

Package recovery has no interactive terminal. If a package requires interactive
input, recover it from a terminal instead. Closing the window can discard the
visible result; let maintenance finish before closing the app.

Read-only command collection retains bounded timeouts. Nothing in release
validation executes privileged cleanup, service restarts, or package recovery.

## Validation and support scope

The source installer stages files before replacing anything, validates Python
syntax, verifies GTK3/Cairo/psutil and required commands, and rolls back failed
upgrades. A successful source upgrade retains the previous application under
`~/.local/share/syslogapp-backups/`. Preferences are not touched.

This is a beta intended for systemd-based Linux Mint/Ubuntu desktops with
Python 3.9 or newer and GTK3. APT/dpkg operations require Debian-family tools.
NetworkManager restart requires that service to be installed. Journal visibility
and socket ownership information depend on the current user's permissions.

Local automated tests and package inspections are useful but do not replace
fresh-install, upgrade, and removal tests on clean Mint/Ubuntu virtual machines.
Do not advertise support for every Linux distribution.
