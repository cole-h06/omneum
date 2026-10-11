#!/bin/sh
# Certbot deploy hook. Certificate paths in the root-owned production config are
# private root-owned copies of the validated certbot lineage, not API-owned files.
set -eu
[ "$(id -u)" = 0 ] || exit 1
/opt/omneum-network/venv/bin/python -I -B -m omneum.network_deploy install-certificates
nginx -t
systemctl reload nginx
# LoadCredential copies certificate material only at process start.
systemctl try-restart omneum-network-ingestion.service omneum-network-enrollment.service
