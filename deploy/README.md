# Linux installation

On a systemd-based Linux host with `systemd-sysusers`, `runuser`, `flock`, and
GNU coreutils, build and install the daemon from an administrator-controlled
checkout:

```sh
cargo build --locked --release --no-default-features --features daemon --bin omneumd
sudo sh deploy/install.sh target/release/omneumd
```

The installer creates persistent `omneum-crypto` and `omneum-mcp` accounts and
the `omneum-ipc` group without fixed IDs. It installs the daemon and systemd unit
root-owned, records the resolved MCP UID in `/etc/omneumd/peer.conf`, and
provisions a new server key. Reinstalling restarts the service and preserves its
accounts and key. An existing installation with a missing or invalid key requires
administrator action; installation never replaces that key.

`RuntimeDirectory=` creates `/run/omneumd` as `omneum-crypto:omneum-ipc` with
mode `0750`. The daemon creates `eval.sock` with mode `0660`. The private key
remains in `/var/lib/omneumd`, owned by `omneum-crypto`, with directory mode
`0700` and key mode `0600`. Do not install a `test-daemon` build.

Install the core Python environment with `uv sync --locked --no-default-groups`
at a location readable and executable by `omneum-mcp`. Run initialization as
that account using the environment's absolute executable paths:

```sh
sudo -H -u omneum-mcp /path/to/.venv/bin/omneum init
sudo -H -u omneum-mcp /path/to/.venv/bin/omneum-server
```

`init` gets the initial public key from the authenticated local daemon and writes
public configuration under the MCP account's home. `--public-key-hex` can be used
to require an expected key. Existing pins are never overwritten. Applications
that launch the MCP server over stdio must run it under the same account.

Inspect the service with:

```sh
systemctl status omneumd
sudo journalctl -u omneumd
```

Python does not provision or read the VOPRF private key.