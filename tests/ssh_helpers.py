"""Shared mock helpers for SSH-related unit tests."""

import threading
from unittest.mock import MagicMock

import paramiko

from pacsys.ssh import SSHClient, SSHHop

_RealTransport = paramiko.Transport


def make_mock_transport(active=True):
    t = MagicMock(spec=_RealTransport)
    t.is_active.return_value = active
    return t


def connected_ssh(mock_connect, mock_transport_cls, active=True):
    """Return a connected SSHClient with mocked transport."""
    mock_connect.return_value = MagicMock()
    mock_transport = make_mock_transport(active)
    mock_transport_cls.return_value = mock_transport
    ssh = SSHClient(SSHHop("host", auth_method="password", password="pw"))
    return ssh, mock_transport


def make_exec_channel(stdout=b"", stderr=b"", exit_code=0):
    """Create a mock channel that simulates one-shot command execution."""
    chan = MagicMock()
    chan.status_event = threading.Event()
    chan.status_event.set()

    stdout_returned = [False]
    stderr_returned = [False]

    def recv_ready():
        return not stdout_returned[0] and bool(stdout)

    def recv(size):
        stdout_returned[0] = True
        return stdout

    def recv_stderr_ready():
        return not stderr_returned[0] and bool(stderr)

    def recv_stderr(size):
        stderr_returned[0] = True
        return stderr

    def exit_status_ready():
        return stdout_returned[0] or not stdout

    chan.recv_ready = MagicMock(side_effect=lambda: recv_ready())
    chan.recv = MagicMock(side_effect=lambda size: recv(size))
    chan.recv_stderr_ready = MagicMock(side_effect=lambda: recv_stderr_ready())
    chan.recv_stderr = MagicMock(side_effect=lambda size: recv_stderr(size))
    chan.exit_status_ready = MagicMock(side_effect=lambda: exit_status_ready())
    chan.recv_exit_status.return_value = exit_code
    return chan


def make_interactive_channel(responses):
    """Create a mock channel for interactive session tests.

    Args:
        responses: List of byte strings. Each call to recv() returns the next one.
    """
    chan = MagicMock()
    chan.status_event = threading.Event()
    chan.status_event.set()
    chan.closed = False

    remaining = list(responses)

    def recv_ready():
        return bool(remaining)

    def recv(size):
        if remaining:
            return remaining.pop(0)
        return b""

    def exit_status_ready():
        return False

    def recv_stderr_ready():
        return False

    chan.recv_ready = MagicMock(side_effect=lambda: recv_ready())
    chan.recv = MagicMock(side_effect=lambda size: recv(size))
    chan.exit_status_ready = MagicMock(side_effect=lambda: exit_status_ready())
    chan.recv_stderr_ready = MagicMock(side_effect=lambda: recv_stderr_ready())
    chan.recv_stderr = MagicMock(side_effect=lambda size: b"")
    return chan
