"""Compromised-Python probes, invoked only by linux_runtime.py's admin override."""
import ctypes
import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import urllib.request

from omneum.config import load_deployment_state
from omneum.oprf import VOPRFClient


def denied(operation):
    try:
        result = operation()
        if isinstance(result, int):
            os.close(result)
    except OSError as error:
        assert error.errno in (errno.EACCES, errno.EPERM, errno.EROFS, errno.ENOENT,
                               errno.EAFNOSUPPORT, errno.ECONNREFUSED), error
        return True
    raise AssertionError('operation permitted')


def main():
    assert os.getuid() != 0
    results = {}
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    assert status['NoNewPrivs'].strip() == '1'
    assert status['Seccomp'].strip() == '2'
    assert int(status['CapEff'].strip(), 16) == 0
    results['unrelated proc hidden'] = denied(lambda: os.open('/proc/1/environ', os.O_RDONLY))
    for path in ('/var/lib/omneumd/voprf.key', '/root/omneum-test', '/home/omneum-test/file',
                 '/tmp/omneum-shared-test', '/var/tmp/omneum-shared-test'):
        results['read '+path] = denied(lambda: os.open(path, os.O_RDONLY))
    for path in ('/opt/omneum/.venv/pyvenv.cfg', '/opt/omneum/.venv/bin/python',
                 '/etc/omneum/config.toml', '/etc/omneumd/peer.conf',
                 '/usr/local/libexec/omneumd', '/usr/local/bin/omneum-server'):
        results['write '+str(path)] = denied(lambda: os.open(path, os.O_WRONLY))
    import omneum, omneum_oprf
    native = list(Path(omneum_oprf.__file__).parent.glob('*.so'))
    assert native, 'native extension must be installed'
    for path in (omneum.__file__, omneum_oprf.__file__, *native):
        results['write '+str(path)] = denied(lambda: os.open(path, os.O_WRONLY))
    for directory in ('/tmp', '/var/tmp', '/dev/shm', '/var/lib/omneum', '/run',
                      '/opt/omneum/.venv/lib', '/etc/cron.d'):
        results['create '+directory] = denied(lambda: os.open(directory+'/omneum-test', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600))
    for family in (socket.AF_INET, socket.AF_INET6):
        results['socket '+str(family)] = denied(lambda: socket.socket(family))
    try:
        urllib.request.urlopen('https://example.com', timeout=2)
    except (OSError, urllib.error.URLError):
        results['HTTPS denied'] = True
    else:
        raise AssertionError('IP egress permitted')
    for path in ('/run/dbus/system_bus_socket', '/run/systemd/private', '/run/snapd.socket',
                 '/run/systemd/journal/stdout', '/run/systemd/resolve/io.systemd.Resolve',
                 '\0omneum-runtime-test'):
        with socket.socket(socket.AF_UNIX) as stream:
            stream.settimeout(1)
            try:
                results['connect '+repr(path)] = denied(lambda: stream.connect(path))
            except AssertionError as error:
                raise AssertionError('socket reachable: '+repr(path)) from error
    pid = int(os.environ['OMNEUM_TEST_DAEMON_PID'])
    results['daemon memory'] = denied(lambda: os.open(f'/proc/{pid}/mem', os.O_RDONLY))
    libc = ctypes.CDLL(None, use_errno=True)
    assert libc.ptrace(16, pid, None, None) == -1 and ctypes.get_errno() in (errno.EPERM, errno.ESRCH)
    results['daemon ptrace'] = True
    # A private network namespace also hides abstract host Unix sockets.
    left, right = socket.socketpair()
    with left, right:
        left.sendall(b'x')
        assert right.recv(1) == b'x'
    state = load_deployment_state()
    client = VOPRFClient(state.voprf_server.public_key)
    blind = client.blind(b'managed runtime')
    evaluation = state.voprf_server.evaluate(blind.blinded_element)
    assert len(client.finalize(input_data=b'managed runtime', client_state=blind.client_state, evaluation=evaluation)) == 64
    results['daemon evaluate'] = True
    completed = []
    threads = [threading.Thread(target=lambda: completed.append(True)) for _ in range(4)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert len(completed) == 4
    results['threads'] = True
    # Deliberately retained authority: descendants inherit the same boundary.
    assert subprocess.check_output(['/bin/sh', '-c', 'printf child']) == b'child'
    results['subprocess remains available'] = True
    if Path('/usr/bin/crontab').exists():
        cron = subprocess.run(['/usr/bin/crontab', '-'], input=b'# no jobs\n', capture_output=True, timeout=3)
        if cron.returncode == 0:
            subprocess.run(['/usr/bin/crontab', '-r'], check=True)
        assert cron.returncode != 0, 'cron persistence permitted'
        results['cron denied'] = True
    results['startup write denied'] = denied(lambda: os.open('/var/lib/omneum/.profile', os.O_WRONLY|os.O_CREAT, 0o600))
    print(json.dumps(results))


if __name__ == '__main__':
    main()
