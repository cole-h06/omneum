# Linux installation

On a systemd-based Linux host with `systemd-sysusers`, `runuser`, `flock`, and
GNU coreutils, build and install the daemon from an administrator-controlled
checkout:

```sh
cargo build --locked --release --no-default-features --features daemon --bin omneumd
sudo sh deploy/install.sh target/release/omneumd
```

The installer creates persistent `omneum-crypto` and `omneum-mcp` accounts and
the `omneum-ipc` and reserved `omneum-session` groups without fixed IDs. It installs
the daemon and systemd unit root-owned, records the resolved MCP UID and session
GID in `/etc/omneumd/peer.conf`, and
provisions a new server key. Reinstalling restarts the service and preserves its
accounts and key. An existing installation with a missing or invalid key requires
administrator action; installation never replaces that key.

`RuntimeDirectory=` creates `/run/omneumd` as `omneum-crypto:omneum-ipc` with
mode `0750`. The daemon creates `eval.sock` with mode `0660`. The private key
remains in `/var/lib/omneumd`, owned by `omneum-crypto`, with directory mode
`0700` and key mode `0600`. Do not install a `test-daemon` build.

For daemon initialization, install the core Python environment with `uv sync --locked --no-default-groups`
at a location readable and executable by `omneum-mcp`. Run initialization as
that account using the environment's absolute executable paths:

```sh
sudo -H -u omneum-mcp /path/to/.venv/bin/omneum init
```

`init` gets the initial public key from the authenticated local daemon and writes
public configuration under the MCP account's home. `--public-key-hex` can be used
to require an expected key. Existing pins are never overwritten. Use the managed
server below for production stdio connections.

Inspect the service with:

```sh
systemctl status omneumd
sudo journalctl -u omneumd
```

Python does not provision or read the VOPRF private key.

## Managed Python server (Ubuntu 22.04 or newer)

Install a dedicated, administrator-controlled production checkout at `/opt/omneum`. As administrator, use
an administrator-owned Python 3.11+ interpreter under `/usr`, or place a
uv-managed interpreter inside `/opt/omneum/python`:

```sh
cd /opt/omneum
sudo env UV_PYTHON_INSTALL_DIR=/opt/omneum/python uv sync --locked --no-default-groups --no-editable --managed-python --python 3.14
```

The checkout, interpreter, environment, native extension, package files, and
import-path parents must all be root-owned and not writable by group or others.
After creating the dedicated installation (uv-managed Python can include writable
group modes), normalize its permissions as administrator:

```sh
sudo chown -R root:root /opt/omneum
sudo find /opt/omneum -type d -exec chmod a+rX,go-w {} +
sudo find /opt/omneum -type f -exec chmod a+rX,go-w {} +
```

After hardening, use `python -B` for administrative Python checks in this runtime.
Otherwise root-run imports can create new `__pycache__` directories with
group-write permissions under a permissive umask, invalidating the hardened
tree before installation. The managed service and installer runtime checks
already disable bytecode writes.

Do not reuse an application-owned environment. The server installer rejects
writable installations and external editable imports. Installation directories
and their parents, including `/usr/local/bin` for the native proxy, must also be
root-owned, non-symlink directories without group/other write permissions
(including the effective ACL mask). The installer rejects an untrusted existing
directory rather than repairing it. Hosted CI images may deliberately make tool
directories writable; prepare those disposable hosts explicitly before testing.
Build the native proxy from the administrator-controlled checkout:

```sh
sudo cargo build --locked --release --no-default-features --features daemon --bin omneum-server
sudo -H -u omneum-mcp /opt/omneum/.venv/bin/omneum init
sudo sh deploy/install-server.sh target/release/omneum-server /var/lib/omneum/.config/Omneum/config.toml
```

For existing deployments, supply the existing public configuration rather than
initializing a different deployment. Installation verifies its daemon pin and
copies it to root-owned `/etc/omneum/config.toml`. A different existing serving
configuration causes failure; updates require explicit administrator action.
The import reads with MCP credentials and cannot read the private server key.
The managed server uses only `/etc/omneum`; its legacy home configuration is not
used for serving.

Grant frontend access only to intended MCP-host accounts:

```sh
sudo usermod -aG omneum-client YOUR_MCP_HOST_USER
```

Start a new login session to acquire membership. Configure the MCP host command
as `/usr/local/bin/omneum-server`. This native command forwards stdio through
`/run/omneum-server.sock`; each connection activates a separate Python service.
Do not point production hosts at the virtualenv's Python console script or run
Python directly as `omneum-mcp`. Never grant frontend clients `omneum-ipc`
membership: that group permits access to the daemon socket. Kernel peer
credentials independently authorize evaluation.

Managed sessions use distinct dynamic users (`omneum-%i`) and the reserved
primary group `omneum-session`. Do not create static accounts with names
`omneum-` followed by a digit, assign accounts to `omneum-session`, or use that
group in other services or directory-service accounts. The installers check
persistent local accounts and group members; keep these names reserved in any
external identity directory as well. Install the updated daemon before the managed server;
the installer records the resolved session GID alongside the existing MCP UID.
The static `omneum-mcp` identity remains available for administrative initialization.

SDK applications using `OmneumClientConfig.from_local_deployment()` should set
`OMNEUM_CONFIG_DIR=/etc/omneum` in the client environment to read the installed
public configuration. The Python service uses that fixed directory independently
of the proxy caller's environment.

The managed service has read-only application/configuration and temporary
storage, hidden home directories, a restricted `/proc` view, and a private
network and IPC namespaces. Only the daemon directory is restored into its otherwise
private `/run`. Python can still execute child programs, which inherit these
restrictions, and can still change application behavior and use the authorized
daemon evaluator. Separate syscall filtering for execution is not enabled.

Python diagnostics go to the journal, never the MCP stream:

```sh
systemctl status omneum-server.socket
sudo journalctl -u 'omneum-server@*'
```

Reinstallation preserves the public configuration and does not interrupt existing
sessions. Restart the socket to apply changed socket settings; stop existing
session units explicitly when an update must take effect immediately.

Before migration, stop unmanaged MCP processes and review existing jobs/startup
files for that identity. The service boundary applies to managed sessions and
their descendants, not to arbitrary processes an administrator launches outside
it. Build and initialization environments remain administrative trust domains.

## Versioned daemon release artifacts

Native daemon bundles are published to GitHub Releases in `cole-h06/omneum`.
The Python package's literal `project.version` in `pyproject.toml` is the version
authority; the Cargo crate version is independent. For version `1.0.3`, the only
valid release tag is `v1.0.3`, and the release asset set is:

- `omneum-daemon-1.0.3-linux-x86_64.tar.gz`
- `omneum-daemon-1.0.3-macos-aarch64.tar.gz`
- `omneum-daemon-1.0.3-macos-x86_64.tar.gz`
- `SHA256SUMS`

The exact-version URL contract is:

```text
https://github.com/cole-h06/omneum/releases/download/v<version>/omneum-daemon-<version>-<platform>.tar.gz
https://github.com/cole-h06/omneum/releases/download/v<version>/SHA256SUMS
```

`<platform>` is exactly `linux-x86_64`, `macos-aarch64`, or `macos-x86_64`.
There is no `latest` fallback or cross-platform substitution. These names describe
the existing native CI builds; they do not promise compatibility with all Linux
libcs or older operating systems. Linux builds currently use Ubuntu 22.04, and
macOS builds use the macOS 15 ARM/Intel runners.

Archives contain files directly at their root, with no enclosing version folder:

- Linux: `omneumd`, `install.sh`, `install-foreground.sh`,
  `systemd/omneumd.service`, and `sysusers.d/omneum.conf`.
- macOS: `omneumd`, `install-macos.sh`, and
  `launchd/ai.omneum.omneumd.plist`.

These are the existing staged daemon artifacts, including the hardened installation
assets. Daemon and scripts have archive mode `0755`, templates `0644`, and
subdirectories `0755`. Packaging sorts members and fixes ownership to UID/GID 0,
owner/group names to empty strings, and tar/gzip timestamps to zero. The gzip
header omits the filename. This makes packaging deterministic for identical staged
bytes and the same Python/zlib toolchain; it does not claim reproducible native
compilation across builds. No installation scripts or security checks are changed.

`SHA256SUMS` is ASCII with one newline-terminated entry per archive, ordered Linux
x86_64, macOS aarch64, macOS x86_64. Each entry is the lowercase SHA-256 digest of
the **compressed archive bytes**, two spaces, and the exact archive basename.
A future installer must retrieve the manifest and selected archive from the same
exact-version release over HTTPS, require exactly one valid entry for the selected
filename, and verify the digest before extraction or execution. Missing, duplicate,
malformed, or mismatched entries must fail closed. The manifest supplies integrity
relative to the trusted GitHub Release; it is not a separate cryptographic signature.
With all three archives downloaded into one directory, administrators can check:

```sh
sha256sum --check SHA256SUMS       # Linux
shasum -a 256 --check SHA256SUMS  # macOS
```

Only `v*` tag **pushes** in the canonical repository can publish. CI rejects any tag
that is not exactly `v<project.version>`, requires the existing test, wheel,
foreground-install, macOS-install, and daemon-artifact jobs to succeed, and fails
on missing/extra staged files, invalid archives, or checksum errors. Preparation
has read-only repository access. Only the publication job gets `contents: write`;
both release jobs have `actions: read` to fetch artifacts from their own run.
All Actions references remain pinned to immutable commit SHAs.

Publication verifies the complete asset set again, creates a draft using an
already-existing tag, uploads assets, downloads and checks the uploaded bytes,
and only then publishes. A failed upload/verification can leave an unpublished
draft requiring administrator inspection and removal before retrying. Existing
releases are not overwritten. CI never creates/pushes tags and does not publish
to PyPI. Pull requests and manual branch runs retain their existing behavior.

The offline contract checks run in the existing Python test matrix and can also
be run locally without building the daemon or publishing:

```sh
python3 -m unittest discover -s tools -p 'test_release_daemon.py' -v
python3 tools/release_daemon.py validate --tag v1.0.3
# With staged daemon-<platform>/ directories under daemon-artifacts/:
python3 tools/release_daemon.py prepare --tag v1.0.3
python3 tools/release_daemon.py verify --tag v1.0.3
```

Preparation requires a fresh `release-assets/` output directory. This establishes
the distribution contract only; `omneum install` is not implemented. The current
administrator installation instructions above continue to apply.
