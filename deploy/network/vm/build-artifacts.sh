#!/bin/sh
# Run on a trusted Linux build host matching the VM's architecture and Python.
set -eu
[ "$(uname -s)" = Linux ] || { echo 'Build on Linux.' >&2; exit 1; }
[ "$#" = 1 ] || { echo 'Usage: build-artifacts.sh /absolute/new/artifact-directory' >&2; exit 1; }
case "$1" in /*) ;; *) exit 1 ;; esac
mkdir -m 0700 "$1"
artifact_dir=$(realpath "$1")
export RUSTUP_TOOLCHAIN=1.90.0
python3 -m venv "$artifact_dir/build-venv"
"$artifact_dir/build-venv/bin/pip" install maturin==1.15.0
"$artifact_dir/build-venv/bin/maturin" build --locked --release --interpreter python3 --out "$artifact_dir"
cargo +1.90.0 build --locked --release --no-default-features --features daemon --bin omneumd
install -m 0755 target/release/omneumd "$artifact_dir/omneumd"
"$artifact_dir/build-venv/bin/pip" download -r deploy/network/requirements.txt --dest "$artifact_dir"
# Remove only this script's just-created build environment, not caller paths.
rm -rf "$artifact_dir/build-venv"
python3 - "$artifact_dir" <<'PY'
import hashlib, json, platform, subprocess, sys
from pathlib import Path
p = Path(sys.argv[1])
(p/'build-info.json').write_text(json.dumps(dict(python=platform.python_version(), machine=platform.machine(),
    revision=subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
    diff_sha256=hashlib.sha256(subprocess.check_output(['git','diff','HEAD'])).hexdigest(), rust='1.90.0'), indent=2))
(p/'SHA256SUMS').write_text(''.join(hashlib.sha256(f.read_bytes()).hexdigest()+'  '+f.name+'\n'
    for f in sorted(p.iterdir()) if f.is_file() and f.name != 'SHA256SUMS'))
PY
echo 'Authenticate the SHA256SUMS digest separately before installing the artifact bundle.'
