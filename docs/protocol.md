# Installation

Omneum supports macOS and Ubuntu. Install the Python package first:

```bash
pip install omneum
```

Then install the local server:

```bash
omneum install
```

Run `omneum install` from your normal login account. Don't run the command with `sudo`; it will ask for administrator access when the system service needs to be installed.

## Supported platforms

| Platform | Architecture | Python | Service manager |
|---|---|---|---|
| macOS | Apple Silicon (arm64) | 3.11–3.14 | launchd |
| macOS | Intel (x86_64) | 3.11–3.14 | launchd |
| Linux (Ubuntu 22.04+) | x86_64 | 3.11–3.14 | systemd |

Windows and Linux ARM aren't supported yet.

## What `omneum install` installs

The Python package contains the SDK, CLI, and `omneum-server` entry point. The evaluator daemon is distributed separately with each GitHub release.

`omneum install` downloads the daemon release matching the installed Python package version. For example, Omneum `1.0.3` only installs daemon assets from the `v1.0.3` release. It doesn't resolve `latest` or fall back to another version.

The downloaded archive is checked against `SHA256SUMS` before anything inside it runs. A missing checksum, mismatched digest, unexpected archive entry, link, or path traversal causes the installation to stop.

### macOS

On macOS, the daemon runs under `launchd`. The installer provisions its VOPRF key, installs the service, and writes the public client configuration for the login account.

`omneum-server` connects MCP clients to this local service.

### Ubuntu

The Linux release includes a CPython 3.13 runtime with Omneum and its locked production dependencies already installed. It is extracted under:

```text
/opt/omneum
```

No Python packages are resolved from PyPI while the installer is running as root.

The evaluator runs under its own service identity. MCP clients don't connect to that process directly. `omneum-server` talks to the frontend Unix socket, which starts an isolated systemd MCP session:

```text
login user
    │
    ▼
omneum-server
    │
    ▼
omneum-client socket
    │
    ▼
isolated MCP session
    │
    ▼
evaluator daemon
```

The login account is added to `omneum-client`. It is not added to `omneum-ipc` or `omneum-session`, and it cannot read the daemon's VOPRF private key.

The public configuration is installed at:

```text
/etc/omneum/config.toml
```

## MCP

After installation, point an MCP client at `omneum-server`:

```json
{
  "mcpServers": {
    "omneum": {
      "command": "omneum-server"
    }
  }
}
```

The same command is used on macOS and Linux.

## Connection check

`omneum install` doesn't report success just because the service started. It sends a VOPRF request through the installed server and verifies the response against the configured public key.

If an existing user configuration contains a different key pin, Omneum leaves it alone and the connection check fails. The installer doesn't replace an existing pin to make the check pass.

## Ubuntu requirements

The managed Linux installer expects Ubuntu 22.04+ x86_64 with systemd.

It also uses the standard system tools:

```text
sudo
systemd-sysusers
runuser
usermod
sg
```

If systemd isn't available, `omneum install` stops before downloading or installing the managed service. See [`deploy/README.md`](../deploy/README.md) for manually supervised deployments.

## Custom endpoints

`omneum init` can be used separately from `omneum install` when developing against a custom daemon or administrator-managed deployment.

The relevant overrides are:

| Variable | Used for |
|---|---|
| `OMNEUM_CONFIG_DIR` | Public client configuration directory |
| `OMNEUM_DAEMON_SOCKET` | Custom daemon socket |
| `OMNEUM_DAEMON_UID` | Expected daemon UID |

Unset `OMNEUM_DAEMON_SOCKET` and `OMNEUM_DAEMON_UID` before running the managed installer. Otherwise the final connection check could target a custom endpoint instead of the installed system service.

## Installation failures

### No matching release

The Python package and daemon release must have the same version. If the release assets for that version haven't been published, `omneum install` stops.

### Checksum failure

Nothing from the downloaded archive runs. Delete the failed download and retry the installation.

### `sudo` failure

Run `omneum install` from an account allowed to request administrator access. Don't run the entire command under `sudo`.

### Server doesn't become ready

The installer won't report success until the final VOPRF request passes. Check the `launchd` or systemd service and the configured public-key pin before retrying.

For systemd units, service accounts, socket permissions, and manual daemon installation, see [`deploy/README.md`](../deploy/README.md).