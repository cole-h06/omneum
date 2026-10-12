# Installation

Omneum runs locally as a Python SDK and MCP server backed by a protected
evaluation daemon.

## Supported platforms

| Platform | Architecture | Python | Managed service |
|---|---|---:|---|
| macOS | Apple Silicon (arm64) | 3.11–3.14 | launchd |
| macOS | Intel (x86_64) | 3.11–3.14 | launchd |
| Linux (Ubuntu 22.04+) | x86_64 | 3.11–3.14 | systemd |

The managed installer does not support Windows or Linux ARM. Windows wheels
are SDK-only and do not provide a protected local MCP deployment.

## Install

Use Python 3.11–3.14 in a virtual environment, or another Python environment
where installing packages is permitted. Ubuntu 22.04 ships Python 3.10, so
install a supported Python first. On managed system Python installations, use
a virtual environment to avoid the externally managed environment restriction.

Local SQLite storage rejects symlinked or group/world-writable ancestors and
requires its own directory to be owner-only (0700). For a new default graph,
Omneum uses `~/.omneum/data/context.db` if the native data-directory ancestors
are unsafe. This private location remains stable across restarts. Existing
graphs and explicitly selected data directories are never silently relocated;
unsafe permissions there still require review. Omneum does not change
permissions on directories shared with other applications.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install omneum
omneum install
```

Run `omneum install` as your normal login user, not with `sudo`. It requests
administrator authorization to install the protected daemon and service account.
No Rust toolchain or manually supplied cryptographic key is required. Internet
access to PyPI and public GitHub Release downloads is required.

Network participation and contribution remain disabled by default. Installing
the local MCP server does not enroll you or authorize uploading private context.

The installer downloads the daemon bundle matching the installed Omneum
version, verifies its SHA-256 checksum, installs the managed service, initializes
the local configuration, and verifies the VOPRF connection before returning
success.

The Python package and daemon release must have the same version. Omneum does
not fall back to `latest` or another daemon version.

## MCP server

After installation, MCP clients can start Omneum with `omneum-server`:

```json
{
  "mcpServers": {
    "omneum": {
      "command": "omneum-server"
    }
  }
}
```

On Linux, `omneum-server` is the native proxy into the isolated systemd MCP
session. On macOS, it connects through the installed local service.

If the MCP client does not inherit your virtual environment's PATH, use the
absolute executable path printed by `command -v omneum-server` as its `command`.
The same executable can be run directly from the activated terminal.

## Managed runtime

### macOS

```text
Python SDK / MCP client
        │
   omneum-server
        │
    local daemon
        │
      launchd
```

The daemon owns the VOPRF key and is installed as a managed launchd service.
Its executable lives at `/Library/Omneum/omneumd` below root-owned, non-writable
parents, independent of a Homebrew installation under `/usr/local`.

### Linux

```text
login user
    │
native omneum-server proxy
    │
omneum-client socket
    │
isolated systemd MCP session
    │
protected evaluation daemon
```

The login account is added to `omneum-client`. It is not added to
`omneum-ipc` or `omneum-session` and cannot read the daemon's private VOPRF key.

The managed runtime is installed under:

```text
/opt/omneum
```

The public client configuration is stored at:

```text
/etc/omneum/config.toml
```

## Release verification

`omneum install` downloads the versioned daemon archive and `SHA256SUMS` from
the corresponding GitHub Release.

The installer:

- requires the exact installed Omneum version;
- verifies the archive SHA-256 before execution;
- rejects archive traversal, links, duplicate paths, and unexpected files;
- does not pipe downloaded shell content into a shell;
- does not resolve Python dependencies as root during Linux installation.

On Linux, the release contains a prebuilt CPython 3.13 runtime and the locked
Omneum production environment. Installation does not resolve packages from
PyPI.

## Linux requirements

Managed Linux installation requires:

- Ubuntu 22.04+ x86_64
- systemd
- `sudo`
- `systemd-sysusers`
- `runuser`
- `usermod`
- `sg`

`omneum install` refuses unsupported or writable installation parents rather
than silently changing their permissions.

Linux installations without systemd require administrator-managed
supervision and are not supported by the managed `omneum install` path.

## Configuration

The installed client uses the public VOPRF key and daemon configuration
generated during initialization.

Existing per-user key pins are preserved. If an existing pin does not match
the installed daemon, connection verification fails rather than replacing it.

For custom endpoints and development environments, `omneum init` can be used
independently of the managed installer.

### Environment variables

| Variable | Purpose |
|---|---|
| `OMNEUM_CONFIG_DIR` | Override the calling user's public configuration directory |
| `OMNEUM_DAEMON_SOCKET` | Override the daemon socket for development or administrator-managed deployments |
| `OMNEUM_DAEMON_UID` | Override the expected daemon UID for custom deployments |

`OMNEUM_DAEMON_SOCKET` and `OMNEUM_DAEMON_UID` should be unset when running
the managed installer so installation verification targets the protected
system service.

## Troubleshooting

### Release not found

The Python package requires daemon assets for the exact same version. Check
that the corresponding GitHub Release contains the daemon bundle for your
platform.

### Checksum verification failed

The downloaded archive is not executed. Retry the download. Persistent
failures indicate that the release assets or checksum manifest need inspection.

### Administrator authorization failed

Run `omneum install` as your normal login account and approve the `sudo`
request when prompted.

### Service verification failed

Installation is not reported as ready until the SDK completes a
proof-verified VOPRF request through the installed service.

Check the daemon/service status and existing public-key pin before retrying.

## Administrator deployments

For service identities, systemd units, socket permissions, manual
installation, and daemon administration, see [`deploy/README.md`](../../deploy/README.md).

## Optional asymmetric authentication

The local stdio installation includes its MCP SDK and does not need Python
cryptography. Operator account enrollment and SDK asymmetric OAuth require
`pip install 'omneum[oauth]'` on macOS arm64 or Linux x86_64. On macOS Intel,
those optional capabilities raise an explicit dependency error because patched
public crypto wheels are unavailable. See [the SDK architecture and maintenance
contract](../mcp-sdk.md).
