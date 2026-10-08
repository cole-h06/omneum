"""Root orchestration of the existing Linux daemon and managed-server installers.

Invoked only from a verified bundle. No downloads, package resolution, or private-key IO.
"""
import fcntl
import grp
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path('/opt/omneum')
BUNDLE_FILES = (
    'omneumd', 'omneum-server', 'install.sh', 'install-server.sh', 'install_server.py',
    'runtime_bundle.py', 'runtime.tar.gz', 'systemd/omneumd.service',
    'systemd/omneum-server.socket', 'systemd/omneum-server@.service',
    'sysusers.d/omneum.conf', 'sysusers.d/omneum-server.conf',
)


def trusted(path):
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('untrusted installation path: ' + str(item))


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(source, destination, uid):
    # Open every source component without following links; never copy privileged
    # files through a raced symlink in a caller-owned bundle.
    for name in BUNDLE_FILES:
        fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in Path(name).parts[:-1]:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            file_fd = os.open(Path(name).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(file_fd, 'rb') as contents:
                info = os.fstat(contents.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != uid or info.st_size > 512 * 1024 * 1024:
                    raise ValueError('invalid bundle file: ' + name)
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as output:
                    shutil.copyfileobj(contents, output)
                target.chmod(0o755 if name in ('omneumd', 'omneum-server') or name.endswith('.sh') else 0o644)
        finally:
            os.close(fd)


def run(*args):
    subprocess.run(args, check=True, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/root'})


def provision_runtime(bundle, version):
    validator = load_module(bundle / 'install_server.py', 'managed_installer')
    if ROOT.exists() or ROOT.is_symlink():
        # Never replace an existing runtime under live sessions or silently repair it.
        validator.inspect_runtime()
        if json.loads((ROOT / 'runtime.json').read_text()) != {'format': 1, 'version': version, 'prefix': str(ROOT)}:
            raise ValueError('existing runtime differs; administrator upgrade required')
        return
    runtime = load_module(bundle / 'runtime_bundle.py', 'runtime_bundle')
    with tempfile.TemporaryDirectory(prefix='.omneum-runtime-', dir=ROOT.parent) as temporary:
        staged = Path(temporary) / 'runtime'
        with (bundle / 'runtime.tar.gz').open('rb') as source:
            runtime.unpack(source, staged, version)
        staged.chmod(0o755)
        staged.rename(ROOT)
    validator.inspect_runtime()


def initialize_and_install_server(bundle, version):
    python = str(ROOT / '.venv/bin/python')
    # Accounts exist now. Verify application imports only after dropping credentials.
    validator = load_module(bundle / 'install_server.py', 'managed_installer')
    validator.runtime()
    validator.unprivileged_python('-c',
        'from importlib.metadata import version; import sys; assert version("omneum") == sys.argv[1]', version)
    config = Path('/var/lib/omneum/.config/Omneum/config.toml')
    if Path('/etc/omneum/config.toml').exists():
        config = Path('/etc/omneum/config.toml')
    run('/usr/sbin/runuser', '-u', 'omneum-mcp', '--', '/usr/bin/env', '-i',
        'PATH=/usr/bin:/bin', 'HOME=/var/lib/omneum', 'OMNEUM_CONFIG_DIR=' + str(config.parent),
        python, '-I', '-B', '-m', 'omneum.cli', 'init')
    run('/bin/sh', str(bundle / 'install-server.sh'), str(bundle / 'omneum-server'), str(config))


def grant_frontend(account):
    # The public group conveys access only to the proxy socket, never the daemon.
    groups = os.getgrouplist(account.pw_name, account.pw_gid)
    forbidden = {grp.getgrnam(name).gr_gid for name in ('omneum-ipc', 'omneum-session')}
    if forbidden.intersection(groups):
        raise ValueError('login user already has protected daemon group membership; administrator review required')
    run('/usr/sbin/usermod', '-a', '-G', 'omneum-client', account.pw_name)


def install_stack(bundle, version, account):
    provision_runtime(bundle, version)
    run('/bin/sh', str(bundle / 'install.sh'), str(bundle / 'omneumd'))
    initialize_and_install_server(bundle, version)
    grant_frontend(account)


def main(source, uid, version):
    if sys.platform != 'linux' or os.geteuid() != 0 or not Path('/run/systemd/system').is_dir():
        raise ValueError('Linux systemd administrator installation required')
    uid = int(uid)
    account = pwd.getpwuid(uid)
    if uid <= 0 or account.pw_name.startswith('omneum-') or int(os.environ.get('SUDO_UID', '-1')) != uid:
        raise ValueError('installation must be requested by the normal sudo login user')
    os.umask(0o077)
    for path in (Path('/opt'), Path('/usr/local/bin')):
        trusted(path)
    for tool in ('/usr/sbin/runuser', '/usr/sbin/usermod', '/usr/bin/sg', '/usr/bin/setpriv'):
        if not Path(tool).is_file():
            raise ValueError('required system tool is missing: ' + tool)
    lock = Path('/opt/.omneum-install.lock')
    fd = os.open(lock, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, 'w') as guard:
        trusted(lock)
        info = os.fstat(guard.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('invalid installation lock')
        fcntl.flock(guard, fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix='.omneum-bundle-', dir='/opt') as temporary:
            bundle = Path(temporary)
            snapshot(Path(source), bundle, uid)
            install_stack(bundle, version, account)


if __name__ == '__main__':
    try:
        main(*sys.argv[1:])
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        sys.exit('install: ' + str(error))
