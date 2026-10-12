#!/usr/bin/env bash
# Pinned official Linux x86_64 release; no mutable installer or unverified download.
set -euo pipefail
[[ $# == 1 && "$1" = /* ]] || { echo 'Usage: bash tools/install_mcp_publisher.sh /absolute/output-directory' >&2; exit 2; }
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { echo 'This CI installer requires Linux x86_64' >&2; exit 2; }
mkdir -p "$1"
archive="$1/mcp-publisher_linux_amd64.tar.gz"
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
  https://github.com/modelcontextprotocol/registry/releases/download/v1.8.1/mcp-publisher_linux_amd64.tar.gz --output "$archive"
printf '%s  %s\n' 'a06c9096dcb9727c13555b6be26c7effa707b01f06a4c561ba7a3635443cf2cc' "$archive" | sha256sum --check --strict
tar -xzf "$archive" -C "$1" mcp-publisher
"$1/mcp-publisher" --version
