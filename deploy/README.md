# Deploying Omneum

This directory contains the service definitions and installers used to run the
Omneum evaluator and MCP server on Linux.

For a normal local installation, use:

```bash
pip install omneum
omneum install
```

See [Installation](../docs/installation.md).

The instructions below are for administrators installing or operating the
services directly.

## Linux

Omneum's managed Linux deployment has two service boundaries:

```text
MCP host
   │
   ▼
/usr/local/bin/omneum-server
   │
   ▼
/run/omneum-server.sock
   │
   ▼
omneum-server@.service
   │
   ▼
/run/omneumd/eval.sock
   │
   ▼
omneumd.service
```

`omneumd` owns evaluation and the VOPRF server key. Each MCP connection runs
in a separate systemd service under a dynamic `omneum-*` user.

### Requirements

The supported managed deployment target is Ubuntu 22.04+ x86_64 with:

```text
systemd
systemd-sysusers
runuser
flock
GNU coreutils
Python 3.11+
```

## Evaluator daemon

Build `omneumd` from an administrator-controlled checkout:

```bash
cargo build --locked --release \
  --no-default-features \
  --features daemon \
  --bin omneumd

sudo sh deploy/install.sh target/release/omneumd
```

`install.sh` creates:

| Resource | Purpose |
|---|---|
| `omneum-crypto` | Owns the VOPRF private key and evaluator daemon |
| `omneum-mcp` | Administrative MCP initialization |
| `omneum-ipc` | Access to the evaluator Unix socket |
| `omneum-session` | Primary group reserved for isolated MCP sessions |

The accounts and groups use system-assigned IDs.

The daemon key is stored under:

```text
/var/lib/omneumd
```

The directory is owned by `omneum-crypto` with mode `0700`; the key uses
`0600`.

At runtime, systemd creates:

```text
/run/omneumd
```

as `omneum-crypto:omneum-ipc` with mode `0750`. `omneumd` creates
`eval.sock` inside it with mode `0660`.

Reinstalling the daemon preserves the existing key. If the key is missing or
invalid, the installer stops instead of generating a replacement.

Check the service with:

```bash
systemctl status omneumd
sudo journalctl -u omneumd
```

## Initialize the MCP configuration

Run `omneum init` as `omneum-mcp` using the production Python environment:

```bash
sudo -H -u omneum-mcp /opt/omneum/.venv/bin/omneum init
```

`init` reads the daemon's public VOPRF key over the authenticated local socket
and writes the client configuration under the MCP account.

To require a specific public key:

```bash
sudo -H -u omneum-mcp \
  /opt/omneum/.venv/bin/omneum init \
  --public-key-hex <hex>
```

An existing key pin is never replaced automatically.

The Python process does not provision or read the VOPRF private key.

## MCP server

The production MCP server runs from an administrator-controlled installation
under `/opt/omneum`.

Create the environment from the lockfile:

```bash
cd /opt/omneum

sudo env UV_PYTHON_INSTALL_DIR=/opt/omneum/python \
  uv sync \
  --locked \
  --no-default-groups \
  --no-editable \
  --managed-python \
  --python 3.14
```

The checkout, Python interpreter, virtual environment, native extension, and
their parent directories must be root-owned and not writable by group or
other users.

Normalize the installation after creating it:

```bash
sudo chown -R root:root /opt/omneum
sudo find /opt/omneum -type d -exec chmod a+rX,go-w {} +
sudo find /opt/omneum -type f -exec chmod a+rX,go-w {} +
```

Don't reuse an application-owned virtual environment. `install-server.sh`
rejects writable installation trees and editable imports.

### Install the native proxy

Build the proxy:

```bash
cargo build --locked --release \
  --no-default-features \
  --features daemon \
  --bin omneum-server
```

Then install it with the initialized public configuration:

```bash
sudo sh deploy/install-server.sh \
  target/release/omneum-server \
  /var/lib/omneum/.config/Omneum/config.toml
```

The installer copies the public configuration to:

```text
/etc/omneum/config.toml
```

The managed server reads this file instead of configuration from a user's
home directory.

## Client access

Grant MCP access to the account that will launch `omneum-server`:

```bash
sudo usermod -aG omneum-client YOUR_MCP_HOST_USER
```

Start a new login session after changing group membership.

Configure the MCP host to execute:

```text
/usr/local/bin/omneum-server
```

Don't add client accounts to `omneum-ipc`. That group can reach the evaluator
socket directly.

Don't add accounts to `omneum-session` either. systemd uses that group for
the dynamic users created for MCP sessions.

## MCP session isolation

Every connection to `/run/omneum-server.sock` starts a separate
`omneum-server@.service` instance.

The service uses a dynamic `omneum-*` user and has:

- a read-only application tree;
- a read-only configuration;
- a private network namespace;
- a private IPC namespace;
- hidden home directories;
- a restricted `/proc`;
- private temporary storage.

Only the evaluator runtime directory is exposed inside its private `/run`.

Python subprocesses inherit the same systemd sandbox. The service does not
currently use a separate syscall filter for process execution.

Never create persistent accounts named `omneum-<digit>...`. Those names are
reserved for systemd's dynamic MCP users.

## SDK applications

Applications using:

```python
OmneumClientConfig.from_local_deployment()
```

should point the client at the system configuration:

```bash
export OMNEUM_CONFIG_DIR=/etc/omneum
```

The managed MCP service always uses `/etc/omneum` regardless of the proxy
caller's environment.

## Logs

Evaluator daemon:

```bash
systemctl status omneumd
sudo journalctl -u omneumd
```

MCP server:

```bash
systemctl status omneum-server.socket
sudo journalctl -u 'omneum-server@*'
```

Python diagnostics are written to the journal, not to MCP stdio.

## Updating an installation

Reinstalling `omneumd` preserves the VOPRF key.

Reinstalling the MCP server preserves the installed public configuration and
doesn't terminate existing MCP sessions.

Restart the socket after changing socket configuration:

```bash
sudo systemctl restart omneum-server.socket
```

Stop existing `omneum-server@*` units if a server update needs to take effect
for already-running sessions.

A runtime at `/opt/omneum` must match the version being deployed. Replacing a
different-version runtime is an administrator operation; the installer won't
rewrite one automatically.

## Foreground deployment

On Linux hosts without systemd, `install-foreground.sh` provisions the daemon
accounts, files, key, and runtime directory without starting a persistent
service:

```bash
sudo sh deploy/install-foreground.sh target/release/omneumd
```

Process supervision is left to the administrator.

## Files in this directory

```text
deploy/
├── install.sh
├── install-foreground.sh
├── install-server.sh
├── install_server.py
├── install-linux.py
├── runtime_bundle.py
├── systemd/
│   ├── omneumd.service
│   ├── omneum-server.socket
│   └── omneum-server@.service
└── sysusers.d/
    ├── omneum.conf
    └── omneum-server.conf
```

For the normal `pip install omneum` installation path, see
[Installation](../docs/installation.md).