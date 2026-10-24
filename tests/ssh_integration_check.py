#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
# Disposable loopback SSH server; no system config changes or maintenance actions.
import getpass,json,os,socket,subprocess,sys,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from syslogapp.hosts import SSHHost
from syslogapp.network import snapshot
from syslogapp.services import load_logs
with tempfile.TemporaryDirectory(prefix='syslogapp-sshtest-') as temporary:
 directory=Path(temporary)
 for name in ('host','client','otherhost'):
  subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(directory/name)],check=True)
 with socket.socket() as sock:
  sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 public=(directory/'host.pub').read_text().strip()
 known=directory/'known_hosts';known.write_text(f'[127.0.0.1]:{port} {public}\n')
 subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','fixture-passphrase','-f',str(directory/'encrypted')],check=True)
 with (directory/'client.pub').open('a') as authorized:
  authorized.write((directory/'encrypted.pub').read_text())
 config=directory/'sshd_config'
 config.write_text(f'''Port {port}
ListenAddress 127.0.0.1
HostKey {directory/'host'}
PidFile {directory/'pid'}
AuthorizedKeysFile {directory/'client.pub'}
StrictModes no
PasswordAuthentication no
KbdInteractiveAuthentication no
UsePAM no
PermitRootLogin no
AllowUsers {getpass.getuser()}
LogLevel ERROR
''')
 log=open(directory/'server.log','w+')
 server=subprocess.Popen(['/usr/sbin/sshd','-D','-e','-f',str(config)],stdout=log,stderr=log)
 host=None
 try:
  for _ in range(40):
   if server.poll() is not None:
    log.seek(0);raise RuntimeError(log.read())
   with socket.socket() as connection:
    if connection.connect_ex(('127.0.0.1',port))==0:break
   time.sleep(.05)
  wrong=directory/'wrong_hosts'
  wrong.write_text(f'[127.0.0.1]:{port} '+(directory/'otherhost.pub').read_text())
  rejected=SSHHost(dict(label='Wrong key test',hostname='127.0.0.1',username=getpass.getuser(),
                       port=port,auth='key',key_file=str(directory/'client')),known_hosts=wrong)
  try:
   rejected.connect()
   raise AssertionError('Changed host key was accepted')
  except RuntimeError as error:
   assert 'HOST IDENTIFICATION HAS CHANGED' in str(error),str(error)
  finally: rejected.close()
  print('Changed host key rejected')
  host=SSHHost(dict(label='Isolated SSH test',hostname='127.0.0.1',username=getpass.getuser(),
                   port=port,auth='key',key_file=str(directory/'client')),known_hosts=known)
  host.connect()
  print('Connected',host.connected,'tools',sorted(host.tools))
  print('Quoted argv',host.capture(['printf','%s',"literal; $(not-a-command) ' quote"])[0])
  print('Overview rows',len(host.overview()['rows']))
  data=snapshot(True,host=host)
  print('Network sockets',len(data['sockets'] or []),'errors',data['errors'])
  print('Journal rows',len(load_logs(100,host=host)))
  proc=host.popen(['sh','-c','printf "live-test\\n"; sleep 20'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True)
  print('Stream',proc.stdout.readline().strip())
  code,text=host.maintenance(['printf','%s','read-only maintenance transport test'])
  print('Maintenance transport',code,text)
  chunks=[]
  stream_code,stream_text=host.maintenance(['printf','%s','read-only streamed transport'],on_output=chunks.append,timeout=5)
  assert stream_code==0 and stream_text=='read-only streamed transport'
  assert ''.join(chunks)==stream_text
  print('Read-only streamed maintenance transport verified')
  master=host.control
  host.close()
  proc.wait(timeout=5)
  print('Disconnected',not host.connected,'control removed',not Path(master).exists(),'stream exited',proc.returncode)
  helper=directory/'fixture-askpass'
  helper.write_text('#!/bin/sh\ncase "$1" in *yes/no*) printf "yes\\n" ;; *) printf "%s\\n" "fixture-passphrase" ;; esac\n')
  helper.chmod(0o700)
  encrypted=SSHHost(dict(label='Encrypted key test',hostname='127.0.0.1',username=getpass.getuser(),
                      port=port,auth='key',key_file=str(directory/'encrypted')),known_hosts=directory/'new_known_hosts')
  encrypted.askpass=str(helper)
  try:
   encrypted.connect()
   assert encrypted.capture(['printf','%s','encrypted-key-ok'])[0]=='encrypted-key-ok'
   assert (directory/'new_known_hosts').exists()
   print('New host trust and encrypted-key askpass authenticated')
  finally: encrypted.close()
  import threading
  marker=directory/'prompt-started'
  slow=directory/'slow-askpass'
  slow.write_text('#!/bin/sh\ntouch '+str(marker)+'\nsleep 30\n')
  slow.chmod(0o700)
  cancelled=SSHHost(dict(label='Cancel auth test',hostname='127.0.0.1',username=getpass.getuser(),
                        port=port,auth='key',key_file=str(directory/'encrypted')),known_hosts=known)
  cancelled.askpass=str(slow)
  errors=[]
  def login():
   try:cancelled.connect()
   except Exception as error:errors.append(str(error))
  worker=threading.Thread(target=login)
  worker.start()
  for _ in range(100):
   if marker.exists():break
   time.sleep(.02)
  assert marker.exists(),'Askpass did not start'
  cancelled.close()
  worker.join(5)
  assert not worker.is_alive(),'Cancelled SSH authentication did not stop'
  assert errors
  print('Cancelled authentication exited and cleaned up')


 finally:
  if host:host.close()
  server.terminate()
  try:server.wait(timeout=5)
  except subprocess.TimeoutExpired:server.kill();server.wait()
  log.close()
