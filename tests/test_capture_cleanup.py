# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from syslogapp.network import capture


class CaptureCleanupTests(unittest.TestCase):
    def test_timeout_cleans_descendant_even_when_parent_already_exited(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'pid'
            child = 'import os,time,pathlib; pathlib.Path(' + repr(str(pidfile)) + ').write_text(str(os.getpid())); time.sleep(30)'
            parent = 'import subprocess,sys; subprocess.Popen([sys.executable,"-c",' + repr(child) + '])'
            try:
                with self.assertRaises(TimeoutError):
                    capture([sys.executable, '-c', parent], timeout=.5)
                self.assertTrue(pidfile.exists())
                pid = int(pidfile.read_text())
                for _ in range(30):
                    status = Path(f'/proc/{pid}/stat')
                    if not status.exists() or status.read_text().split(') ', 1)[1].startswith('Z'):
                        break
                    time.sleep(.01)
                else:
                    self.fail('Read-only helper descendant survived capture timeout')
            finally:
                if pidfile.exists():
                    try:
                        os.kill(int(pidfile.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
