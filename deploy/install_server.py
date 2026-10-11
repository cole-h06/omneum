"""Administrative installation only. Never invoked by the serving process."""
import fcntl
import grp
import io
import json
import os
import pwd
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path('/opt/omneum')
HERE = Path(__file__).resolve().parent


def trusted(path):
    """Require root ownership and no group/other write, including ACL mask bits."""
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError(f'untrusted installation path: {item}')


def unprivileged_python(*args):
    """Drop all credentials before bundled Python startup, including .pth imports."""
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise ValueError('Linux administrator verification required')
    account = pwd.getpwnam('omneum-mcp')
    if account.pw_uid <= 0 or account.pw_gid <= 0:
        raise ValueError('invalid runtime verification identity')
    python = ROOT / '.venv/bin/python'
    trusted(python.resolve(strict=True))
    if python.stat().st_mode & 0o6000:
        raise ValueError('privileged runtime executable')
    # util-linux setpriv changes real/effective/saved IDs before exec. NNP and
    # empty capability sets also prevent privilege gains through executable metadata.
    transition = Path('/usr/bin/setpriv')
    trusted(transition.resolve(strict=True))
    return subprocess.run(
        [str(transition), '--reuid', str(account.pw_uid),
         '--regid', str(account.pw_gid), '--clear-groups', '--no-new-privs',
         '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all',
         '--', str(python), '-I', '-B', *args],
        env={'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent'}, cwd='/',
        stdin=subprocess.DEVNULL, close_fds=True, check=True,
        capture_output=True, text=True, timeout=30,
    )


def inspect_runtime():
    """Privileged filesystem checks only; never start the bundled interpreter."""
    trusted(ROOT)
    for directory, dirs, files in os.walk(ROOT):
        for name in dirs + files:
            path = Path(directory)/name
            if path.is_symlink():
                target = path.resolve(strict=True)
                # uv interpreter aliases and lib64 are permitted; external
                # directories/import trees are not. /usr is the OS installation.
                if not target.is_relative_to(ROOT) and not (
                    target.is_relative_to('/usr') and target.is_file()
                    and path.parent == ROOT/'.venv/bin' and name.startswith('python')
                ):
                    raise ValueError(f'external runtime link: {path}')
                trusted(target)
                if path.lstat().st_uid != 0:
                    raise ValueError('runtime link must be root owned')
            else:
                trusted(path)


def runtime():
    inspect_runtime()
    inspected = unprivileged_python('-c', '''
import pathlib,sys,omneum,omneum_oprf
root=pathlib.Path('/opt/omneum')
assert pathlib.Path(omneum.__file__).resolve().is_relative_to(root)
assert pathlib.Path(omneum_oprf.__file__).resolve().is_relative_to(root)
for entry in sys.path:
    path=pathlib.Path(entry).resolve()
    assert path.is_relative_to(root) or path.is_relative_to('/usr'), path
assert sys.prefix == '/opt/omneum/.venv'
import json
print(json.dumps(sys.path))
''')
    # Also enforce ownership of OS-provided Python import trees, not merely
    # their /usr prefix. Missing standard-library zip paths need trusted parents.
    for entry in json.loads(inspected.stdout):
        path = Path(entry).resolve()
        trusted(path if path.exists() else path.parent)
        if path.is_relative_to(ROOT) or not path.is_dir():
            continue
        for directory, dirs, files in os.walk(path):
            for name in dirs + files:
                item = Path(directory)/name
                if item.is_symlink() and item.resolve().is_dir():
                    raise ValueError('external Python directory link')
                trusted(item.resolve())



def install(source, destination, mode):
    destination = Path(destination)
    trusted(destination.parent)
    if destination.exists() or destination.is_symlink():
        trusted(destination)
        if not destination.is_file() or destination.stat().st_nlink != 1:
            raise ValueError('invalid installed file')
    fd, staged = tempfile.mkstemp(prefix='.omneum-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as output, (io.BytesIO(source) if isinstance(source, bytes) else open(source, 'rb')) as input_file:
            shutil.copyfileobj(input_file, output)
            os.fchmod(output.fileno(), mode)
            output.flush()
            os.fsync(output.fileno())
        os.replace(staged, destination)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


def main(proxy, config):
    if os.geteuid() != 0 or not Path('/run/systemd/system').is_dir():
        raise ValueError('Linux systemd root installation required')
    runtime()
    session = grp.getgrnam('omneum-session')
    shadow = [line.split(':') for line in Path('/etc/gshadow').read_text().splitlines()
              if line.startswith('omneum-session:')]
    if (len(shadow) != 1 or not shadow[0][1].startswith(('!', '*'))
            or shadow[0][2] or shadow[0][3]):
        raise ValueError('session group must be locked without administrators')
    # pwd.getpwall includes live nss-systemd allocations. The reserved namespace
    # must have no persistent local accounts, but active instances are expected.
    accounts = [line.split(':') for line in Path('/etc/passwd').read_text().splitlines()]
    groups = [line.split(':') for line in Path('/etc/group').read_text().splitlines()]
    if (session.gr_gid == 0 or session.gr_mem
            or session.gr_gid in [g.gr_gid for g in grp.getgrall()
                                  if g.gr_name in ('omneum-ipc', 'omneum-client')]
            or any(int(p[3]) == session.gr_gid or
                   (p[0].startswith('omneum-') and p[0][7:8].isdigit())
                   for p in accounts)):
        raise ValueError('reserved session identity is in use')
    if any(int(g[2]) == session.gr_gid and g[0] != 'omneum-session' for g in groups):
        raise ValueError('session group has an alias')
    peer_config = Path('/etc/omneumd/peer.conf')
    trusted(peer_config)
    if f'OMNEUM_SESSION_GID={session.gr_gid}' not in peer_config.read_text().splitlines():
        raise ValueError('install the updated daemon first')
    for path in ('/etc/omneum', '/etc/omneum/run', '/usr/local/bin'):
        directory = Path(path)
        if not directory.exists():
            trusted(directory.parent)
            directory.mkdir(mode=0o755)
            directory.chmod(0o755)
        trusted(directory)
    # systemd may create mount-point directories here, but no host service
    # sockets or files belong in the replacement /run tree.
    for directory, dirs, files in os.walk('/etc/omneum/run'):
        if files:
            raise ValueError('private run directory contains files')
        for name in dirs:
            trusted(Path(directory)/name)
    lock = Path('/etc/omneum/install.lock')
    if lock.exists() or lock.is_symlink():
        trusted(lock)
    with open(lock, 'a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        # Read a possibly MCP-owned input with MCP credentials, never as root.
        # A raced symlink must not turn public-config import into a key read.
        supplied = subprocess.run(['runuser', '-u', 'omneum-mcp', '--',
                                   str(ROOT/'.venv/bin/python'), '-I', '-B', '-c',
                                   'import os,stat,sys; fd=os.open(sys.argv[1], os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW); '
                                   'assert stat.S_ISREG(os.fstat(fd).st_mode); sys.stdout.buffer.write(os.read(fd,4097))',
                                   str(Path(config).absolute())],
                                  capture_output=True, check=True, timeout=5).stdout
        if len(supplied) > 4096:
            raise ValueError('configuration is too large')
        target = Path('/etc/omneum/config.toml')
        if target.exists() or target.is_symlink():
            trusted(target)
            if target.read_bytes() != supplied:
                raise ValueError('existing configuration differs; administrator update required')
        else:
            install(supplied, target, 0o644)
        # The existing Python client authenticates the daemon and verifies the
        # supplied pin. No key provisioning, key read, or IPC duplication here.
        subprocess.run(['runuser', '-u', 'omneum-mcp', '--', 'env',
                        'OMNEUM_CONFIG_DIR=/etc/omneum',
                        'OMNEUM_DAEMON_SOCKET=/run/omneumd/eval.sock',
                        'OMNEUM_DAEMON_UID='+str(pwd.getpwnam('omneum-crypto').pw_uid),
                        str(ROOT/'.venv/bin/python'), '-I', '-B', '-c',
                        'from omneum.config import load_deployment_state; load_deployment_state()'],
                       check=True, timeout=30)
        install(HERE/'sysusers.d/omneum-server.conf', '/etc/sysusers.d/omneum-server.conf', 0o644)
        subprocess.run(['systemd-sysusers', '/etc/sysusers.d/omneum-server.conf'], check=True)
        install(proxy, '/usr/local/bin/omneum-server', 0o755)
        for name in ('omneum-server.socket', 'omneum-server@.service'):
            install(HERE/'systemd'/name, '/etc/systemd/system'/Path(name), 0o644)
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'enable', '--now', 'omneum-server.socket'], check=True)
        print('Installed omneum-server.')


if __name__ == '__main__':
    try:
        main(*sys.argv[1:])
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        sys.exit(f'install: {error}')
