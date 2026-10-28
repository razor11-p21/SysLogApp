# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
import json
from pathlib import Path
import shlex
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from syslogapp.hosts import SSHHost,HostContext,host_profile
from syslogapp import config,network,services
from syslogapp.maintenance import ACTIONS,Action

PROFILE=dict(label='Server',hostname='server.example',username='alice',port=2222,auth='key',key_file='')


class HostTests(unittest.TestCase):
    def host(self):
        host=SSHHost(PROFILE)
        self.addCleanup(host.close)
        return host

    def test_profiles_reject_option_and_shell_injection_and_drop_secrets(self):
        for hostname in ('-oProxyCommand=bad','server;touch /tmp/anything','host$(id)','server\n-oBatchMode=no'):
            with self.assertRaises(ValueError):host_profile(dict(PROFILE,hostname=hostname))
        safe=host_profile(dict(PROFILE,hostname='2001:db8::1',password='secret',passphrase='secret',private_key='secret'))
        self.assertNotIn('secret',json.dumps(safe))
        saved=config.normalized({'hosts':[dict(PROFILE,password='secret'),{'hostname':'-bad'}]})
        self.assertEqual(len(saved['hosts']),1)
        self.assertNotIn('secret',json.dumps(saved))

    def test_nonfinite_saved_ports_are_rejected_without_breaking_settings(self):
        for port in (float('inf'), float('-inf'), float('nan')):
            with self.assertRaises(ValueError):
                host_profile(dict(PROFILE, port=port))
            settings = config.normalized({'hosts': [dict(PROFILE, port=port), PROFILE]})
            self.assertEqual(len(settings['hosts']), 1)

    def test_command_quotes_remote_arguments_and_cannot_reconnect_implicitly(self):
        host=self.host()
        host.connected=True
        text="literal; $(do-not-run) ' quote"
        command=host.command(['printf','%s',text])
        self.assertEqual(shlex.split(command[-1])[-3:],['printf','%s',text])
        self.assertIn('ProxyCommand=false',command)
        self.assertIn('BatchMode=yes',command)
        self.assertIn('ForwardAgent=no',command)
        self.assertIn('ClearAllForwardings=yes',command)
        self.assertIn('StrictHostKeyChecking=yes',command)

    def test_sudo_and_rotation_commands_target_remote_helpers(self):
        host=self.host()
        host.tools={'sudo':'/usr/bin/sudo','python3':'/usr/bin/python3','logrotate':'/usr/sbin/logrotate',
                    'journalctl':'/usr/bin/journalctl'}
        host.uid=1000
        host.python_version=(3,12)
        args,error=host.resolve_action(ACTIONS[1])
        self.assertFalse(error)
        self.assertEqual(args[:5],['/usr/bin/sudo','-S','-p','','--'])
        self.assertIn('exec "$@" </dev/null',args)
        self.assertEqual(args[-2:],['/usr/bin/journalctl','--vacuum-time=7d'])
        action=Action('Rotation','test',('/usr/bin/python3','/local/syslogapp/logrotate_config.py','--path','/var/log/a.log'))
        args,error=host.resolve_action(action)
        self.assertFalse(error)
        self.assertIn('-c',args)
        self.assertNotIn('/local/syslogapp/logrotate_config.py',args)
        self.assertTrue(any('def apply_config' in arg for arg in args))

    def test_missing_remote_tools_disable_unsupported_actions(self):
        host=self.host()
        args,reason=host.resolve_action(ACTIONS[2])
        self.assertIsNone(args)
        self.assertIn('apt-get',reason)
        with self.assertRaisesRegex(RuntimeError,'Python 3'):
            host.overview()

    def test_stale_host_callbacks_are_ignored(self):
        app=SimpleNamespace(config={},window=None,_closing=False,run_async=Mock())
        context=HostContext(app,Mock())
        callback=Mock()
        context.run_async(lambda:42,callback)
        complete=app.run_async.call_args.args[1]
        context.active=False
        complete(42,None)
        callback.assert_not_called()

    def test_network_and_journal_use_remote_capture_not_local_commands(self):
        def capture(args,**kwargs):
            if args[0]=='ip':return '[]',False
            if args[0]=='ss':return 'tcp ESTAB 0 0 10.0.0.1:1 192.0.2.1:2\n',False
            if args[0]=='journalctl':return json.dumps({'MESSAGE':'remote marker','PRIORITY':'6'}),False,''
            raise AssertionError(args)
        remote=SimpleNamespace(capture=Mock(side_effect=capture))
        with patch.object(network,'capture',side_effect=AssertionError('local scan')), \
             patch.object(services,'run_command',side_effect=AssertionError('local journal')):
            data=network.snapshot(host=remote)
            logs=services.load_logs(100,host=remote)
        self.assertEqual(data['sockets'][0]['local'],'10.0.0.1:1')
        self.assertEqual(logs[0]['message'],'remote marker')
        self.assertEqual(remote.capture.call_count,5)

    def test_remote_overview_executes_collector_on_remote(self):
        host=self.host()
        host.tools={'python3':'/remote/python3'}
        host.python_version=(3,12)
        with patch.object(host,'capture',return_value=(json.dumps({'rows':[['Host','remote','#6aa8ff']],'time':'now'}),False)) as capture:
            result=host.overview()
        args=capture.call_args.args[0]
        self.assertEqual(args[:2],['/remote/python3','-c'])
        self.assertIn('/proc/meminfo',args[2])
        self.assertEqual(result['rows'][0][1],'remote')

    def test_disconnect_rejects_further_commands(self):
        host=self.host()
        host.close()
        with self.assertRaises(RuntimeError):host.command(['true'])
        self.assertFalse(Path(host.control).exists())

    def test_sidebar_remote_local_switch_in_isolated_gtk_process(self):
        try:
            import gi
            gi.require_version('Gtk','3.0')
            from gi.repository import Gtk
            if not Gtk.init_check()[0]:self.skipTest('GTK desktop required')
        except ImportError:
            self.skipTest('GTK unavailable')
        import sys
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('ssh_ui_check.py'))],
                              capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertNotIn('CRITICAL',result.stderr)

    def test_ipv6_profiles_accept_compressed_and_bracketed_addresses(self):
        self.assertEqual(host_profile(dict(PROFILE,hostname='[::1]'))['hostname'],'::1')
        self.assertEqual(host_profile(dict(PROFILE,hostname='fe80::1%eth0'))['hostname'],'fe80::1%eth0')
        with self.assertRaises(ValueError):host_profile(dict(PROFILE,hostname='host:2222'))

    def test_password_mode_uses_askpass_without_password_in_argv_or_environment(self):
        host=SSHHost(dict(PROFILE,auth='password'))
        self.addCleanup(host.close)
        process=Mock()
        process.wait.return_value=0
        with patch.object(host,'_spawn',return_value=process) as spawn,patch.object(host,'_probe'), patch.object(host, '_watch_master'):
            host.connect()
        command=spawn.call_args.args[0]
        environment=spawn.call_args.kwargs['env']
        self.assertIn('PreferredAuthentications=keyboard-interactive,password',command)
        self.assertIn('StrictHostKeyChecking=ask',command)
        self.assertIn('PubkeyAuthentication=no',command)
        self.assertEqual(environment['SSH_ASKPASS_REQUIRE'],'force')
        self.assertEqual(environment['SSH_ASKPASS'],host.askpass)
        self.assertFalse(any(key.lower() in ('password','ssh_password','sshpass') for key in environment))

    def test_askpass_password_and_host_confirmation_are_explicit(self):
        try:
            from syslogapp import ssh_askpass
        except ImportError:
            self.skipTest('GTK unavailable')
        import io
        from contextlib import redirect_stdout
        gtk=Mock()
        gtk.Dialog.return_value.run.return_value=gtk.ResponseType.OK
        gtk.Entry.return_value.get_text.return_value='fixture-secret'
        output=io.StringIO()
        with patch.object(ssh_askpass,'Gtk',gtk),patch.object(ssh_askpass,'Gdk',Mock()), \
             patch.object(ssh_askpass.sys,'argv',['askpass',"alice@server's password:"]), \
             redirect_stdout(output):
            self.assertEqual(ssh_askpass.main(),0)
        self.assertEqual(output.getvalue(),'fixture-secret\n')
        gtk.Entry.return_value.set_visibility.assert_called_once_with(False)
        gtk.Entry.return_value.set_text.assert_called_once_with('')
        output=io.StringIO()
        gtk.MessageDialog.return_value.run.return_value=gtk.ResponseType.NO
        with patch.object(ssh_askpass,'Gtk',gtk),patch.object(ssh_askpass,'Gdk',Mock()), \
             patch.object(ssh_askpass.sys,'argv',['askpass','Trust this fingerprint? (yes/no)']), \
             redirect_stdout(output):
            self.assertEqual(ssh_askpass.main(),1)
        self.assertEqual(output.getvalue(),'')

    def test_remote_maintenance_worker_never_runs_local_action(self):
        from syslogapp.pages.maintenance import MaintenancePage
        remote=Mock()
        remote.maintenance.return_value=(0,'remote-result')
        page=SimpleNamespace(host=remote,_sudo_password='fixture-secret',_destroyed=False,
                             app=SimpleNamespace(_closing=False),_done=Mock())
        with patch('syslogapp.pages.maintenance.run_action',side_effect=AssertionError('local action')), \
             patch('syslogapp.pages.maintenance.GLib.idle_add') as idle:
            MaintenancePage._worker(page,ACTIONS[1],['remote-journalctl','--vacuum-time=7d'])
        remote.maintenance.assert_called_once_with(['remote-journalctl','--vacuum-time=7d'],'fixture-secret')
        self.assertIsNone(page._sudo_password)
        self.assertEqual(idle.call_args.args[2],(0,'remote-result'))

    def test_maintenance_confirmation_names_the_target_host(self):
        from syslogapp.pages.maintenance import MaintenancePage
        page=SimpleNamespace(host=SimpleNamespace(target='alice@example:2222'),get_toplevel=Mock())
        with patch('syslogapp.pages.maintenance.Gtk.MessageDialog') as dialog:
            MaintenancePage._confirm(page,ACTIONS[1],['sudo','journalctl','--vacuum-time=7d'])
        self.assertIn('TARGET: alice@example:2222',dialog.return_value.format_secondary_text.call_args.args[0])
