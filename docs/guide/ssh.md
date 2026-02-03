# SSH Utility

The `pacsys.ssh` module provides SSH command execution, port tunneling, and SFTP
over multi-hop SSH chains using paramiko and GSSAPI (Kerberos) authentication.

This is a standalone utility -- not a backend subclass -- useful for running
remote commands, transferring files, and setting up tunnels (e.g., for gRPC).

## Quick Start

```python
import pacsys

# Execute a remote command
with pacsys.ssh("target.fnal.gov") as client:
    result = client.exec("hostname")
    print(result.stdout)      # "target.fnal.gov\n"
    print(result.ok)          # True
```

## Multi-Hop Connections

Chain through jump hosts. Each hop can use a different auth method.

```python
# Simple multi-hop (all Kerberos)
with pacsys.ssh(["jump.fnal.gov", "target.fnal.gov"]) as client:
    result = client.exec("whoami")

# Mixed auth per hop
from pacsys.ssh import SSHHop

with pacsys.ssh([
    SSHHop("jump.fnal.gov"),  # Kerberos (default)
    SSHHop("target.fnal.gov", auth_method="key",
           key_filename="~/.ssh/id_ed25519"),
]) as client:
    result = client.exec("ls /data")
```

## Command Execution

### Single Command

```python
result = client.exec("ls -la /tmp")
print(result.exit_code)  # 0
print(result.stdout)     # file listing
print(result.stderr)     # empty string
print(result.ok)         # True
```

### With Stdin Input

```python
result = client.exec("cat > /tmp/config.txt", input="key=value\n")
```

### With Timeout

```python
from pacsys.ssh import SSHTimeoutError

try:
    result = client.exec("long-running-job", timeout=30.0)
except SSHTimeoutError:
    print("Command timed out")
```

### Streaming Output

Yields stdout lines as they arrive:

```python
for line in client.exec_stream("tail -f /var/log/messages"):
    print(line)
    if "ERROR" in line:
        break
```

Non-zero exit raises `SSHCommandError` after all output is consumed:

```python
from pacsys.ssh import SSHCommandError

try:
    for line in client.exec_stream("failing-command"):
        print(line)
except SSHCommandError as e:
    print(f"Exit code: {e.exit_code}, stderr: {e.stderr}")
```

### Multiple Commands

```python
results = client.exec_many(["hostname", "uptime", "df -h"])
for r in results:
    print(f"{r.command}: exit={r.exit_code}")
```

## Port Forwarding

Create local port forwards through the SSH connection:

```python
# Forward local:23456 -> dce08.fnal.gov:50051 through jump host
with pacsys.ssh("jump.fnal.gov") as client:
    with client.forward(23456, "dce08.fnal.gov", 50051) as tunnel:
        print(f"Listening on 127.0.0.1:{tunnel.local_port}")

        # Use with gRPC backend
        with pacsys.grpc(port=tunnel.local_port) as backend:
            value = backend.read("M:OUTTMP")
```

Use `local_port=0` for OS-assigned port:

```python
with client.forward(0, "remote-db", 5432) as tunnel:
    print(f"Assigned port: {tunnel.local_port}")
```

## SFTP

```python
with client.sftp() as sftp:
    # Download
    sftp.get("/remote/data.csv", "/local/data.csv")

    # Upload
    sftp.put("/local/config.ini", "/remote/config.ini")

    # Directory operations
    files = sftp.listdir("/data")
    sftp.mkdir("/data/output")
    sftp.remove("/data/old_file.txt")

    # File info
    info = sftp.stat("/data/important.dat")
    print(info.st_size)
```

## Authentication

### Kerberos (Default)

All hops use GSSAPI (Kerberos) by default. Requires a valid ticket (`kinit`).

```python
# Implicit -- validates GSSAPI availability at init
client = pacsys.ssh("host.fnal.gov")

# Explicit -- reuse KerberosAuth from other pacsys operations
from pacsys import KerberosAuth
client = pacsys.ssh("host.fnal.gov", auth=KerberosAuth())
```

### Key-Based

```python
from pacsys.ssh import SSHHop

client = pacsys.ssh(SSHHop(
    "host.fnal.gov",
    auth_method="key",
    key_filename="~/.ssh/id_ed25519",
))
```

### Password

```python
client = pacsys.ssh(SSHHop(
    "host.fnal.gov",
    auth_method="password",
    password="secret",  # excluded from repr
))
```

## Error Handling

| Exception | When |
|-----------|------|
| `SSHConnectionError` | Connection or auth failure (includes hop info) |
| `SSHCommandError` | Non-zero exit from `exec_stream()` |
| `SSHTimeoutError` | Command or connection timeout |

`exec()` does *not* raise on non-zero exit -- check `result.ok` instead.

```python
from pacsys.ssh import SSHConnectionError

try:
    with pacsys.ssh("unreachable.fnal.gov") as client:
        client.exec("ls")
except SSHConnectionError as e:
    print(f"Failed: {e}")
    print(f"Hop: {e.hop}")
```

## Connection Lifecycle

- **Lazy**: No TCP connection until the first operation
- **Keepalive**: 30-second keepalive on all transports
- **No auto-reconnect**: Create a new client if the connection drops
- **Daemon threads**: Tunnel threads are daemon -- safe in Jupyter
- **Context manager**: `close()` stops all tunnels and disconnects in reverse hop order
