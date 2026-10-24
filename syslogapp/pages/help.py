# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Static, selectable help shared by local and SSH hosts; no background work."""
from gi.repository import Gtk

SHORTCUTS = (
    ('F1', 'Open Help'),
    ('F5', 'Refresh the current tab'),
    ('Ctrl+F', 'Search System logs or Network'),
    ('F6', 'Turn Live on / off (System logs and Network)'),
    ('F7', 'Pause / resume Live (System logs and Network)'),
    ('Ctrl+C', 'Copy selected text; when a table has focus, copy its selected row'),
    ('Ctrl+A', 'Select all shown table text, or all text in the focused readout/input'),
    ('Esc', 'Clear text selection; press again to close event details'),
    ('Ctrl+1 … Ctrl+5', 'System logs · Network · Overview · Maintenance · Help'),
    ('Ctrl+B', 'Show / hide the host sidebar'),
)

GUIDE = (
    ('Select and copy',
     'Press and drag over text to select the characters you want. Continue dragging across columns and '
     'log entries to select several lines, then press Ctrl+C or right-click Copy selected text. '
     'Text remains visible and read-only. Drag near the top or bottom edge to scroll while selecting. '
     'Double-click selects a word; triple-click selects a row. Ctrl+A selects all shown text, '
     'and Esc clears the selection. A single click selects a row; double-click a log event or press Enter to open its details.\n\n'
     'Right-click for Copy cell, Copy row and Copy all shown rows. '
     'Sorting, filters and visible columns determine which rows and fields are included.'),
    ('System logs',
     'New events appear last when sorted by time ascending. The Live / Paused button or F6/F7 starts or stops live journal updates. '
     'Dragging to select text pauses Live and keeps the displayed rows still; press F7 to resume. '
     'History remains bounded, so sufficiently old entries can expire. '
     'Double-click an event or press Enter for details; Esc closes them. Search filters loaded events. '
     'Right-click a row for service and severity filters.'),
    ('Network',
     'Network opens with Live, Connections and Basic process details selected. Live updates while the tab is visible; Refresh collects one snapshot. '
     'Dragging to select text pauses Live so connections do not disappear during selection; press F7 to resume. '
     'Hide TIME-WAIT removes those connections. Choose Process details: Basic or Extended, then Refresh to collect process details. '
     'Extended shows full loaded process metadata without another scan. The Live / Paused button or F6/F7 toggles monitoring. Interfaces & routes expands the interface summary.'),
    ('Columns and layout',
     'Click a column header to sort; click again to reverse. Drag a header divider to resize. Network widths stay steady between snapshots to avoid refresh flicker. '
     '⋯ → Fit columns restores automatic widths. ⋯ → Export logs saves the shown journal rows as CSV. Window size and manual column widths are saved on normal close.'),
    ('Overview and Maintenance',
     'Overview is a manual snapshot with no background sampling. Maintenance runs only the action you choose; '
     'changes require confirmation and administrator authentication. F5 refreshes command availability in Maintenance. '
     'Text log rotation configures logrotate; saving does not rotate files. '
     'Maintenance has grouped actions and a collapsed Advanced section for network restart and package repair. '
     'The output pane streams command output and shows elapsed time and exit status. ⋯ offers Copy, Save and Clear. '
     'The history selector keeps the last ten results across hosts for this session. '
     'Vacuum journal reads current usage before reviewing an age/size cleanup policy. '
     'The rotation editor has a summary, config preview and Validate only action that changes no files. '
     'Remote network restart can disconnect SSH. Maintenance output supports mouse selection, Ctrl+A, Ctrl+C and right-click Copy.'),
    ('Local and SSH hosts',
     'Use Hosts or Ctrl+B to show the sidebar. Add an SSH host, choose password or key authentication, then Connect. '
     'Password prompts offer Remember password in the desktop keyring. Edit host → Forget saved password removes it. '
     'Key passphrases, verification codes and sudo passwords are not saved. '
     'The host name above the tabs identifies the current target. All shortcuts and selection controls work the same '
     'locally and remotely. Available commands, permissions and journal support depend on the selected Linux host. '
     'Help performs no local or remote commands.'),
    ('Other familiar keys',
     'Ctrl+R also refreshes; Ctrl+K also focuses search. Tab / Shift+Tab moves between controls. '
     
     'Shortcuts never execute a maintenance action or initiate an SSH connection.'),
)


class HelpPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_border_width(8)
        self.text = Gtk.TextView()
        self.text.set_editable(False)
        self.text.set_cursor_visible(True)
        self.text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text.set_left_margin(10)
        self.text.set_right_margin(10)
        self.text.set_bottom_margin(20)
        buffer = self.text.get_buffer()
        heading = buffer.create_tag('heading', foreground='#91d89d', weight=700, pixels_above_lines=12)
        key = buffer.create_tag('key', foreground='#6aa8ff')
        buffer.insert_with_tags(buffer.get_end_iter(), 'Keyboard shortcuts\n', heading)
        for shortcut, action in SHORTCUTS:
            buffer.insert_with_tags(buffer.get_end_iter(), shortcut + '\n', key)
            buffer.insert(buffer.get_end_iter(), '  ' + action + '\n')
        for name, description in GUIDE:
            buffer.insert_with_tags(buffer.get_end_iter(), '\n' + name + '\n', heading)
            buffer.insert(buffer.get_end_iter(), description + '\n')
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.text)
        self.pack_start(scroll, True, True, 0)
        self.connect('map', lambda *_: self.text.grab_focus())
