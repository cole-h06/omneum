#!/bin/sh
# Offline, root-only artifact install. Never creates cloud resources or starts services.
set -eu
umask 022
[ "$(id -u)" = 0 ] || { echo 'Run as root on the approved Linux VM.' >&2; exit 1; }
[ "$(uname -s)" = Linux ] || exit 1
[ "$#" = 2 ] || { echo 'Usage: install.sh /root/artifacts /root/repository' >&2; exit 1; }
artifacts=$1
repository=$2
[ ! -e /opt/omneum-network ] && [ ! -L /opt/omneum-network ] || {
    echo 'Existing runtime: follow the documented upgrade/rollback procedure.' >&2; exit 1;
}
python3 - <<'PY'
import os, stat
from pathlib import Path
for target in ('/opt/omneum-network', '/etc/omneum-network', '/var/lib/omneum-network-crypto'):
    p = Path(target)
    if p.exists() or p.is_symlink():
        raise SystemExit('Refusing existing installation paths; follow recovery/upgrade instructions.')
    for ancestor in p.parents:
        s = ancestor.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
            raise SystemExit('Unsafe installation ancestor.')
PY
cd "$artifacts"
# Verify this manifest against a separately authenticated release digest first.
sha256sum --check SHA256SUMS
systemd-sysusers "$repository/deploy/network/vm/sysusers.conf"
install -d -o root -g root -m 0755 /opt/omneum-network /opt/omneum-network/libexec
python3 -m venv /opt/omneum-network/venv
/opt/omneum-network/venv/bin/pip install --no-index --find-links "$artifacts" \
    -r "$repository/deploy/network/requirements.txt" "$artifacts"/omneum-*.whl
[ "$("$artifacts/omneumd" capabilities)" = protected-voprf-v1 ] || {
    echo 'Unprotected daemon artifact.' >&2; exit 1;
}
install -o root -g root -m 0755 "$artifacts/omneumd" /opt/omneum-network/libexec/omneumd
install -d -o root -g root -m 0700 /etc/omneum-network /etc/omneum-network/secrets
install -d -o omneum-network-crypto -g omneum-network-ipc -m 0700 /var/lib/omneum-network-crypto
install -d -o root -g root -m 0755 /var/lib/omneum-acme /var/lib/omneum-acme/.well-known /var/lib/omneum-acme/.well-known/acme-challenge
install -o root -g root -m 0755 "$repository/deploy/network/vm/renew-certificates.sh" /opt/omneum-network/libexec/renew-certificates
install -o root -g root -m 0644 "$repository/deploy/network/vm/nginx-acme.conf" /etc/nginx/conf.d/omneum-acme.conf
install -o root -g root -m 0600 "$repository/deploy/network/vm/production.json" /etc/omneum-network/production.json
echo 'Installed offline artifacts. Configuration remains intentionally invalid; no services started.'
