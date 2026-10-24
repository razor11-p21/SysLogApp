// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 pit pitopoulos
const Applet = imports.ui.applet;
const Util = imports.misc.util;
const GLib = imports.gi.GLib;
const Gio = imports.gi.Gio;

class SysLogAppApplet extends Applet.IconApplet {
    constructor(metadata, orientation, panelHeight, instanceId) {
        super(orientation, panelHeight, instanceId);
        const localIcon = GLib.build_filenamev([GLib.get_home_dir(), ".local", "share", "syslogapp", "syslogapp", "assets", "syslogapp.svg"]);
        if (GLib.file_test(localIcon, GLib.FileTest.EXISTS)) {
            this.set_applet_icon_path(localIcon);
        } else {
            this.set_applet_icon_name("syslogapp");
        }
        this.set_applet_tooltip("Open SysLogApp — logs and network");
    }

    on_applet_clicked() {
        const application = Gio.DesktopAppInfo.new("syslogapp.desktop");
        if (application) {
            application.launch([], null);
            return;
        }
        const systemLauncher = "/usr/bin/syslogapp";
        const userLauncher = GLib.build_filenamev([GLib.get_home_dir(), ".local", "bin", "syslogapp"]);
        Util.spawn([GLib.file_test(systemLauncher, GLib.FileTest.IS_EXECUTABLE) ? systemLauncher : userLauncher]);
    }
}

function main(metadata, orientation, panelHeight, instanceId) {
    return new SysLogAppApplet(metadata, orientation, panelHeight, instanceId);
}
