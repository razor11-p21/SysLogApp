# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 pit pitopoulos
"""Temporary askpass handoff through a private Unix socket, never a secret file."""
import json
import os
import socket
from pathlib import Path

MAX_PACKET = 32768


def send(password=None):
    address = os.environ.get('SYSLOGAPP_SSH_PENDING')
    if not address:
        return False
    packet = json.dumps({'password': password}).encode('utf-8')
    if len(packet) > MAX_PACKET:
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
            channel.settimeout(1)
            channel.sendto(packet, address)
        return True
    except OSError:
        return False


class PendingPassword:
    def __init__(self, directory):
        self.path = Path(directory) / 'pending-password'
        self.channel = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        bound = False
        try:
            self.channel.setblocking(False)
            self.channel.bind(str(self.path))
            bound = True
            self.path.chmod(0o600)
        except BaseException:
            self.channel.close()
            if bound:
                self.path.unlink(missing_ok=True)
            raise

    def take(self):
        password = None
        # SSH has at most three prompts; bound malformed/excess handoffs too.
        for _ in range(16):
            try:
                data = self.channel.recv(MAX_PACKET + 1)
            except BlockingIOError:
                break
            if len(data) > MAX_PACKET:
                password = None
                continue
            try:
                value = json.loads(data).get('password')
                password = value if isinstance(value, str) and len(value) <= 4096 else None
            except (ValueError, TypeError, AttributeError):
                password = None
        return password

    def close(self):
        self.channel.close()
        self.path.unlink(missing_ok=True)
