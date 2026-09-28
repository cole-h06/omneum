"""Verify foreground daemon installation without a systemd service manager."""

import errno
import grp
import os
from pathlib import Path
import pwd
import shutil
import signal
import subprocess
import sys
import time

from omneum.daemon import DaemonServerContext
from omneum.oprf import OPRFError, VOPRFClient

ROOT = Path(__file__).resolve().parents[2]
KEY = Path("/var/lib/omneumd/voprf.key")
SOCKET = Path("/run/omneumd/eval.sock")
BINARY = Path("/usr/local/libexec/omneumd")
PEER = Path("/etc/omneumd/peer.conf")


def run(*args, check=True):
    return subprocess.run(
        args, check=check, capture_output=True, text=True, timeout=30
    )


def denied(path, flags):
    try:
        fd = os.open(path, flags)
    except OSError as error:
        assert error.errno in (errno.EACCES, errno.EPERM), error
    else:
        os.close(fd)
        raise AssertionError(f"access permitted: {path}")


def as_user(name, operation):
    account = pwd.getpwnam(name)
    read_fd, write_fd = os.pipe()
    pid = os.fork()

    if pid == 0:
        os.close(read_fd)
        try:
            os.initgroups(name, account.pw_gid)
            os.setgid(account.pw_gid)
            os.setuid(account.pw_uid)
            result = operation()
            os.write(write_fd, b"1" if result else b"0")
        except BaseException:
            import traceback

            traceback.print_exc()
            os._exit(1)
        os._exit(0)

    os.close(write_fd)
    with os.fdopen(read_fd, "rb") as pipe:
        result = pipe.read(1)

    assert os.waitpid(pid, 0)[1] == 0, f"{name} verification failed"
    return result == b"1"


def wait_ready(process):
    for _ in range(100):
        if process.poll() is not None:
            raise AssertionError("foreground daemon exited")
        if SOCKET.is_socket():
            return
        time.sleep(0.05)
    raise AssertionError("foreground daemon did not create socket")


def main(binary):
    assert sys.platform == "linux" and os.geteuid() == 0
    assert not KEY.parent.exists(), "use a fresh disposable host"

    installer = (ROOT / "deploy/install-foreground.sh").read_text()
    assert "/run/systemd/system" not in installer
    assert "systemctl" not in installer

    install = [
        "sh",
        str(ROOT / "deploy/install-foreground.sh"),
        str(Path(binary).resolve()),
    ]
    run(*install)

    crypto = pwd.getpwnam("omneum-crypto")
    mcp = pwd.getpwnam("omneum-mcp")
    ipc = grp.getgrnam("omneum-ipc")
    session = grp.getgrnam("omneum-session")

    assert crypto.pw_uid != mcp.pw_uid
    assert min(crypto.pw_uid, mcp.pw_uid) > 0
    assert session.gr_gid != ipc.gr_gid
    assert not session.gr_mem

    assert PEER.read_text() == (
        f"OMNEUM_MCP_UID={mcp.pw_uid}\n"
        f"OMNEUM_SESSION_GID={session.gr_gid}\n"
    )

    for path, owner, mode in (
        (KEY.parent, crypto.pw_uid, 0o700),
        (KEY, crypto.pw_uid, 0o600),
        (Path(mcp.pw_dir), mcp.pw_uid, 0o700),
        (SOCKET.parent, crypto.pw_uid, 0o750),
        (BINARY, 0, 0o755),
        (PEER, 0, 0o644),
    ):
        metadata = path.stat()
        assert metadata.st_uid == owner
        assert metadata.st_mode & 0o7777 == mode

    assert SOCKET.parent.stat().st_gid == ipc.gr_gid

    process = subprocess.Popen(
        [
            "runuser",
            "-u",
            "omneum-crypto",
            "-g",
            "omneum-ipc",
            "--",
            str(BINARY),
            "serve",
            "--client-uid",
            str(mcp.pw_uid),
            "--session-gid",
            str(session.gr_gid),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        wait_ready(process)

        assert SOCKET.stat().st_uid == crypto.pw_uid
        assert SOCKET.stat().st_gid == ipc.gr_gid
        assert SOCKET.stat().st_mode & 0o7777 == 0o660

        def client():
            denied(KEY, os.O_RDONLY)
            denied(KEY.parent, os.O_RDONLY | os.O_DIRECTORY)

            public = DaemonServerContext.fetch_public_key(
                str(SOCKET), crypto.pw_uid
            )
            context = DaemonServerContext(str(SOCKET), crypto.pw_uid, public)
            voprf = VOPRFClient(public)
            value = b"foreground verification"
            blind = voprf.blind(value)
            result = context.evaluate(blind.blinded_element)
            token = voprf.finalize(
                input_data=value,
                client_state=blind.client_state,
                evaluation=result,
            )
            return bool(token)

        assert as_user("omneum-mcp", client)

        users = Path("/tmp/omneum-foreground-users.conf")
        users.write_text(
            'u omneum-foreground-other - "Omneum test" '
            "/nonexistent /usr/sbin/nologin\n"
        )
        try:
            run("systemd-sysusers", str(users))
        finally:
            users.unlink(missing_ok=True)

        def unrelated():
            try:
                DaemonServerContext.fetch_public_key(
                    str(SOCKET), crypto.pw_uid
                )
            except OPRFError:
                return True
            raise AssertionError("unrelated peer accepted")

        assert as_user("omneum-foreground-other", unrelated)

        key_metadata = KEY.stat()
        run(*install)
        assert (KEY.stat().st_ino, KEY.stat().st_mtime_ns) == (
            key_metadata.st_ino,
            key_metadata.st_mtime_ns,
        )

        print(
            "PASS: foreground install, identities, key isolation, "
            "runtime socket, evaluation, peer authorization, repeated install"
        )
    finally:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if SOCKET.exists():
            SOCKET.unlink()


if __name__ == "__main__":
    main(sys.argv[1])
