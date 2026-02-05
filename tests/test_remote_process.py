"""Tests for RemoteProcess and SSHClient.remote_process() factory."""

import threading
from unittest.mock import MagicMock, patch

import pytest

from pacsys.ssh import RemoteProcess, SSHError, SSHTimeoutError

from .ssh_helpers import connected_ssh, make_interactive_channel


@pytest.fixture(autouse=True)
def _mock_getuser():
    with patch("getpass.getuser", return_value="testuser"):
        yield


# ---------------------------------------------------------------------------
# RemoteProcess
# ---------------------------------------------------------------------------


class TestRemoteProcess:
    @patch("paramiko.Transport")
    @patch("socket.create_connection")
    def test_send_line(self, mock_connect, mock_transport_cls):
        ssh, transport = connected_ssh(mock_connect, mock_transport_cls)
        chan = make_interactive_channel([])
        transport.open_session.return_value = chan

        proc = RemoteProcess(ssh, "cmd")
        proc.send_line("hello")
        chan.sendall.assert_called_with(b"hello\n")
        proc.close()

    @patch("paramiko.Transport")
    @patch("socket.create_connection")
    def test_send_bytes(self, mock_connect, mock_transport_cls):
        ssh, transport = connected_ssh(mock_connect, mock_transport_cls)
        chan = make_interactive_channel([])
        transport.open_session.return_value = chan

        proc = RemoteProcess(ssh, "cmd")
        proc.send_bytes(b"\x00\x01\x02")
        chan.sendall.assert_called_with(b"\x00\x01\x02")
        proc.close()

    @patch("paramiko.Transport")
    @patch("socket.create_connection")
    def test_read_until_finds_marker(self, mock_connect, mock_transport_cls):
        ssh, transport = connected_ssh(mock_connect, mock_transport_cls)
        chan = make_interactive_channel([b"hello\nMARKER", b"extra"])
        transport.open_session.return_value = chan

        proc = RemoteProcess(ssh, "cmd")
        result = proc.read_until(b"MARKER")
        assert result == b"hello\n"
        proc.close()

    @patch("paramiko.Transport")
    @patch("socket.create_connection")
    def test_read_until_consumes_marker(self, mock_connect, mock_transport_cls):
        ssh, transport = connected_ssh(mock_connect, mock_transport_cls)
        chan = make_interactive_channel([b"aMARKERbMARKERc"])
        transport.open_session.return_value = chan

        proc = RemoteProcess(ssh, "cmd")
        r1 = proc.read_until(b"MARKER")
        assert r1 == b"a"
        r2 = proc.read_until(b"MARKER")
        assert r2 == b"b"
        proc.close()

    @patch("paramiko.Transport")
    @patch("socket.create_connection")
    def test_read_until_split_across_chunks(self, mock_connect, mock_transport_cls):
        ssh, transport = connected_ssh(mock_connect, mock_transport_cls)
        chan = make_interactive_channel([b"hel", b"lo\nMAR", b"KER"])
        transport.open_session.return_value = chan

        proc = RemoteProcess(ssh, "cmd")
        result = proc.read_until(b"MARKER")
        assert result == b"hello\n"
        proc.close()

    @patch("paramiko.Transport")
    @patch("socket.create_connection")
    def test_read_until_timeout(self, mock_connect, mock_transport_cls):
        ssh, transport = connected_ssh(mock_connect, mock_transport_cls)
        chan = MagicMock()
        chan.status_event = threading.Event()
        chan.closed = False
        chan.recv_ready = MagicMock(return_value=False)
        chan.recv_stderr_ready = MagicMock(return_value=False)
        chan.exit_status_ready = MagicMock(return_value=False)
        transport.open_session.return_value = chan

        proc = RemoteProcess(ssh, "cmd")
        with pytest.raises(SSHTimeoutError, match="Timed out"):
            proc.read_until(b"MARKER", timeout=0.1)
        proc.close()

    @patch("paramiko.Transport")
    @patch("socket.create_connection")
    def test_read_until_channel_closed(self, mock_connect, mock_transport_cls):
        ssh, transport = connected_ssh(mock_connect, mock_transport_cls)
        chan = MagicMock()
        chan.status_event = threading.Event()
        chan.status_event.set()
        chan.closed = False
        chan.recv_ready = MagicMock(return_value=False)
        chan.recv_stderr_ready = MagicMock(return_value=False)
        chan.exit_status_ready = MagicMock(return_value=True)
        transport.open_session.return_value = chan

        proc = RemoteProcess(ssh, "cmd")
        with pytest.raises(SSHError, match="Process exited"):
            proc.read_until(b"MARKER")
        proc.close()

    @patch("paramiko.Transport")
    @patch("socket.create_connection")
    def test_read_for(self, mock_connect, mock_transport_cls):
        ssh, transport = connected_ssh(mock_connect, mock_transport_cls)
        chan = make_interactive_channel([b"hello ", b"world"])
        transport.open_session.return_value = chan

        proc = RemoteProcess(ssh, "cmd")
        result = proc.read_for(0.2)
        assert result == b"hello world"
        proc.close()

    @patch("paramiko.Transport")
    @patch("socket.create_connection")
    def test_read_for_empty(self, mock_connect, mock_transport_cls):
        ssh, transport = connected_ssh(mock_connect, mock_transport_cls)
        chan = MagicMock()
        chan.status_event = threading.Event()
        chan.closed = False
        chan.recv_ready = MagicMock(return_value=False)
        chan.recv_stderr_ready = MagicMock(return_value=False)
        chan.exit_status_ready = MagicMock(return_value=False)
        transport.open_session.return_value = chan

        proc = RemoteProcess(ssh, "cmd")
        result = proc.read_for(0.1)
        assert result == b""
        proc.close()

    @patch("paramiko.Transport")
    @patch("socket.create_connection")
    def test_alive_property(self, mock_connect, mock_transport_cls):
        ssh, transport = connected_ssh(mock_connect, mock_transport_cls)
        chan = make_interactive_channel([])
        transport.open_session.return_value = chan

        proc = RemoteProcess(ssh, "cmd")
        assert proc.alive
        proc.close()
        assert not proc.alive

    @patch("paramiko.Transport")
    @patch("socket.create_connection")
    def test_context_manager(self, mock_connect, mock_transport_cls):
        ssh, transport = connected_ssh(mock_connect, mock_transport_cls)
        chan = make_interactive_channel([])
        transport.open_session.return_value = chan

        with RemoteProcess(ssh, "cmd") as proc:
            assert proc.alive
        assert not proc.alive
        chan.close.assert_called()

    @patch("paramiko.Transport")
    @patch("socket.create_connection")
    def test_double_close(self, mock_connect, mock_transport_cls):
        ssh, transport = connected_ssh(mock_connect, mock_transport_cls)
        chan = make_interactive_channel([])
        transport.open_session.return_value = chan

        proc = RemoteProcess(ssh, "cmd")
        proc.close()
        proc.close()  # should not raise

    @patch("paramiko.Transport")
    @patch("socket.create_connection")
    def test_drains_stderr(self, mock_connect, mock_transport_cls):
        ssh, transport = connected_ssh(mock_connect, mock_transport_cls)
        chan = make_interactive_channel([b"dataMARKER"])
        stderr_calls = [True, False]
        chan.recv_stderr_ready = MagicMock(side_effect=lambda: stderr_calls.pop(0) if stderr_calls else False)
        chan.recv_stderr = MagicMock(return_value=b"warning\n")
        transport.open_session.return_value = chan

        proc = RemoteProcess(ssh, "cmd")
        proc.read_until(b"MARKER")
        chan.recv_stderr.assert_called()
        proc.close()


# ---------------------------------------------------------------------------
# SSHClient.remote_process() factory
# ---------------------------------------------------------------------------


class TestRemoteProcessFactory:
    @patch("paramiko.Transport")
    @patch("socket.create_connection")
    def test_returns_remote_process(self, mock_connect, mock_transport_cls):
        ssh, transport = connected_ssh(mock_connect, mock_transport_cls)
        chan = make_interactive_channel([])
        transport.open_session.return_value = chan

        proc = ssh.remote_process("my_cmd")
        assert isinstance(proc, RemoteProcess)
        chan.exec_command.assert_called_once_with("my_cmd")
        proc.close()
