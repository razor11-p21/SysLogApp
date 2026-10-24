# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
TERMINAL = r"""
window, .app-root { background: #101411; color: #c6d4c9; font-family: monospace; font-size: 13px; }
* { transition: none; animation: none; box-shadow: none; text-shadow: none; }
.host-sidebar { border-right: 1px solid #36483b; }
.host-sidebar list, .host-sidebar row { background: #101411; color: #c6d4c9; }
.host-sidebar row:selected { background: #294432; color: #91d89d; }
.terminal-title { color: #91d89d; font-size: 14px; font-weight: bold; }
.muted, .status-line { color: #96a79a; }
.status-line { padding: 6px 12px; border-top: 1px solid #2b3930; font-size: 11px; }
.toolbar-card { border-top: 1px solid #2b3930; border-bottom: 1px solid #2b3930; padding: 2px; }
button, entry, combobox button { background: #171e19; color: #c6d4c9; border: 1px solid #36483b; border-radius: 0; min-height: 22px; padding: 2px 6px; }
button:hover, button:checked { background: #263c2c; color: #b5edbf; }
/* ComboBox popups are separate GTK menus, outside the toolbar widget tree. */
menu, .context-menu, combobox window.popup, combobox window.popup > * {
  background: #171e19; color: #c6d4c9; border: 1px solid #36483b;
  border-radius: 0; font-family: monospace; font-size: 13px;
}
menu { padding: 3px; }
menuitem { background: transparent; color: #c6d4c9; padding: 5px 10px; border: 0; }
menuitem label, menuitem cellview { color: inherit; font-family: monospace; font-size: 13px; }
menuitem:hover, menuitem:selected { background: #263c2c; color: #b5edbf; }
menuitem:disabled { color: #68766c; }
menu separator { background: #36483b; min-height: 1px; margin: 3px 0; }
combobox window.popup treeview { background: #171e19; color: #c6d4c9; }
combobox window.popup treeview:selected { background: #263c2c; color: #b5edbf; }
entry:focus { border-color: #91d89d; }
button:disabled { color: #68766c; }
treeview, textview, textview text { background: #101411; color: #c6d4c9; }
treeview { -GtkTreeView-horizontal-separator: 2; -GtkTreeView-vertical-separator: 0; }
.network-table header button { color: #c8dff3; border-right: 1px solid #2b3930; }
treeview:selected { background: #294432; color: #e6f5e9; }
treeview header button { background: #171e19; color: #96a79a; border-width: 0 0 1px; border-color: #2b3930; padding: 2px; }
.section-card { background: #101411; border: 1px solid #2b3930; border-radius: 0; }
.section-title { color: #91d89d; font-weight: bold; }
.detail-text { padding: 8px; }
.active-live { color: #91d89d; border-color: #91d89d; }
.fetch-logo { color: #91d89d; padding: 4px 10px 4px 0; font-weight: bold; }
paned separator { background: #36483b; min-width: 4px; min-height: 4px; }
.maintenance-change { color: #ffb34c; }
.maintenance-error { color: #ff8188; }
.maintenance-read { color: #6aa8ff; }
checkbutton:checked { color: #91d89d; }
.paused-live { color: #e4bd72; }
notebook, notebook > stack { background: #101411; }
notebook > header { background: #101411; border-bottom: 1px solid #2b3930; }
notebook > header tabs tab { background: #171e19; color: #96a79a; padding: 5px 12px; border: 0; border-radius: 0; }
notebook > header tabs tab:checked { color: #91d89d; background: #263c2c; }
/* Mint themes draw dashed undershoot borders at scrollable edges. */
scrolledwindow undershoot { border: none; background-image: none; background-color: transparent; box-shadow: none; }
scrollbar trough { background: #101411; }
scrollbar slider { background: #36483b; min-width: 7px; min-height: 7px; border-radius: 0; }
"""
