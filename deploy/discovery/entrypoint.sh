#!/bin/sh
# Fresh single-session sandbox; never install this on a production host.
set -eu
umask 077
ulimit -c 0
[ "${OMNEUM_DISCOVERY_SANDBOX:-}" = 1 ] || { echo 'sandbox bootstrap is disabled outside the discovery image' >&2; exit 1; }
[ "$(id -u)" = 0 ] || { echo 'sandbox bootstrap requires container root' >&2; exit 1; }
[ ! -e /var/lib/omneumd/voprf.key ] || { echo 'use a fresh disposable sandbox' >&2; exit 1; }
# No caller-selected key/socket/config overrides or private network credential.
unset OMNEUM_DAEMON_UID OMNEUM_DAEMON_SOCKET
export OMNEUM_CONFIG_DIR=/var/lib/omneum/config
sh /opt/omneum-discovery/install-foreground.sh /opt/omneum-discovery/omneumd >&2
crypto_uid=$(id -u omneum-crypto)
mcp_uid=$(id -u omneum-mcp)
session_gid=$(getent group omneum-session | cut -d: -f3)
[ "$crypto_uid" != "$mcp_uid" ]
[ "$(/opt/omneum-discovery/omneumd capabilities)" = protected-voprf-v1 ]
runuser -u omneum-crypto -g omneum-ipc -- /usr/local/libexec/omneumd serve \
  --client-uid "$mcp_uid" --session-gid "$session_gid" >&2 &
daemon_pid=$!
trap 'kill "$daemon_pid" 2>/dev/null || true; wait "$daemon_pid" 2>/dev/null || true' EXIT
trap 'exit 1' HUP INT TERM
attempt=0
until [ -S /run/omneumd/eval.sock ]; do
  kill -0 "$daemon_pid" || exit 1
  attempt=$((attempt + 1))
  [ "$attempt" -lt 100 ] || { echo 'daemon readiness timed out' >&2; exit 1; }
  sleep 0.05
done
runuser -u omneum-mcp -- /usr/local/bin/python -I -B -m omneum.cli init >&2
case "${1:-stdio}" in
  stdio) runuser -u omneum-mcp -- /opt/omneum-discovery/omneum-server ;;
  probe) runuser -u omneum-mcp -- /usr/local/bin/python -I -B /opt/omneum-discovery/probe.py ;;
  *) echo 'allowed modes: stdio, probe' >&2; exit 1 ;;
esac
