"""Verify installation on a disposable macOS host using a real client user.

Run as root with the locked development Python environment. This installs the
daemon at its production paths. Do not run it on an existing deployment.
"""
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time

from click.testing import CliRunner
from typer.main import get_command

import omneum_oprf
from omneum.cli import app
from omneum.daemon import DaemonServerContext, get_daemon_socket, get_daemon_uid
from omneum.oprf import OPRFError, VOPRFClient
from omneum.paths import get_config_dir

ROOT = Path(__file__).resolve().parents[2]
KEY_DIR = Path("/Library/Application Support/OmneumCrypto")
KEY = KEY_DIR / "voprf.key"
SOCKET_DIR = Path("/Library/Application Support/OmneumIPC")
SOCKET = SOCKET_DIR / "eval.sock"
PLIST = Path("/Library/LaunchDaemons/ai.omneum.omneumd.plist")
BINARY = Path("/usr/local/libexec/omneumd")
LABEL = "system/ai.omneum.omneumd"
COMMAND = get_command(app)


def run(*args, check=True):
    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if check and result.returncode:
        if result.stdout:
            print(result.stdout, file=sys.stderr, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        result.check_returncode()
    return result


def ready():
    for _ in range(100):
        if SOCKET.exists() and run("launchctl", "print", LABEL, check=False).returncode == 0:
            return
        time.sleep(0.05)
    raise AssertionError("daemon did not start")


def as_uid(uid, operation):
    account = pwd.getpwuid(uid)
    read_fd, write_fd = os.pipe()
    pid = os.fork()

    if pid == 0:
        os.close(read_fd)
        try:
            os.initgroups(account.pw_name, account.pw_gid)
            os.setgid(account.pw_gid)
            os.setuid(account.pw_uid)
            os.environ["HOME"] = account.pw_dir
            result = operation()
            os.write(write_fd, json.dumps(result).encode())
        except BaseException:
            import traceback
            traceback.print_exc()
            os._exit(1)
        os._exit(0)

    os.close(write_fd)
    with os.fdopen(read_fd, "rb") as pipe:
        result = pipe.read(4096)

    assert os.waitpid(pid, 0)[1] == 0, "client verification failed"
    return json.loads(result)


def main(binary, client_uid):
    assert sys.platform == "darwin"
    assert os.geteuid() == 0
    assert client_uid > 0

    assert not PLIST.exists(), "use a fresh disposable host"
    assert not KEY_DIR.exists(), "use a fresh disposable host"
    assert not SOCKET_DIR.exists(), "use a fresh disposable host"
    assert not BINARY.exists(), "use a fresh disposable host"

    try:
        pwd.getpwnam("omneum-crypto")
    except KeyError:
        pass
    else:
        raise AssertionError("use a host without an existing omneum-crypto account")

    for name in (
        "OMNEUM_DAEMON_UID",
        "OMNEUM_DAEMON_SOCKET",
        "OMNEUM_CONFIG_DIR",
    ):
        os.environ.pop(name, None)

    config_dir = Path(tempfile.mkdtemp(prefix="omneum-config-"))
    client = pwd.getpwuid(client_uid)
    os.chown(config_dir, client_uid, client.pw_gid)
    config_dir.chmod(0o700)
    os.environ["OMNEUM_CONFIG_DIR"] = str(config_dir)

    install = [
        "sh",
        str(ROOT / "deploy/install-macos.sh"),
        str(binary),
        str(client_uid),
    ]

    try:
        run(*install)
        ready()

        crypto = pwd.getpwnam("omneum-crypto")

        assert crypto.pw_uid != 0
        assert crypto.pw_uid != client_uid

        for path, owner, mode in (
            (KEY_DIR, crypto.pw_uid, 0o700),
            (KEY, crypto.pw_uid, 0o600),
            (SOCKET_DIR, crypto.pw_uid, 0o750),
            (SOCKET, crypto.pw_uid, 0o660),
            (BINARY, 0, 0o755),
            (PLIST, 0, 0o644),
        ):
            metadata = path.stat()
            assert metadata.st_uid == owner, path
            assert metadata.st_mode & 0o7777 == mode, path

        def client_operation():
            public = DaemonServerContext.fetch_public_key(
                get_daemon_socket(),
                get_daemon_uid(),
            )
            context = DaemonServerContext(
                get_daemon_socket(),
                get_daemon_uid(),
                public,
            )
            voprf = VOPRFClient(public)
            value = b"macos install verification"
            blind = voprf.blind(value)
            evaluation = context.evaluate(blind.blinded_element)
            token = voprf.finalize(
                input_data=value,
                client_state=blind.client_state,
                evaluation=evaluation,
            )

            initialized = CliRunner().invoke(COMMAND, ["init"])
            assert initialized.exit_code == 0, initialized.output
            assert (get_config_dir() / "config.toml").exists()

            return public.hex(), token.hex()

        expected = as_uid(client_uid, client_operation)

        key_metadata = KEY.stat()
        crypto_uid = crypto.pw_uid

        run(*install)
        ready()

        assert pwd.getpwnam("omneum-crypto").pw_uid == crypto_uid
        assert (KEY.stat().st_ino, KEY.stat().st_mtime_ns) == (
            key_metadata.st_ino,
            key_metadata.st_mtime_ns,
        )
        assert as_uid(client_uid, client_operation) == expected

        try:
            DaemonServerContext.fetch_public_key(
                get_daemon_socket(),
                get_daemon_uid(),
            )
        except OPRFError:
            pass
        else:
            raise AssertionError("unauthorized root peer accepted")

        print(
            "PASS: install, launchd service, identities, permissions, "
            "VOPRF operation, init, repeated install"
        )
    finally:
        run("launchctl", "bootout", LABEL, check=False)
        shutil.rmtree(config_dir, ignore_errors=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), int(sys.argv[2]))
