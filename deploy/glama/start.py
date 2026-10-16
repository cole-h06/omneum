"""Run the existing foreground evaluator and MCP server with separate OS users."""
import grp
import os
from pathlib import Path
import pwd
import signal
import subprocess
import sys
import time


ROOT = Path("/opt/omneum-glama")


def main():
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("The inspection container must start as Linux root to drop service credentials")
    os.umask(0o077)
    # Reuse the production installer and identities, without systemd, test mode,
    # network enrollment, or granting the MCP process access to the private key.
    subprocess.run(["/bin/sh", str(ROOT / "daemon/install-foreground.sh"),
                    str(ROOT / "daemon/omneumd")], check=True, stdout=sys.stderr)
    uid = pwd.getpwnam("omneum-mcp").pw_uid
    session_gid = grp.getgrnam("omneum-session").gr_gid
    daemon = subprocess.Popen([
        "/usr/sbin/runuser", "-u", "omneum-crypto", "-g", "omneum-ipc", "--",
        "/usr/local/libexec/omneumd", "serve", "--client-uid", str(uid),
        "--session-gid", str(session_gid),
    ], stdin=subprocess.DEVNULL, stdout=sys.stderr, stderr=sys.stderr)
    server = None

    def stop(signum, _frame):
        raise SystemExit(128 + signum)

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, stop)
    environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/var/lib/omneum",
                   "PYTHONUNBUFFERED": "1"}
    command = ["/usr/sbin/runuser", "-u", "omneum-mcp", "--", sys.executable, "-I", "-m"]
    try:
        subprocess.run([*command, "omneum.cli", "init"], env=environment,
                       check=True, timeout=30, stdout=sys.stderr)
        server = subprocess.Popen([*command, "omneum.server"], env=environment)
        while server.poll() is None:
            if daemon.poll() is not None:
                raise RuntimeError("Protected evaluator exited")
            time.sleep(0.05)
        return server.returncode
    finally:
        for process in (server, daemon):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    sys.exit(main())
