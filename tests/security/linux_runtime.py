"""Root-only managed runtime verification on a disposable systemd Linux host.

Run after linux_install.py with a production, root-owned /opt/omneum runtime.
The temporary admin service override changes only ExecStart and test PID input;
all production identity, namespace, filesystem, and network controls remain.
"""
import asyncio
from datetime import datetime, timezone
import grp
import json
import os
from pathlib import Path
import pwd
import select
import socket
import subprocess
import sys
import time

ROOT = Path('/opt/omneum')
PROXY = '/usr/local/bin/omneum-server'
CONFIG = '/var/lib/omneum/.config/Omneum/config.toml'
CLIENT = 'omneum-test-client'


def run(*args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=60, **kwargs)
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result


async def workload():
    from mcp import ClientSession, StdioServerParameters, stdio_client
    from omneum.client import OmneumClientConfig, open_stdio_client
    from omneum.information import Claim, Observation, Source
    from omneum.dependency import DependencyEstimatorConfig
    os.environ['OMNEUM_CONFIG_DIR'] = '/etc/omneum'
    config = OmneumClientConfig.from_local_deployment()
    async with stdio_client(StdioServerParameters(command=PROXY)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            ping = await session.call_tool('ping', {})
            assert not ping.isError and ping.content
    async with open_stdio_client(config, StdioServerParameters(command=PROXY)) as client:
        first = await client.link_claim('service', ' Example ', ' Display Name ', ' Alice ')
        second = await client.link_claim('service', 'example', 'display_name', 'Alice')
        assert first.value == second.value
        observations = tuple(Observation(assertion_id=f'assertion-{n}', source=Source('web_publisher', f'https://example{n}.com'), claim=Claim('service', 'example', 'display_name', 'Alice'), observed_at=datetime(2026,1,1,tzinfo=timezone.utc), source_modified_at=None, upstream_sources=(), cited_sources=(), parent_assertion_ids=(), retrievals=()) for n in range(2))
        result = await client.evaluate_assertion(observations, estimator=DependencyEstimatorConfig(upstream_weight=.25, citation_weight=.20, assertion_lineage_weight=.20, ownership_weight=.10, temporal_weight=.10, graph_weight=.15, temporal_window_seconds=7200.))
        assert len(result.source_reliability) == 2
        print('session ready', flush=True)
        await asyncio.sleep(3)
    print('session passed', flush=True)


def instances():
    data = run('systemctl', 'list-units', '--plain', '--no-legend', 'omneum-server@*.service').stdout
    return [line.split()[0] for line in data.splitlines() if 'running' in line]


def main():
    assert sys.platform == 'linux' and os.geteuid() == 0
    run('systemctl', 'start', 'omneumd')
    install = ['sh', str(ROOT/'deploy/install-server.sh'), str(ROOT/'target/release/omneum-server'), CONFIG]
    run(*install)
    for path, group, mode in [(Path(PROXY), 'root', 0o755),
                              (Path('/run/omneum-server.sock'), 'omneum-client', 0o660),
                              (Path('/etc/omneum/config.toml'), 'root', 0o644)]:
        info = path.stat()
        assert info.st_uid == 0 and info.st_gid == grp.getgrnam(group).gr_gid
        assert info.st_mode & 0o7777 == mode
    before = Path('/etc/omneum/config.toml').read_bytes()
    run(*install)
    assert Path('/etc/omneum/config.toml').read_bytes() == before
    changed = Path('/etc/omneum/test-config.toml')
    changed.write_bytes(before+b'\n# different configuration\n'); changed.chmod(0o644)
    try:
        assert subprocess.run(install[:-1]+[str(changed)], capture_output=True).returncode != 0
        assert Path('/etc/omneum/config.toml').read_bytes() == before
    finally: changed.unlink()
    # Reject both writable runtime metadata and a writable installation parent;
    # the installer must not silently repair either one, even on a reinstall.
    for path, mode in [(ROOT/'.venv/pyvenv.cfg', 0o666), (Path(PROXY).parent, 0o777)]:
        original_mode = path.stat().st_mode & 0o777
        try:
            path.chmod(mode)
            rejected = subprocess.run(install, capture_output=True, text=True)
            assert rejected.returncode != 0
            assert f'untrusted installation path: {path}' in rejected.stderr
            assert path.stat().st_mode & 0o777 == mode
        finally: path.chmod(original_mode)
    run('systemd-sysusers', '-', input=f'u {CLIENT} - "Omneum test client" /nonexistent /usr/sbin/nologin\nm {CLIENT} omneum-client\n')
    account = pwd.getpwnam(CLIENT)
    assert grp.getgrnam('omneum-ipc').gr_gid not in os.getgrouplist(CLIENT, account.pw_gid)
    # A persistent account must not acquire the reserved evaluator principal.
    run('usermod', '-aG', 'omneum-session', CLIENT)
    try:
        rejected = subprocess.run(install, capture_output=True, text=True)
        assert rejected.returncode != 0
    finally:
        run('gpasswd', '-d', CLIENT, 'omneum-session')
    reserved = 'omneum-123456-test'
    run('useradd', '--no-create-home', '--shell', '/usr/sbin/nologin', reserved)
    try:
        rejected = subprocess.run(install, capture_output=True, text=True)
        assert rejected.returncode != 0
    finally:
        run('userdel', reserved)
    run('groupadd','--non-unique','--gid',str(grp.getgrnam('omneum-session').gr_gid),'omneum-test-alias')
    try:
        assert subprocess.run(install,capture_output=True).returncode != 0
        assert subprocess.run(['sh',str(ROOT/'deploy/install.sh'),'/usr/local/libexec/omneumd'],
                              capture_output=True).returncode != 0
    finally:
        run('groupdel','omneum-test-alias')
    run(*install)
    command = ['runuser', '-u', CLIENT, '--', str(ROOT/'.venv/bin/python'), str(Path(__file__).resolve()), 'workload']
    clients = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    for child in clients:
        assert select.select([child.stdout], [], [], 30)[0], 'session startup timed out'
        assert child.stdout.readline().strip() == 'session ready', child.stderr.read() if child.poll() is not None else 'session failed'
    units = instances()
    assert len(units) == 2, units
    pids = [run('systemctl', 'show', '--value', '-p', 'MainPID', unit).stdout.strip() for unit in units]
    assert len(set(pids)) == 2 and '0' not in pids
    for child in clients:
        stdout, stderr = child.communicate(timeout=20)
        assert child.returncode == 0 and 'session passed' in stdout, stderr
    for _ in range(100):
        if not instances(): break
        time.sleep(.05)
    assert not instances(), 'EOF left a running session'
    # The frontend-only identity cannot bypass the MCP layer to call omneumd.
    rejected = subprocess.run(['runuser', '-u', CLIENT, '--', '/usr/bin/python3', '-c',
        'import socket; s=socket.socket(socket.AF_UNIX); s.connect("/run/omneumd/eval.sock")'], capture_output=True)
    assert rejected.returncode != 0
    # Underlying pin/package ownership denies writes even outside the namespace.
    run('runuser', '-u', 'omneum-mcp', '--', '/usr/bin/python3', '-c', '''
import os
for p in ['/etc/omneum/config.toml','/opt/omneum/.venv/pyvenv.cfg']:
    try: os.open(p,os.O_WRONLY)
    except PermissionError: pass
    else: raise AssertionError(p)
''')
    override = Path('/etc/systemd/system/omneum-server@.service.d')
    assert not override.exists(), 'do not overwrite administrator overrides'
    override.mkdir()
    markers = [Path('/tmp/omneum-shared-test'), Path('/var/tmp/omneum-shared-test')]
    home = Path('/home/omneum-test')
    assert not home.exists()
    home.mkdir(mode=0o755); (home/'file').write_text('synthetic fixture')
    for marker in markers: marker.write_text('synthetic fixture')
    host_socket = socket.socket(socket.AF_UNIX); host_socket.bind('\0omneum-runtime-test'); host_socket.listen(1)
    pid = run('systemctl', 'show', '--value', '-p', 'MainPID', 'omneumd').stdout.strip()
    try:
        (override/'test.conf').write_text('[Service]\nExecStart=\nExecStart=/opt/omneum/.venv/bin/python -I -B /opt/omneum/tests/security/runtime_probe.py\nEnvironment=OMNEUM_TEST_DAEMON_PID='+pid+'\n')
        run('systemctl', 'daemon-reload')
        result = run('runuser', '-u', CLIENT, '--', PROXY, input='')
        checks = json.loads(result.stdout)
        assert all(checks.values()), checks
        print(json.dumps(checks, indent=2))
        # Opaque forwarding and half-close: return bytes only after stdin EOF.
        echo = ROOT/'tests/security/runtime_echo.py'
        echo.write_text('import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data); sys.stdout.buffer.flush()\n')
        echo.chmod(0o644)
        try:
            (override/'test.conf').write_text('[Service]\nExecStart=\nExecStart=/opt/omneum/.venv/bin/python -I -B /opt/omneum/tests/security/runtime_echo.py\n')
            run('systemctl', 'daemon-reload')
            payload = bytes(range(256))*4096
            echoed = subprocess.run(['runuser','-u',CLIENT,'--',PROXY], input=payload, capture_output=True, timeout=20)
            assert echoed.returncode == 0 and echoed.stdout == payload and not echoed.stderr
            # Server EOF must terminate the proxy even while its stdin is open.
            echo.write_text('import sys; sys.stdout.buffer.write(b"done"); sys.stdout.buffer.flush()\n')
            early = subprocess.Popen(['runuser','-u',CLIENT,'--',PROXY], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            assert early.wait(timeout=10) == 0
            assert early.stdout.read() == b'done' and not early.stderr.read()
            early.stdin.close()
        finally: echo.unlink()
    finally:
        (override/'test.conf').unlink(); override.rmdir()
        run('systemctl', 'daemon-reload')
        host_socket.close()
        for marker in markers: marker.unlink()
        (home/'file').unlink(); home.rmdir()
    run('systemctl', 'restart', 'omneumd')
    run(*command)
    print('PASS: managed sessions, EOF, separate client group, reinstall, ownership, service authority probes')


if __name__ == '__main__':
    if sys.argv[-1] == 'workload': asyncio.run(workload())
    else: main()
