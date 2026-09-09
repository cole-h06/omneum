#!/bin/sh
# Install from an administrator-controlled checkout using a production daemon binary.

set -eu

PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077

fail() { printf '%s\n' "install: $*" >&2; exit 1; }

[ "$(uname -s)" = Linux ] || fail 'Linux is required'
[ "$(id -u)" = 0 ] || fail 'root is required'
[ "$#" = 1 ] || fail 'usage: install.sh DAEMON_BINARY'
[ -f "$1" ] && [ -x "$1" ] || fail 'daemon binary is required'

binary=$(readlink -f -- "$1")
source_dir=$(dirname -- "$(readlink -f -- "$0")")

[ -d /run/systemd/system ] || fail 'systemd is required'

# These paths are administrator-owned. Never follow a link or repair an
# application-owned parent before installing privileged files beneath it.
root_dir() {
    [ ! -L "$1" ] || fail 'directory is a symlink'

    if [ ! -e "$1" ]; then mkdir -m 0755 -- "$1"; fi

    [ -d "$1" ] && [ "$(stat -c %u -- "$1")" = 0 ] || fail 'invalid directory owner'

    mode=$(stat -c %a -- "$1")
    [ $((0$mode & 0022)) = 0 ] || fail 'directory is writable by group or others'
}

root_file() {
    [ ! -L "$1" ] || fail 'file is a symlink'

    if [ -e "$1" ]; then
        [ -f "$1" ] && [ "$(stat -c %u -- "$1")" = 0 ] &&
            [ "$(stat -c %h -- "$1")" = 1 ] || fail 'invalid file owner or type'
    fi
}

copy_file() {
    root_file "$2"

    if [ -f "$2" ] && cmp -s -- "$1" "$2" && [ "$(stat -c %a -- "$2")" = "$3" ]; then
        return
    fi

    staged=$(mktemp "$(dirname -- "$2")/.omneum.XXXXXX")
    install -o root -g root -m "$3" -- "$1" "$staged"
    mv -fT -- "$staged" "$2"
}

for directory in /etc /etc/omneumd; do root_dir "$directory"; done

root_file /etc/omneumd/install.lock
exec 9>/etc/omneumd/install.lock
flock -x 9

for directory in /usr /usr/local /usr/local/libexec /etc/sysusers.d /etc/systemd /etc/systemd/system /var /var/lib; do
    root_dir "$directory"
done

copy_file "$source_dir/sysusers.d/omneum.conf" /etc/sysusers.d/omneum.conf 644
systemd-sysusers /etc/sysusers.d/omneum.conf

crypto_uid=$(id -u omneum-crypto)
mcp_uid=$(id -u omneum-mcp)
session_gid=$(getent group omneum-session | cut -d: -f3)
client_gid=$(getent group omneum-client | cut -d: -f3)
# This group conveys evaluator authority through the primary peer credential,
# not through filesystem/supplementary-group membership. Reserve it for units.
[ -n "$session_gid" ] && [ "$session_gid" != 0 ] &&
    [ "$session_gid" != "$(getent group omneum-ipc | cut -d: -f3)" ] || fail 'invalid session group'
[ -z "$client_gid" ] || [ "$session_gid" != "$client_gid" ] || fail 'session and frontend groups must differ'
[ -z "$(getent group omneum-session | cut -d: -f4)" ] || fail 'session group has members'
getent gshadow omneum-session | awk -F: '$1 == "omneum-session" && $2 ~ /^[!*]/ && $3 == "" && $4 == "" { ok=1 } END { exit !ok }' || fail 'session group must be locked without administrators'
# nss-systemd enumerates live dynamic users too. Check persistent local records;
# live allocations are expected and must not make a reinstall fail.
getent -s files passwd | awk -F: -v gid="$session_gid" '$4 == gid || $1 ~ /^omneum-[0-9]/ { bad=1 } END { exit bad }' || fail 'reserved session identity is in use'
getent -s files group | awk -F: -v gid="$session_gid" '$3 == gid && $1 != "omneum-session" { bad=1 } END { exit bad }' || fail 'session group has an alias'

[ "$crypto_uid" != 0 ] && [ "$mcp_uid" != 0 ] && [ "$crypto_uid" != "$mcp_uid" ] || fail 'invalid service UIDs'

# sysusers records the MCP home but does not create it.
[ ! -L /var/lib/omneum ] || fail 'MCP directory is a symlink'

if [ ! -e /var/lib/omneum ]; then
    install -d -o omneum-mcp -g "$(id -g omneum-mcp)" -m 0700 /var/lib/omneum
fi

[ -d /var/lib/omneum ] && [ "$(stat -c %u /var/lib/omneum)" = "$mcp_uid" ] &&
    [ "$(stat -c %a /var/lib/omneum)" = 700 ] || fail 'invalid MCP directory'

# Do not repair or replace existing key storage during installation.
[ ! -L /var/lib/omneumd ] || fail 'key directory is a symlink'

if [ ! -e /var/lib/omneumd ]; then
    install -d -o omneum-crypto -g omneum-ipc -m 0700 /var/lib/omneumd
fi

[ -d /var/lib/omneumd ] && [ "$(stat -c %u /var/lib/omneumd)" = "$crypto_uid" ] &&
    [ "$(stat -c %a /var/lib/omneumd)" = 700 ] || fail 'invalid key directory'

if [ ! -e /var/lib/omneumd/voprf.key ] && [ ! -L /var/lib/omneumd/voprf.key ]; then
    [ ! -e /etc/omneumd/peer.conf ] && [ ! -e /etc/systemd/system/omneumd.service ] || fail 'server key is missing'
    provision=yes
else
    provision=no
fi

copy_file "$binary" /usr/local/libexec/omneumd 755

if [ "$provision" = yes ]; then
    runuser -u omneum-crypto -- /usr/local/libexec/omneumd provision >/dev/null
    printf '%s\n' 'Provisioned server key.'
fi

peer_file=$(mktemp /etc/omneumd/.peer.XXXXXX)

trap 'rm -f -- "$peer_file"' EXIT
trap 'exit 1' HUP INT TERM

printf 'OMNEUM_MCP_UID=%s\n' "$mcp_uid" >"$peer_file"
printf 'OMNEUM_SESSION_GID=%s\n' "$session_gid" >>"$peer_file"

copy_file "$peer_file" /etc/omneumd/peer.conf 644
copy_file "$source_dir/systemd/omneumd.service" /etc/systemd/system/omneumd.service 644

systemctl daemon-reload
systemctl enable omneumd.service
systemctl restart omneumd.service

# Type=exec confirms exec, not socket readiness. Wait for the socket below.
attempt=0

while [ "$attempt" -lt 10 ]; do
    if systemctl is-active --quiet omneumd.service && [ -S /run/omneumd/eval.sock ]; then
        printf '%s\n' 'Installed omneumd.'
        exit 0
    fi

    attempt=$((attempt + 1))
    sleep 1
done

fail 'daemon failed to start'
