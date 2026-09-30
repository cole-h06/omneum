# Installing Omneum

On macOS arm64/x86_64 or Ubuntu 22.04+ x86_64 with systemd,
with Python 3.11–3.14:

```sh
pip install omneum
omneum install
```

Run the command as your normal login user, without `sudo`. It requests administrator
authorization through the system `sudo` prompt only when deploying the verified
bundle. On macOS, initialization runs as your login user. On Linux, it runs
as the existing protected MCP identity using the verified, root-owned runtime;
the final connection check runs as your login user through the public proxy.

The command detects the platform, reads the installed Python distribution's version,
and downloads `SHA256SUMS` and `omneum-daemon-<version>-<platform>.tar.gz` from
`https://github.com/cole-h06/omneum/releases/download/v<version>/`. It never resolves
`latest`, accepts alternate repositories, or skips checksum verification. The exact
version's daemon assets must be published first; installing the Python wheel does
not itself publish or supply the daemon bundle.

The manifest must match the three-platform release contract, with exactly one valid
entry per asset. SHA-256 covers the compressed bytes. HTTPS redirects are restricted
to GitHub release hosts. The manifest supplies integrity relative to the trusted
GitHub Release, not an independent signature.

All archive paths, entry types, ownership, and modes must match the existing release
layout. Links, traversal, duplicates, unexpected files, and incomplete bundles are
rejected before any files are extracted. Downloads and expanded archives have size
limits. Extracted files live in a private temporary directory that is removed on
success or failure. No downloaded shell content is piped to a shell.

On macOS, deployment invokes the bundle's existing `install-macos.sh`; daemon
identity, key provisioning, socket permissions, and launchd behavior remain in that
installer. Shared `init` logic creates public configuration, and a pinned,
OS-authenticated VOPRF evaluation verifies connectivity before readiness.

## Linux managed installation

The Linux archive additionally contains the native `omneum-server` proxy, the
existing server installer and systemd/sysusers files, a small root orchestration
helper, and `runtime.tar.gz`. The latter contains a prebuilt CPython 3.13 runtime
and a non-editable Omneum environment with the locked production dependencies.
It is covered by the outer release SHA-256 and has an exact package-version marker.
Installation does not resolve dependencies or download packages from PyPI.

After sudo authorization, the helper:

1. Copies required bundle files without following links into a root-owned temporary
   directory and serializes installation with an administrator-owned lock.
2. Extracts the link-free runtime at `/opt/omneum`, checks it with the existing
   managed-runtime trust validator, and checks its installed package version.
3. Calls the existing `install.sh` to provision and start the protected daemon.
4. Runs the existing `omneum init` as `omneum-mcp`, using only the validated runtime.
   An existing managed configuration or key pin is preserved.
5. Calls the existing `install-server.sh` to install the native proxy, public pin,
   and socket-activated isolated session service.
6. Adds the invoking login account only to `omneum-client`.
7. Returns to the caller, whose installed Python SDK makes a proof-verified request
   through the native proxy and managed MCP server. Only this success reports ready.

The serving path remains:

```text
login user → native proxy → omneum-client socket → isolated systemd MCP session
                                                     ↓
                                              protected daemon
```

The login account is never added to `omneum-ipc` or `omneum-session`, never runs
user-owned Python as `omneum-mcp`, and cannot read the daemon key. Existing systemd
namespace restrictions, dynamic identities, socket ownership, and peer checks stay
unchanged. The public `omneum-server` entry point delegates to the native Linux
proxy. If the current shell predates the new group membership, it uses the system
`sg` tool with a fixed proxy command to activate **only the frontend group** in
that subprocess. No logout or permanent privilege change to the shell is required.

Clients with no explicit configuration override or existing user pin read the
root-owned public `/etc/omneum/config.toml`. Existing per-user pins are not replaced;
a stale pin causes connection verification to fail. Administrator instructions
remain in [deployment documentation](../deploy/README.md).

The supported Linux baseline is Ubuntu 22.04+ x86_64 with an active systemd manager,
`sudo`, system Python 3.10+, `systemd-sysusers`, `runuser`, `usermod`, `sg`, and the
standard core utilities. These are OS prerequisites, not a pre-provisioned Omneum
runtime. Installation refuses untrusted/writable installation parents instead of
repairing them. A runtime created by this installer may be reused for the same
exact version after validation; automatic replacement of an existing different
runtime or an administrator-created runtime is not supported.

Without systemd, `install-foreground.sh` provisions accounts, files, key, and runtime
directory but does not start or supervise a persistent service. `omneum install`
stops before download/elevation and points to administrator-managed supervision.
Windows, Linux ARM, and other architectures are explicitly unsupported. No telemetry
is sent on any platform.

## When installation fails

- **Release unavailable:** install a Python package version with an existing,
  matching daemon release. There is no fallback to another version.
- **Checksum or archive failure:** nothing from that archive executes. Retry the
  download; persistent failures require release maintainer attention.
- **Authorization failure:** retry with an account allowed to use `sudo`.
- **Installer failure:** follow the displayed installer diagnostic and the
  [administrator documentation](../deploy/README.md). Deployment may have partially
  completed; the command does not delete service accounts or keys to roll it back.
- **Initialization or verification failure:** readiness is not reported. Check
  service status and the existing public-key pin before retrying. The command never
  overwrites an existing pin or private key to hide a mismatch.

Unset `OMNEUM_DAEMON_SOCKET` and `OMNEUM_DAEMON_UID` before using `install`; it must
verify the protected system endpoint. `OMNEUM_CONFIG_DIR` can still select the
calling user's public configuration location. `omneum init` remains available for
administrator/development workflows with custom endpoints.

Native OS support follows the existing release builds (macOS 15 ARM/Intel and
Ubuntu 22.04 x86_64); the installer does not promise support for every Linux libc
or older macOS version. macOS deployment binds the daemon to the invoking client
UID; changing client accounts is an administrator operation.
