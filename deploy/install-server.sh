#!/bin/sh
# Run from an administrator-controlled checkout after installing omneumd.
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077
[ "$(id -u)" = 0 ] && [ "$(uname -s)" = Linux ] || exit 1
[ "$#" = 2 ] || { echo 'usage: install-server.sh PROXY PUBLIC_CONFIG' >&2; exit 1; }
exec /usr/bin/python3 -I "$(dirname "$(readlink -f "$0")")/install_server.py" "$1" "$2"
