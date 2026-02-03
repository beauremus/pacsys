"""
Live SSH tests against real jump and destination hosts.

Requires:
- Valid Kerberos ticket (kinit)
- Env vars PACSYS_TEST_SSH_JUMP and PACSYS_TEST_SSH_DEST
  (set in tests/real/.env.ssh)

Run:
    source tests/real/.env.ssh && python -m pytest tests/real/test_ssh.py -v -s -o "addopts="
"""

import os
import socket

import pytest

from pacsys.ssh import (
    SSHClient,
    SSHTimeoutError,
)
from .devices import (
    SSH_JUMP_HOST,
    SSH_DEST_HOST,
    requires_ssh,
    kerberos_available,
)


pytestmark = [requires_ssh]


# =============================================================================
# Direct (single-hop) tests against jump host
# =============================================================================


class TestSingleHop:
    """Tests using direct SSH to the jump host."""

    def test_exec_hostname(self):
        with SSHClient(SSH_JUMP_HOST) as ssh:
            result = ssh.exec("hostname")
            assert result.ok
            assert result.stdout.strip()
            print(f"  hostname: {result.stdout.strip()}")

    def test_exec_whoami(self):
        with SSHClient(SSH_JUMP_HOST) as ssh:
            result = ssh.exec("whoami")
            assert result.ok
            username = result.stdout.strip()
            assert username  # non-empty
            # Should match our OS user or Kerberos principal
            print(f"  whoami: {username}")

    def test_exec_nonzero_exit(self):
        with SSHClient(SSH_JUMP_HOST) as ssh:
            result = ssh.exec("ls /nonexistent_path_xyz_12345")
            assert not result.ok
            assert result.exit_code != 0
            assert result.stderr  # should have error message

    def test_exec_with_stdin(self):
        with SSHClient(SSH_JUMP_HOST) as ssh:
            result = ssh.exec("cat", input="hello from pacsys\n")
            assert result.ok
            assert "hello from pacsys" in result.stdout

    def test_exec_many(self):
        with SSHClient(SSH_JUMP_HOST) as ssh:
            results = ssh.exec_many(["hostname", "date", "uptime"])
            assert len(results) == 3
            assert all(r.ok for r in results)
            for r in results:
                print(f"  {r.command}: {r.stdout.strip()}")

    def test_exec_stream(self):
        with SSHClient(SSH_JUMP_HOST) as ssh:
            lines = list(ssh.exec_stream("echo line1; echo line2; echo line3"))
            assert len(lines) >= 3
            assert "line1" in lines[0]
            assert "line2" in lines[1]
            assert "line3" in lines[2]

    def test_exec_timeout(self):
        with SSHClient(SSH_JUMP_HOST) as ssh:
            # Very short timeout on a slow command
            with pytest.raises(SSHTimeoutError):
                ssh.exec("sleep 30", timeout=1.0)

    def test_lazy_connection(self):
        """Client should not connect until first operation."""
        ssh = SSHClient(SSH_JUMP_HOST)
        assert not ssh.connected
        try:
            result = ssh.exec("echo lazy")
            assert ssh.connected
            assert result.ok
        finally:
            ssh.close()
        assert not ssh.connected

    def test_sftp_listdir(self):
        with SSHClient(SSH_JUMP_HOST) as ssh:
            with ssh.sftp() as sftp:
                entries = sftp.listdir("/tmp")
                assert isinstance(entries, list)
                print(f"  /tmp has {len(entries)} entries")

    def test_sftp_stat(self):
        with SSHClient(SSH_JUMP_HOST) as ssh:
            with ssh.sftp() as sftp:
                info = sftp.stat("/etc/hostname")
                assert info.st_size > 0

    def test_tunnel_connectivity(self):
        """Verify tunnel can accept local connections."""
        with SSHClient(SSH_JUMP_HOST) as ssh:
            # Forward to a port we know exists on the jump host (SSH itself)
            with ssh.forward(0, "127.0.0.1", 22) as tunnel:
                assert tunnel.active
                assert tunnel.local_port > 0
                # Try connecting through the tunnel
                try:
                    sock = socket.create_connection(("127.0.0.1", tunnel.local_port), timeout=5.0)
                    # SSH server should send banner
                    data = sock.recv(256)
                    assert b"SSH" in data
                    sock.close()
                    print(f"  tunnel port {tunnel.local_port} -> SSH banner OK")
                except (socket.timeout, ConnectionRefusedError, OSError) as e:
                    pytest.fail(f"Tunnel connection failed: {e}")

    def test_repr(self):
        with SSHClient(SSH_JUMP_HOST) as ssh:
            assert "disconnected" in repr(ssh)
            ssh.exec("true")
            assert "connected" in repr(ssh)
            assert SSH_JUMP_HOST in repr(ssh)


# =============================================================================
# Multi-hop tests: jump -> destination
# =============================================================================


class TestMultiHop:
    """Tests using jump host to reach destination."""

    def test_exec_hostname_via_jump(self):
        with SSHClient([SSH_JUMP_HOST, SSH_DEST_HOST]) as ssh:
            result = ssh.exec("hostname")
            assert result.ok
            hostname = result.stdout.strip()
            print(f"  dest hostname: {hostname}")
            # Should be the destination host (or at least not the jump host)
            assert hostname  # non-empty

    def test_exec_uname(self):
        with SSHClient([SSH_JUMP_HOST, SSH_DEST_HOST]) as ssh:
            result = ssh.exec("uname -a")
            assert result.ok
            assert "Linux" in result.stdout or "linux" in result.stdout.lower()
            print(f"  uname: {result.stdout.strip()[:80]}")

    def test_exec_many_via_jump(self):
        with SSHClient([SSH_JUMP_HOST, SSH_DEST_HOST]) as ssh:
            results = ssh.exec_many(["hostname", "whoami", "pwd"])
            assert len(results) == 3
            assert all(r.ok for r in results)

    def test_exec_stream_via_jump(self):
        with SSHClient([SSH_JUMP_HOST, SSH_DEST_HOST]) as ssh:
            lines = list(ssh.exec_stream("seq 1 5"))
            assert len(lines) == 5
            assert lines[0].strip() == "1"
            assert lines[4].strip() == "5"

    def test_sftp_via_jump(self):
        with SSHClient([SSH_JUMP_HOST, SSH_DEST_HOST]) as ssh:
            with ssh.sftp() as sftp:
                entries = sftp.listdir("/tmp")
                assert isinstance(entries, list)
                print(f"  dest /tmp has {len(entries)} entries")

    def test_sftp_roundtrip_via_jump(self):
        """Write a file via SFTP and read it back."""
        import uuid

        tag = uuid.uuid4().hex[:8]
        remote_path = f"/tmp/pacsys_test_{tag}.txt"
        content = f"pacsys ssh test {tag}\n"
        local_write = f"/tmp/pacsys_ssh_test_put_{tag}.txt"
        local_read = f"/tmp/pacsys_ssh_test_get_{tag}.txt"

        # Write local temp file
        with open(local_write, "w") as f:
            f.write(content)

        try:
            with SSHClient([SSH_JUMP_HOST, SSH_DEST_HOST]) as ssh:
                with ssh.sftp() as sftp:
                    sftp.put(local_write, remote_path)
                    sftp.get(remote_path, local_read)
                    sftp.remove(remote_path)

            with open(local_read) as f:
                assert f.read() == content
        finally:
            for p in (local_write, local_read):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def test_tunnel_to_dest(self):
        """Tunnel through jump host to destination's SSH port."""
        with SSHClient(SSH_JUMP_HOST) as ssh:
            with ssh.forward(0, SSH_DEST_HOST, 22) as tunnel:
                assert tunnel.active
                try:
                    sock = socket.create_connection(("127.0.0.1", tunnel.local_port), timeout=5.0)
                    data = sock.recv(256)
                    assert b"SSH" in data
                    sock.close()
                    print(f"  tunnel to {SSH_DEST_HOST}:22 OK (port {tunnel.local_port})")
                except (socket.timeout, ConnectionRefusedError, OSError) as e:
                    pytest.fail(f"Tunnel to dest failed: {e}")

    def test_repr_multi_hop(self):
        with SSHClient([SSH_JUMP_HOST, SSH_DEST_HOST]) as ssh:
            r = repr(ssh)
            assert SSH_JUMP_HOST in r
            assert SSH_DEST_HOST in r
            assert "disconnected" in r

            ssh.exec("true")
            r = repr(ssh)
            assert "connected" in r


# =============================================================================
# Explicit KerberosAuth tests
# =============================================================================


class TestExplicitAuth:
    """Tests with explicit KerberosAuth passed to SSHClient."""

    @pytest.mark.skipif(not kerberos_available(), reason="Kerberos not available")
    def test_explicit_kerberos_auth(self):
        from pacsys.auth import KerberosAuth

        auth = KerberosAuth()
        with SSHClient(SSH_JUMP_HOST, auth=auth) as ssh:
            result = ssh.exec("hostname")
            assert result.ok
            print(f"  authenticated as: {auth.principal}")

    @pytest.mark.skipif(not kerberos_available(), reason="Kerberos not available")
    def test_explicit_auth_multi_hop(self):
        from pacsys.auth import KerberosAuth

        auth = KerberosAuth()
        with SSHClient([SSH_JUMP_HOST, SSH_DEST_HOST], auth=auth) as ssh:
            result = ssh.exec("whoami")
            assert result.ok
            print(f"  whoami on dest: {result.stdout.strip()}")


# =============================================================================
# Edge cases
# =============================================================================


class TestEdgeCases:
    def test_double_close(self):
        ssh = SSHClient(SSH_JUMP_HOST)
        ssh.exec("true")
        ssh.close()
        ssh.close()  # should not raise

    def test_close_before_connect(self):
        ssh = SSHClient(SSH_JUMP_HOST)
        ssh.close()  # should not raise

    def test_connection_reuse(self):
        """Multiple commands should reuse the same transport."""
        with SSHClient(SSH_JUMP_HOST) as ssh:
            r1 = ssh.exec("echo first")
            r2 = ssh.exec("echo second")
            r3 = ssh.exec("echo third")
            assert r1.ok and r2.ok and r3.ok
            assert r1.stdout.strip() == "first"
            assert r3.stdout.strip() == "third"

    def test_large_output(self):
        """Handle commands with large stdout."""
        with SSHClient(SSH_JUMP_HOST) as ssh:
            result = ssh.exec("seq 1 10000")
            assert result.ok
            lines = result.stdout.strip().split("\n")
            assert len(lines) == 10000
            assert lines[0] == "1"
            assert lines[-1] == "10000"
