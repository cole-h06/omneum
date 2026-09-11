#!/bin/sh

set -eu

PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
umask 077

fail() {
    printf '%s\n' "install-macos: $*" >&2
    exit 1
}

[ "$(uname -s)" = Darwin ] || fail 'macOS is required'
[ "$(id -u)" = 0 ] || fail 'root is required'
[ "$#" = 2 ] || fail 'usage: install-macos.sh DAEMON_BINARY CLIENT_UID'

daemon_binary=$1
client_uid=$2

case "$client_uid" in
    ''|*[!0-9]*) fail 'CLIENT_UID must be numeric' ;;
esac

[ "$client_uid" -gt 0 ] || fail 'CLIENT_UID must be non-root'
[ -f "$daemon_binary" ] && [ -x "$daemon_binary" ] || fail 'daemon binary is required'

source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
plist_template="$source_dir/launchd/ai.omneum.omneumd.plist"

[ -f "$plist_template" ] || fail 'LaunchDaemon template is missing'

if ! dscl . -read /Users/omneum-crypto >/dev/null 2>&1; then
    uid=450

    while dscl . -search /Users UniqueID "$uid" 2>/dev/null | grep -q .; do
        uid=$((uid + 1))
        [ "$uid" -lt 500 ] || fail 'no available service UID below 500'
    done

    dscl . -create /Users/omneum-crypto
    dscl . -create /Users/omneum-crypto UserShell /usr/bin/false
    dscl . -create /Users/omneum-crypto RealName "Omneum daemon"
    dscl . -create /Users/omneum-crypto UniqueID "$uid"
    dscl . -create /Users/omneum-crypto PrimaryGroupID 20
    dscl . -create /Users/omneum-crypto NFSHomeDirectory "/var/empty"
    dscl . -create /Users/omneum-crypto IsHidden 1
fi

crypto_uid=$(id -u omneum-crypto)

[ "$crypto_uid" -ne 0 ] || fail 'invalid daemon UID'
[ "$crypto_uid" -ne "$client_uid" ] || fail 'daemon and client UIDs must differ'

install -d -o omneum-crypto -g staff -m 0700 \
    "/Library/Application Support/OmneumCrypto"

install -d -o omneum-crypto -g staff -m 0750 \
    "/Library/Application Support/OmneumIPC"

install -d -o root -g wheel -m 0755 /usr/local/libexec

touch /var/log/omneumd.log
chown omneum-crypto:staff /var/log/omneumd.log
chmod 0600 /var/log/omneumd.log

install -o root -g wheel -m 0755 \
    "$daemon_binary" \
    /usr/local/libexec/omneumd

key="/Library/Application Support/OmneumCrypto/voprf.key"

if [ ! -e "$key" ]; then
    sudo -u omneum-crypto \
        /usr/local/libexec/omneumd provision >/dev/null
    printf '%s\n' 'Provisioned server key.'
fi

plist="/Library/LaunchDaemons/ai.omneum.omneumd.plist"
tmp=$(mktemp /tmp/omneumd-plist.XXXXXX)

sed "s/__OMNEUM_CLIENT_UID__/$client_uid/g" \
    "$plist_template" > "$tmp"

install -o root -g wheel -m 0644 "$tmp" "$plist"
rm -f "$tmp"

launchctl bootout system/ai.omneum.omneumd >/dev/null 2>&1 || true
launchctl bootstrap system "$plist"
launchctl enable system/ai.omneum.omneumd
launchctl kickstart -k system/ai.omneum.omneumd

attempt=0

while [ "$attempt" -lt 10 ]; do
    if [ -S "/Library/Application Support/OmneumIPC/eval.sock" ]; then
        printf '%s\n' 'Installed omneumd.'
        exit 0
    fi

    attempt=$((attempt + 1))
    sleep 1
done

printf '%s\n' '--- launchd status ---' >&2
launchctl print system/ai.omneum.omneumd >&2 || true
printf '%s\n' '--- daemon log ---' >&2
tail -n 100 /var/log/omneumd.log >&2 || true
fail 'daemon failed to start'
