# Copyright and attribution

Copyright (C) 2026 pit pitopoulos.

SysLogApp, its installer, and its optional Cinnamon applet are distributed under
GNU GPL version 3 or (at your option) any later version. See LICENSE for the full
GPL version 3 text.

SysLogApp uses the following separately installed projects. Their code is not
bundled in the SysLogApp packages, and each retains its own license:

- Python: https://www.python.org/ — Python Software Foundation license.
- GTK3, GLib/GIO, and Pango: https://www.gtk.org/ — LGPL family licenses.
- PyGObject: https://pygobject.gnome.org/ — LGPL-2.1-or-later.
- Cairo and Pycairo: https://www.cairographics.org/ — see their license notices.
- psutil: https://github.com/giampaolo/psutil — BSD-3-Clause.
- Cinnamon (optional applet host): https://github.com/linuxmint/cinnamon — GPL-2.0-or-later.
- systemd, iproute2, iputils, glibc/getent, polkit, APT, and dpkg are invoked as
  host tools and remain subject to their respective project licenses.

The application uses the desktop's existing system-monitor icon. No upstream
icon artwork is bundled. The dashboard concept image is excluded from release
packages; it is not an application screenshot.
