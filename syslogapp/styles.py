# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
LIGHT = r'''
@define-color app_bg #f5f7fb;
@define-color sidebar_bg #202832;
@define-color card_bg #ffffff;
@define-color card_border #e3e8ef;
@define-color text_main #131923;
@define-color text_muted #667085;
@define-color accent #2878e8;
@define-color accent_soft #e8f1ff;
@define-color green #17a75b;
@define-color green_soft #e7f8ef;
@define-color orange #d98700;
@define-color orange_soft #fff3d7;
@define-color red #d9363e;
@define-color red_soft #ffe8ea;
@define-color purple #7b54d8;
@define-color purple_soft #f0eaff;

window, .app-root { background: @app_bg; color: @text_main; font-size: 13px; }
.app-root.compact .section-card { padding: 4px; }
.app-root.compact .metric-card box { padding: 10px; }

.sidebar { background: @sidebar_bg; color: #eef4fa; border-right: 1px solid #303944; }
.sidebar-title { color: #ffffff; font-size: 21px; font-weight: 700; }
.sidebar-subtitle { color: #aeb9c6; font-size: 12px; }
.nav-button { background: transparent; color: #e7edf4; border: 0; border-radius: 9px; padding: 12px 14px; box-shadow: none; text-shadow: none; font-size: 13px; }
.nav-button:hover { background: rgba(255,255,255,0.07); }
.nav-button.active { background: #315f9e; color: white; }
.sidebar-footer { background: rgba(0,0,0,0.12); border: 1px solid #3a4652; border-radius: 10px; padding: 12px; color: #eaf2f8; }

.topbar { background: rgba(255,255,255,0.96); border-bottom: 1px solid @card_border; padding: 10px 18px; }
.search-shell { background: #f7f9fc; border: 1px solid #d9e0e9; border-radius: 9px; padding: 4px 10px; }

.page-title { font-size: 32px; font-weight: 700; color: @text_main; }
.page-subtitle { font-size: 15px; color: @text_muted; }
.section-title { font-size: 18px; font-weight: 700; color: @text_main; }
.metric-title { font-size: 14px; font-weight: 600; color: @text_main; }
.metric-value { font-size: 24px; font-weight: 700; color: @text_main; }
.metric-status { font-size: 13px; font-weight: 600; }
.muted, .footer-text { color: @text_muted; }
.footer-text { font-size: 12px; }
.empty-text { color: @text_muted; font-style: italic; }
.action-title { font-size: 14px; font-weight: 600; color: @text_main; }

.metric-card, .section-card, .toolbar-card { background: @card_bg; border: 1px solid @card_border; border-radius: 12px; box-shadow: 0 1px 2px rgba(20,28,40,0.04); }
.metric-card:hover { border-color: #8fbaf2; }
.metric-card.clickable-card:hover, .section-card.clickable-hover { border-color: @accent; box-shadow: 0 2px 6px rgba(40,120,232,0.12); }
.issue-clickable:hover { background: #f5f9ff; }
.metric-icon, .section-icon { border-radius: 20px; padding: 8px; background: @accent_soft; color: @accent; }
.metric-icon.green { background: @green_soft; color: @green; }
.metric-icon.orange { background: @orange_soft; color: @orange; }
.metric-icon.red { background: @red_soft; color: @red; }
.metric-icon.purple { background: @purple_soft; color: @purple; }
.metric-icon.blue { background: @accent_soft; color: @accent; }
.section-icon { background: @accent_soft; color: @accent; }

.ok { color: @green; }
.warning { color: @orange; }
.error { color: @red; }
.info { color: @accent; }
.status-dot { font-size: 11px; }

.status-pill { border-radius: 14px; padding: 5px 10px; font-size: 12px; font-weight: 600; }
.status-pill.ok { background: @green_soft; color: @green; }
.status-pill.warning { background: @orange_soft; color: @orange; }
.status-pill.error { background: @red_soft; color: @red; }
.status-pill.info { background: @accent_soft; color: @accent; }
.level-badge { border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 600; }
.level-badge.error { background: @red_soft; color: @red; }
.level-badge.warning { background: @orange_soft; color: @orange; }
.level-badge.info { background: @accent_soft; color: @accent; }

.issue-row, .diagnostic-row, .maintenance-row, .settings-row { border-bottom: 1px solid #edf0f4; }
.issue-row:last-child, .diagnostic-row:last-child, .maintenance-row:last-child, .settings-row:last-child { border-bottom: 0; }

button { border-radius: 8px; padding: 8px 12px; font-size: 13px; }
entry { font-size: 13px; }
.primary-button { background: @accent; color: white; border-color: @accent; text-shadow: none; }
.secondary-button { background: #ffffff; color: @text_main; border: 1px solid #d8e0e9; text-shadow: none; }
.danger-soft { background: @red_soft; color: @red; border: 1px solid #ffcfd3; }
.active-live { background: @red_soft; color: @red; border-color: #ffc9ce; }
.paused-live { background: @orange_soft; color: @orange; border-color: #efd39b; }

.info-banner { background: @accent_soft; color: #24466e; border: 1px solid #cbdfff; border-radius: 10px; }
.detail-text { font-family: Monospace; font-size: 13px; background: #f8fafc; border: 1px solid #e6ebf1; border-radius: 8px; padding: 8px; }
.severity-critical { color: #b42318; font-weight: 600; }
.severity-error { color: #d92d20; font-weight: 600; }
.severity-warning { color: #b54708; font-weight: 600; }
.severity-notice { color: #6941c6; font-weight: 600; }
.severity-info { color: #175cd3; }
.severity-debug { color: #667085; }

treeview { background: @card_bg; color: @text_main; font-size: 13px; }
treeview header button { background: #f8fafc; color: @text_muted; border-bottom: 1px solid @card_border; font-weight: 600; font-size: 12px; }
treeview:selected { background: #dfeeff; color: #142033; }

@define-color graph_grid rgba(160,170,184,0.30);
@define-color graph_line #2684ff;
@define-color graph_fill rgba(38,132,255,0.14);
@define-color graph_text #687586;
@define-color graph_rx #2878e8;
@define-color graph_tx #17a75b;
.network-rx { color: #2878e8; font-weight: 600; }
.network-tx { color: #17a75b; font-weight: 600; }
.network-interface-row { background: #fbfcfe; border: 1px solid @card_border; border-radius: 10px; }
.network-switcher button { padding: 8px 16px; }
.network-switcher button:checked { background: @accent_soft; color: @accent; border-color: #b9d4fb; }
'''

DARK = r'''
@define-color app_bg #11161c;
@define-color sidebar_bg #171d24;
@define-color card_bg #1b222b;
@define-color card_border #2b3541;
@define-color text_main #f3f6f9;
@define-color text_muted #9aa8b7;
@define-color accent #5a9dff;
@define-color accent_soft #1e3654;
@define-color green #45cf7a;
@define-color green_soft #153d29;
@define-color orange #ffb34c;
@define-color orange_soft #493415;
@define-color red #ff6b73;
@define-color red_soft #4a2025;
@define-color purple #b28cff;
@define-color purple_soft #33264d;

window, .app-root { background: @app_bg; color: @text_main; font-size: 13px; }
.app-root.compact .section-card { padding: 4px; }
.sidebar { background: @sidebar_bg; color: #eef4fa; border-right: 1px solid #2b3541; }
.sidebar-title { color: #ffffff; font-size: 21px; font-weight: 700; }
.sidebar-subtitle { color: #98a6b5; font-size: 12px; }
.nav-button { background: transparent; color: #dbe4ed; border: 0; border-radius: 9px; padding: 12px 14px; box-shadow: none; text-shadow: none; font-size: 13px; }
.nav-button:hover { background: rgba(255,255,255,0.06); }
.nav-button.active { background: #244f83; color: white; }
.sidebar-footer { background: rgba(0,0,0,0.14); border: 1px solid #35414e; border-radius: 10px; padding: 12px; color: #eaf2f8; }
.topbar { background: #171d24; border-bottom: 1px solid @card_border; padding: 10px 18px; }
.search-shell { background: #202832; border: 1px solid #35414e; border-radius: 9px; padding: 4px 10px; }
.page-title { font-size: 32px; font-weight: 700; color: @text_main; }
.page-subtitle { font-size: 15px; color: @text_muted; }
.section-title { font-size: 18px; font-weight: 700; color: @text_main; }
.metric-title { font-size: 14px; font-weight: 600; color: @text_main; }
.metric-value { font-size: 24px; font-weight: 700; color: @text_main; }
.metric-status { font-size: 13px; font-weight: 600; }
.muted, .footer-text { color: @text_muted; }
.footer-text { font-size: 12px; }
.empty-text { color: @text_muted; font-style: italic; }
.action-title { font-size: 14px; font-weight: 600; color: @text_main; }
.metric-card, .section-card, .toolbar-card { background: @card_bg; border: 1px solid @card_border; border-radius: 12px; box-shadow: none; }
.metric-card:hover { border-color: #5378a6; }
.metric-card.clickable-card:hover, .section-card.clickable-hover { border-color: @accent; }
.issue-clickable:hover { background: #202a35; }
.metric-icon, .section-icon { border-radius: 20px; padding: 8px; background: @accent_soft; color: @accent; }
.metric-icon.green { background: @green_soft; color: @green; }
.metric-icon.orange { background: @orange_soft; color: @orange; }
.metric-icon.red { background: @red_soft; color: @red; }
.metric-icon.purple { background: @purple_soft; color: @purple; }
.metric-icon.blue { background: @accent_soft; color: @accent; }
.section-icon { background: @accent_soft; color: @accent; }
.ok { color: @green; } .warning { color: @orange; } .error { color: @red; } .info { color: @accent; }
.status-dot { font-size: 11px; }
.status-pill { border-radius: 14px; padding: 5px 10px; font-size: 12px; font-weight: 600; }
.status-pill.ok { background: @green_soft; color: @green; }
.status-pill.warning { background: @orange_soft; color: @orange; }
.status-pill.error { background: @red_soft; color: @red; }
.status-pill.info { background: @accent_soft; color: @accent; }
.level-badge { border-radius: 8px; padding: 3px 8px; font-size: 11px; font-weight: 600; }
.level-badge.error { background: @red_soft; color: @red; }
.level-badge.warning { background: @orange_soft; color: @orange; }
.level-badge.info { background: @accent_soft; color: @accent; }
.issue-row, .diagnostic-row, .maintenance-row, .settings-row { border-bottom: 1px solid #2a343f; }
button { border-radius: 8px; padding: 8px 12px; font-size: 13px; }
entry { font-size: 13px; }
.primary-button { background: #347fd7; color: white; border-color: #347fd7; text-shadow: none; }
.secondary-button { background: #202832; color: @text_main; border: 1px solid #364250; text-shadow: none; }
.danger-soft { background: @red_soft; color: @red; border: 1px solid #613137; }
.active-live { background: @red_soft; color: @red; border-color: #613137; }
.paused-live { background: @orange_soft; color: @orange; border-color: #6a4a20; }
.info-banner { background: @accent_soft; color: #cfe2ff; border: 1px solid #31547b; border-radius: 10px; }
.detail-text { font-family: Monospace; font-size: 13px; background: #131920; border: 1px solid #2d3743; border-radius: 8px; padding: 8px; }
.severity-critical { color: #ff6b73; font-weight: 600; }
.severity-error { color: #ff8188; font-weight: 600; }
.severity-warning { color: #ffb34c; font-weight: 600; }
.severity-notice { color: #b69cff; font-weight: 600; }
.severity-info { color: #6aa8ff; }
.severity-debug { color: #9aa8b7; }
treeview { background: @card_bg; color: @text_main; font-size: 13px; }
treeview header button { background: #202832; color: @text_muted; border-bottom: 1px solid @card_border; font-weight: 600; font-size: 12px; }
treeview:selected { background: #274f7d; color: white; }
@define-color graph_grid rgba(100,115,132,0.32);
@define-color graph_line #5a9dff;
@define-color graph_fill rgba(90,157,255,0.16);
@define-color graph_text #96a3b1;
@define-color graph_rx #5a9dff;
@define-color graph_tx #45cf7a;
.network-rx { color: #6aa8ff; font-weight: 600; }
.network-tx { color: #45cf7a; font-weight: 600; }
.network-interface-row { background: #171e26; border: 1px solid @card_border; border-radius: 10px; }
.network-switcher button { padding: 8px 16px; }
.network-switcher button:checked { background: @accent_soft; color: @accent; border-color: #31547b; }
'''
