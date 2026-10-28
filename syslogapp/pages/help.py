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
    ('Display filters and repeats',
     'System logs → Display filters hides exact service/source names (comma-separated, up to 32) or '
     'messages containing a literal, case-insensitive text fragment. Right-click → Hide This Service/Message '
     'fills these controls. Clear display filters restores them without another host query. '
     'Group consecutive repeats is off by default. Matching source, severity, message and process/boot identity '
     'produce a [×N] row; intervening events break a run. Open details for each original timestamp/message, '
     'or turn grouping off to inspect individual rows. Copy Event includes all group members; bookmarking '
     'a group keeps its first event. Exports expand groups into original events, including all events in '
     'a selected group. Saved views retain these display settings for the host. '
     'While System logs is hidden, live collection stays bounded but table updates and wrapping wait '
     'until you return. Returning renders the retained history without another query.'),
    ('Log limit',
     'Choose how many recent journal entries to load: default 400, up to 2000. The choice is remembered on close. '
     'Byte limits still apply, so unusually large entries can reduce the retained count.'),
    ('Log hover preview',
     'Keep the mouse still over a log row for two seconds to see its preview. '
     'Moving, clicking, scrolling or leaving hides it. Full details are available by opening the event.'),
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
     'Right-click a row for service and severity filters. History… searches a chosen time range and optional literal message on the selected host only after Search. '
     'Choose Previous Boot to inspect the preceding boot. Older replaces the page with earlier matching entries; Live or ⋯ → Return to recent logs returns to recent events. '
     'Custom dates use this computer’s local timezone. Entries above 64 KiB are omitted with a count; retained history and the live inbox each have a 4 MiB serialized-data budget. Original journal entries are unchanged.'),
    ('Overview',
     'The opening summary shows host, system, uptime, CPU, memory and root disk usage. '
     'Notices stay visible above it. Expand System details for kernel, load, swap, services and filesystems. '
     'Copy snapshot includes the full collected snapshot, even when details are collapsed. '
     'Expanding does not collect data; Refresh updates the snapshot. '
     'RAM shows available / total for the selected host, not SysLogApp. Available includes reclaimable memory. '
     'System details separates estimated used RAM and occupied swap. Swap occupancy does not measure current swapping; '
     'Disabled means no swap is configured, while Unavailable means the check could not be completed.'),
    ('Network',
     'Network opens with Live, Connections and Basic process details selected. Live updates while the tab is visible; Refresh collects one snapshot. '
     'Dragging to select text pauses Live so connections do not disappear during selection; press F7 to resume. '
     'Hide TIME-WAIT removes those connections. Choose Process details: Basic or Extended, then Refresh to collect process details. '
     'Extended shows full loaded process metadata without another scan. The Live / Paused button or F6/F7 toggles monitoring. Interfaces & routes expands the interface summary. Automatic sockets refresh every two seconds; interfaces/routes are reused for 30 seconds with their collection time shown. Refresh updates everything. If a socket read fails, the previous connections stay visible with an amber Stale status and last successful update time. A first failed read says unavailable; a successful read clears the warning.'),
    ('Connection filters and related logs',
     'Expand Connection filters in Network. App matches literal process-name text without case sensitivity; '
     'PID and Port match whole numbers exactly. Choose either, local or remote port. '
     'Filters combine with search, connection type and Hide TIME-WAIT and operate on loaded rows only. '
     'App and PID must match the same owner on shared sockets. If ownership is unavailable, select Basic/Extended and Refresh; '
     'permissions can still limit visibility. Select a connection, then Process details or Related logs to open verified on-demand inspection. '
     'Opening pauses Live. Saved views and export metadata retain these criteria.'),
    ('Exporting and sharing',
     'System logs: ⋯ → Export logs…; Network: ⋯ → Export connections…. Live pauses and the displayed rows are frozen. '
     'Choose selected entries (whole rows touched by text selection) or all filtered loaded entries. '
     'JSONL preserves all collected raw fields when redaction is off, plus source/filters/timezone metadata; it does not fetch additional journal fields. '
     'CSV quotes cells and prefixes formula-like text with an apostrophe. JSONL is the fidelity option. '
     'Optional IP, hostname, username and custom-text redaction is best effort; review before sharing. Binary fields are omitted while redacting. '
     'Preview export runs only when clicked; Previous/Next pages cover the whole file. Changed options require a new preview before Save. '
     'Files are local, atomic and user-only. No remote query or background work is added.'),
    ('Connection details and service logs',
     'Network: right-click a connection → Process details… or Related service logs… (also in ⋯). '
     'Inspection pauses Network. The dialog verifies current socket ownership before showing executable, command, UID, parent PID, memory and unit. '
     'Choose a PID/descriptor when several processes share a connection. Refresh details repeats the read; nothing polls in the dialog. '
     'Service logs loads related, boot-scoped journal entries only when opened, with UID scoping for user services. '
     'Text wraps, supports mouse selection and native Copy; Copy shown text copies the active readout. '
     'Unavailable or changed owners are reported. TIME-WAIT often has no owner. Basic/Extended plus Refresh collects visible process ownership. '
     'SSH inspection requires Python 3.8+, readable /proc and journal permissions for related logs.'),
    ('Saved views and bookmarks',
     'System logs and Network: ⋯ → Save view… names the current filters; ⋯ → Saved views & bookmarks… applies or removes them. '
     'Views belong to the selected host and tab, and restore in Paused mode. Saved log date ranges stay fixed. '
     'Network views filter loaded sockets; Refresh updates collected process details. '
     'In System logs, right-click → Bookmark event… saves the selected original message and its journal reference locally. '
     'The manager shows saved text even after rotation; Locate event checks the exact entry on demand. '
     'Long messages keep a labelled 8 KiB excerpt. Items are stored in a private local file, with limits of 100 views and 100 bookmarks; no background query is added.'),
    ('Columns and layout',
     'Click a column header to sort; click again to reverse. Drag a header divider to resize. Network widths stay steady between snapshots to avoid refresh flicker. '
     '⋯ → Fit columns restores automatic widths. ⋯ → Export logs opens a preview with JSONL/CSV and redaction options. Window size and manual column widths are saved on normal close. '
     'If settings cannot be saved, Retry tries again, Keep open returns to the app, and Close without saving exits without another save attempt. '
     'Dismissing the error dialog keeps the app open.'),
    ('Overview and Maintenance',
     'Overview is a manual snapshot with no background sampling. It lists mounted filesystem capacity and failed system services. '
     'Virtual mounts shows retained kernel mounts without another read; capacity is not applicable for them. '
     'Network/FUSE on Refresh enables their usage checks only after Refresh. Missing, timed-out and unchecked data is labelled explicitly. '
     'Select a failed Service row → Show service logs (also Enter/right-click) to open that unit on the same host. '
     'Reboot notices use supported system markers; no notice reported does not guarantee no reboot is needed. '
     'Maintenance runs only the action you choose; '
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
     'Reconnect keeps the current tab, filters and retained data; stale data stays marked until refreshed. Maintenance is never repeated automatically. '
     'Password prompts offer Remember password in the desktop keyring after successful authentication. Edit host → Forget saved password removes it. '
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
