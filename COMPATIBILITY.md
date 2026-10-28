# Release readiness — Preview 67

Audit date: 26 October 2026. This is an evidence record, not certification for
all Linux distributions. No administrative maintenance action was executed.

Results: all 280 GTK/unit tests passed with strict resource warnings; the real
loopback OpenSSH checks passed without resource warnings. Both .deb packages
passed staging/integrity checks. Lintian reported no errors and only the
initial-upload-closes-no-bugs advisory for each package (there is no Debian bug
number to close). A deliberately changed payload was rejected by the checker.

| Environment | Evidence | Remaining verification |
| --- | --- | --- |
| Linux Mint 22.3, this PC | GTK regression suite; temporary-user clean install and two upgrades; rollback fault tests; staged Debian packages; live loopback OpenSSH | Actual system-wide dpkg install/upgrade/removal in a disposable machine; interactive authentication and desktop launch on a fresh account |
| Ubuntu | Package names checked against official repositories; Debian-family dependency guidance tested | Native desktop, package lifecycle and real SSH target tests |
| Debian | Package names checked against official repositories; Debian-family dependency guidance and remote capabilities tested | Native desktop, package lifecycle and real SSH target tests |
| Fedora | Official dependency names checked; Fedora guidance and missing APT/dpkg capability scenarios tested | Native desktop, source installation and real SSH target tests; RPM packaging is not provided |

Mocked capability scenarios test program behavior, not another distribution's
actual binaries. Mint sharing Ubuntu packages does not establish Ubuntu coverage.
No VM images or container runtime for those distributions were available here.

## Installation and upgrades

The per-user installer requires Python 3.9+, GTK3/PyGObject, journalctl, ip, ss and
OpenSSH client. It checks dependencies before replacing the app. Failure tests
cover preflight, syntax validation, app swap and launcher/desktop write failures.
A clean install followed by two upgrades preserves settings and retains prior
application copies. Existing desktop entries are preserved intentionally.

The .deb files are for Debian-family distributions only. The release checker
verifies archive hashes, staged file checksums, Python syntax, desktop entry,
launcher mode and declared core dependencies. It rejects unsafe source archive
paths/links and accidental inclusion of private directories. These staging
checks do not install packages, resolve dependencies on another system, or test
dpkg lifecycle behavior. The optional Cinnamon applet requires Cinnamon.

Fedora source/per-user installation prerequisites:

```bash
sudo dnf install python3 python3-gobject gtk3 systemd iproute openssh-clients
bash ./install.sh
```

Optional maintenance and password storage need the corresponding distro packages
and configured services (polkit/pkexec, logrotate, sudo on SSH hosts, Secret Service
keyring). The installer does not enable these services or grant journal access.
Log/process visibility remains limited by the connected account's permissions.

Official package references checked during this audit:
[Ubuntu GTK3](https://packages.ubuntu.com/nl/gir1.2-gtk-3.0),
[Debian PyGObject](https://packages.debian.org/en/trixie/python3-gi),
[Fedora PyGObject](https://packages.fedoraproject.org/pkgs/pygobject3/python3-gobject/),
[Fedora GTK3](https://packages.fedoraproject.org/pkgs/gtk3/gtk3/),
[Fedora OpenSSH client](https://packages.fedoraproject.org/pkgs/openssh/openssh-clients/),
[Fedora iproute](https://packages.fedoraproject.org/pkgs/iproute/iproute/).

## SSH evidence and boundaries

The temporary loopback server uses throwaway host/client keys and a random port,
with no change to the system SSH service, accounts or configuration. Real OpenSSH
checks cover changed-host-key rejection, literal argument quoting, remote journal,
network and overview reads, live-stream shutdown, encrypted private keys, first
host trust via fixture askpass and cancellation of a waiting authentication prompt.
A printf-only operation checks both maintenance transport modes without changing
system state. Disconnect removes the control socket and stops the live stream.

Unit/UI tests cover password handoff privacy, saving only after authentication
and capability probing, authentication/probe failure cleanup, stale callbacks,
no implicit reconnect, missing tools and local/remote tab routing. Successful real
password login, interactive keyring prompts, sudo/polkit prompts and behavior on
non-Mint SSH servers are still unverified end to end.

APT and dpkg actions are unavailable when those binaries are absent. Fedora does
not gain equivalent DNF maintenance operations. Overview/logrotate require Python
3.8+ on remote hosts; the remote host does not need GTK or SysLogApp installed.
Hosts without systemd journal support cannot provide equivalent journal features.

## Repeatable checks

Run these in a desktop session using the system Python and a disposable account
or VM. The integration check requires openssh-server installed and an sshd able to
run as that account. Only loopback test commands are sent.

```bash
/usr/bin/python3 -W error::ResourceWarning -m unittest discover -s tests -q
/usr/bin/python3 -W error::ResourceWarning tests/ssh_integration_check.py
/usr/bin/python3 scripts/build_release.py
/usr/bin/python3 scripts/check_release.py dist/preview67
lintian --tag-display-limit 0 dist/preview67/*.deb
```

For each native distro VM before claiming support:

1. Record OS, architecture, Python, GTK, OpenSSH and display backend versions.
2. Install dependencies and perform a clean install, launch from the desktop,
   close/reopen, then upgrade with existing settings and saved host profiles.
3. On Debian-family VMs, install/upgrade/remove the .deb with the package manager;
   check menu entry/icon, dependencies, unchanged user settings and applet optionality.
4. Connect to a separate SSH target with a key, encrypted key and password;
   verify host trust, wrong credentials, reconnect, saved-password keyring and
   all five tabs. Check restricted journal/process access and missing tools.
5. Interrupt the connection during live reads and verify retained stale data,
   stopped polling and no automatic replay of maintenance actions.
6. Verify ordinary desktop use under X11 and Wayland where offered. Test any
   privileged maintenance changes only on disposable VMs with snapshots.

Release gate: Ubuntu, Debian and Fedora remain pending native validation. Do not
advertise them as tested based only on these Mint results.

## Preview 68 follow-up — 28 October 2026

All 292 GTK/unit tests passed with strict resource warnings on Mint. The loopback
OpenSSH test additionally verifies stderr on successful commands. Native distro
and real password/keyring verification gaps above remain unchanged.

## Preview 69 follow-up — 28 October 2026

All 309 GTK/unit tests passed with strict resource warnings on Mint. Display
filtering, hidden collection and original-preserving groups are tested with local
and simulated SSH host contexts; native distro verification gaps remain. No new
SSH command or authentication behavior is introduced.

## Preview 70 follow-up — 28 October 2026

All 310 GTK/unit tests passed with strict resource warnings on Mint, including
six isolated close/save-failure scenarios. No SSH or native-distro support claim
is added; previous validation gaps remain.

## Public Alpha 1 — 28 October 2026

Alpha 1 is the Preview 70 runtime with public release metadata and packaging.
Native distribution and real SSH password/keyring coverage above remains pending.
