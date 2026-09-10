"""Verify installation on a disposable Linux systemd host, using its real users.

Run as root with the locked development Python environment. This installs the
service at its production paths. Do not run it on an existing deployment.
"""
import errno
import grp
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib

# Load the application before dropping identity, so the test runner may live in
# a root/CI checkout. Serving and all access checks execute as the real users.
import omneum_oprf
from omneum.daemon import DaemonServerContext, get_daemon_socket, get_daemon_uid
from omneum.oprf import VOPRFClient, OPRFError
from omneum.cli import app
from omneum.paths import get_config_dir
from typer.main import get_command
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[2]
KEY = Path('/var/lib/omneumd/voprf.key')
SOCKET = Path('/run/omneumd/eval.sock')
UNIT = Path('/etc/systemd/system/omneumd.service')
PEER = Path('/etc/omneumd/peer.conf')
BINARY = Path('/usr/local/libexec/omneumd')
COMMAND = get_command(app)


def run(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=30)


def denied(path, flags):
    try:
        fd = os.open(path, flags)
    except OSError as error:
        assert error.errno in (errno.EACCES, errno.EPERM), error
    else:
        os.close(fd)
        raise AssertionError(f'access permitted: {path}')


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
            os.environ["HOME"] = account.pw_dir
            os.environ.pop("XDG_CONFIG_HOME", None)
            result = operation()
            os.write(write_fd, json.dumps(result).encode())
        except BaseException:
            import traceback
            traceback.print_exc()
            os._exit(1)
        os._exit(0)
    os.close(write_fd)
    with os.fdopen(read_fd, 'rb') as pipe:
        result = pipe.read(4096)
    assert os.waitpid(pid, 0)[1] == 0, f'{name} verification failed'
    return json.loads(result)


def properties():
    output = run('systemctl', 'show', 'omneumd.service').stdout
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


def ready():
    for _ in range(100):
        if SOCKET.exists() and properties()['ActiveState'] == 'active':
            return
        time.sleep(.05)
    raise AssertionError('daemon did not start')


def main(binary):
    assert sys.platform == 'linux' and os.geteuid() == 0
    assert Path('/run/systemd/system').is_dir(), 'systemd is required'
    assert not UNIT.exists() and not KEY.parent.exists(), 'use a fresh disposable host'
    for name in ('OMNEUM_DAEMON_UID', 'OMNEUM_DAEMON_SOCKET', 'OMNEUM_CONFIG_DIR'):
        os.environ.pop(name, None)
    get_command(app)  # load CLI command definitions before switching UID
    directory = Path(tempfile.mkdtemp(prefix='omneum-install-', dir='/run'))
    directory.chmod(0o755)
    install = ['sh', str(ROOT/'deploy/install.sh'), str(binary)]
    try:
        run(*install)
        ready()
        crypto = pwd.getpwnam('omneum-crypto')
        mcp = pwd.getpwnam('omneum-mcp')
        ipc = grp.getgrnam('omneum-ipc')
        assert crypto.pw_uid != mcp.pw_uid and min(crypto.pw_uid, mcp.pw_uid) > 0
        assert ipc.gr_gid in os.getgrouplist('omneum-mcp', mcp.pw_gid)
        session = grp.getgrnam('omneum-session')
        assert not session.gr_mem and session.gr_gid != ipc.gr_gid
        assert PEER.read_text() == f'OMNEUM_MCP_UID={mcp.pw_uid}\nOMNEUM_SESSION_GID={session.gr_gid}\n'
        settings = properties()
        assert settings['Type'] == 'exec' and settings['Restart'] == 'on-failure'
        assert settings['User'] == 'omneum-crypto' and settings['Group'] == 'omneum-ipc'
        for setting in ('NoNewPrivileges', 'ProtectHome', 'PrivateDevices',
                        'ProtectKernelTunables', 'ProtectKernelModules', 'ProtectControlGroups',
                        'RestrictSUIDSGID', 'RestrictRealtime', 'LockPersonality'):
            assert settings[setting] == 'yes', (setting, settings[setting])
        assert settings['ProtectSystem'] == 'strict'
        assert settings['RestrictAddressFamilies'] == 'AF_UNIX'
        assert settings['SystemCallArchitectures'] == 'native'
        assert settings['UMask'] == '0077'
        pid = settings['MainPID']
        process_status = Path(f'/proc/{pid}/status').read_text()
        uid_line = next(line for line in process_status.splitlines() if line.startswith('Uid:'))
        assert set(uid_line.split()[1:]) == {str(crypto.pw_uid)}
        for path, owner, mode in ((KEY.parent, crypto.pw_uid, 0o700),
                                  (KEY, crypto.pw_uid, 0o600),
                                  (Path(mcp.pw_dir), mcp.pw_uid, 0o700),
                                  (SOCKET.parent, crypto.pw_uid, 0o750),
                                  (SOCKET, crypto.pw_uid, 0o660),
                                  (BINARY, 0, 0o755), (UNIT, 0, 0o644), (PEER, 0, 0o644)):
            metadata = path.stat()
            assert metadata.st_uid == owner and metadata.st_mode & 0o7777 == mode
        assert SOCKET.stat().st_gid == ipc.gr_gid
        assert SOCKET.parent.stat().st_gid == ipc.gr_gid

        def client():
            denied(KEY, os.O_RDONLY)
            denied(KEY.parent, os.O_RDONLY | os.O_DIRECTORY)
            for path in (BINARY, UNIT, PEER, Path('/etc/sysusers.d/omneum.conf')):
                denied(path, os.O_WRONLY)
            public = DaemonServerContext.fetch_public_key(get_daemon_socket(), get_daemon_uid())
            context = DaemonServerContext(get_daemon_socket(), get_daemon_uid(), public)
            voprf = VOPRFClient(public)
            value = b'install verification'
            blind = voprf.blind(value)
            result = context.evaluate(blind.blinded_element)
            token = voprf.finalize(input_data=value, client_state=blind.client_state, evaluation=result)
            config_dir = get_config_dir()
            initialized = CliRunner().invoke(COMMAND, ['init'])
            assert initialized.exit_code == 0, initialized.output
            saved = (config_dir/'config.toml').read_bytes()
            assert CliRunner().invoke(COMMAND, ['init']).exit_code == 0
            assert (config_dir/'config.toml').read_bytes() == saved
            assert tomllib.loads(saved.decode())['voprf_key_version'] == 1
            return public.hex(), token.hex()

        expected = as_user('omneum-mcp', client)
        key_metadata = KEY.stat()
        before_ids = crypto.pw_uid, mcp.pw_uid, ipc.gr_gid
        run(*install)
        ready()
        assert before_ids == (pwd.getpwnam('omneum-crypto').pw_uid,
                              pwd.getpwnam('omneum-mcp').pw_uid, grp.getgrnam('omneum-ipc').gr_gid)
        assert (KEY.stat().st_ino, KEY.stat().st_mtime_ns) == (key_metadata.st_ino, key_metadata.st_mtime_ns)
        assert as_user('omneum-mcp', client) == expected

        users = directory/'users.conf'
        users.write_text('u omneum-other - "Omneum test" /nonexistent /usr/sbin/nologin\n')
        run('systemd-sysusers', str(users))
        def unrelated():
            denied(KEY, os.O_RDONLY)
            try:
                DaemonServerContext.fetch_public_key(get_daemon_socket(), get_daemon_uid())
            except OPRFError:
                return True
            raise AssertionError('unrelated peer accepted')
        assert as_user('omneum-other', unrelated)
        SOCKET.parent.chmod(0o755)
        SOCKET.chmod(0o666)
        try:
            assert as_user('omneum-other', unrelated)
        finally:
            SOCKET.parent.chmod(0o750)
            SOCKET.chmod(0o660)

        # Installation must neither repair invalid key permissions nor replace a
        # missing key. The existing daemon remains responsible for key validation.
        run('systemctl', 'stop', 'omneumd.service')
        KEY.chmod(0o640)
        assert run(*install, check=False).returncode != 0
        run('systemctl', 'stop', 'omneumd.service')
        assert KEY.stat().st_mode & 0o777 == 0o640
        KEY.chmod(0o600)
        saved_key = KEY.with_suffix('.saved')
        KEY.rename(saved_key)
        try:
            assert run(*install, check=False).returncode != 0
            assert not KEY.exists()
            KEY.symlink_to(saved_key)
            assert run(*install, check=False).returncode != 0
            run('systemctl', 'stop', 'omneumd.service')
            assert KEY.is_symlink()
            KEY.unlink()
        finally:
            saved_key.rename(KEY)
        run('systemctl', 'reset-failed', 'omneumd.service')
        run('systemctl', 'start', 'omneumd.service')
        ready()
        assert as_user('omneum-mcp', client) == expected
        print('PASS: install, systemd settings, service UIDs, operations, access checks, key checks, repeated install')
    finally:
        run('systemctl', 'stop', 'omneumd.service', check=False)
        shutil.rmtree(directory)


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
