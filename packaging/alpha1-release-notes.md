# SysLogApp 2.0.0 Alpha 1

First public alpha of SysLogApp, a terminal-style GTK3 desktop app for systemd-based Linux systems.

## Highlights

- Color-coded journal logs with Live/Pause, historical search, exclusions and optional repeat grouping.
- Bounded history (400 events by default, up to 2000) and deferred table updates while hidden.
- Network connections with application/PID/port filters and on-demand process details and service logs.
- Local and SSH hosts using password or key authentication; optional desktop-keyring password storage.
- A compact system overview and explicit maintenance/logrotate controls.
- JSONL/CSV exports with preview and redaction, saved views/bookmarks, and remembered window/column sizes.
- Clear stale-data/error handling and retry/keep-open choices when settings cannot be saved.

## Downloads and installation

Download the main `syslogapp_2.0.0~alpha1-1_all.deb` for a Debian-family desktop, then:

```bash
sudo apt install ./syslogapp_2.0.0~alpha1-1_all.deb
syslogapp
```

The `syslogapp-cinnamon-applet` .deb is optional and requires Cinnamon. It does not enable itself or change panel settings.
The source archive supports per-user installation with `bash ./install.sh`; prerequisites are documented in README.md.
Existing private preview .deb packages sort after this alpha in Debian version ordering. For those previews, use the per-user/source upgrade route described in README.md.

## Validation and known limits

Validation: **310 tests passed** with GTK and strict resource warnings under a hard 1 GiB per-process address-space limit. Release integrity, staged package checks and source-archive checks passed.

Tested on Linux Mint 22.3. Ubuntu, Debian and Fedora still need native verification. Fedora uses source installation; no RPM is supplied. The system journal requires systemd/journalctl. Remote overview and rotation helpers require Python 3.8+; journal/process visibility depends on account permissions. APT/dpkg maintenance actions are unavailable when those tools are absent.

See [COMPATIBILITY.md](https://github.com/razor11-p21/SysLogApp/blob/main/COMPATIBILITY.md) for SSH test scope and remaining real password/keyring checks.

This is an **alpha pre-release** for testing and feedback. Please report the distro/version, app version and reproduction steps when filing an issue, and redact private log or SSH details.

[Watch the short showcase](https://youtu.be/QMs4t9-B8qw)

Copyright © 2026 pit pitopoulos · GPL-3.0-or-later.
