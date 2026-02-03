# ACL

HTTP-based read-only access via the ACL CGI script. ACL is a separate service on the control system (not DPM). No authentication required.

```mermaid
sequenceDiagram
    participant App as Your App
    participant CGI as www-ad.fnal.gov<br>/cgi-bin/acl.pl
    participant ACNET as ACNET

    App->>CGI: HTTPS GET ?command=read&drf=...
    CGI->>ACNET: Device query
    ACNET-->>CGI: Device value
    CGI-->>App: Text response
```

## Characteristics

- **No authentication**: Anyone can read
- **Read-only**: No write or streaming support
- **Simple**: Just HTTP requests. No writes. No streaming.
- **Slower**: HTTP overhead vs binary protocol

## Usage

```python
import pacsys

with pacsys.acl() as backend:
    value = backend.read("M:OUTTMP")
    readings = backend.get_many(["M:OUTTMP", "G:AMANDA"])
```

## When to Use

- Quick one-off reads when there are difficulties installing dependencies
