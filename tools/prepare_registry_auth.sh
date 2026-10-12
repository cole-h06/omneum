#!/usr/bin/env bash
# Generate local proof material only. Never log or commit the private seed.
set +x
set -euo pipefail
if [[ $# != 1 ]]; then
  echo 'Usage: OPENSSL=/path/to/openssl3 bash tools/prepare_registry_auth.sh /absolute/private/output-directory' >&2
  exit 2
fi
umask 077
output=$1
[[ "$output" = /* && ! -e "$output" ]] || { echo 'Use a new absolute directory outside the repository' >&2; exit 2; }
repo=$(cd "$(dirname "$0")/.." && pwd -P)
mkdir -p "$(dirname "$output")"
parent=$(cd "$(dirname "$output")" && pwd -P)
[[ "$parent" != "$repo" && "$parent" != "$repo/"* ]] || { echo 'Private output must be outside the repository' >&2; exit 2; }
# Refuse every Git worktree, including sibling release/integration checkouts.
if git -C "$parent" rev-parse --show-toplevel >/dev/null 2>&1; then
  echo 'Private output must be outside every Git worktree' >&2
  exit 2
fi
mkdir -m 700 "$output"
openssl_bin=${OPENSSL:-openssl}
"$openssl_bin" genpkey -algorithm Ed25519 -out "$output/key.pem"
public_key=$("$openssl_bin" pkey -in "$output/key.pem" -pubout -outform DER | tail -c 32 | base64 | tr -d '\n')
printf 'v=MCPv1; k=ed25519; p=%s\n' "$public_key" > "$output/mcp-registry-auth"
printf 'omneum.ai. IN TXT "v=MCPv1; k=ed25519; p=%s"\n' "$public_key" > "$output/dns-record.txt"
"$openssl_bin" pkey -in "$output/key.pem" -outform DER | tail -c 32 | od -An -v -tx1 | tr -d ' \n' > "$output/private-key.hex"
printf '\n' >> "$output/private-key.hex"
cat "$output/dns-record.txt"
