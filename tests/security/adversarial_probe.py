"""Test-only malicious-code simulation, executed inside the installed service.

The administrator harness temporarily selects this program with ExecStart. This
is never a production endpoint or application import. All data is synthetic.
"""
import ctypes
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import urllib.request

LIBC = ctypes.CDLL(None, use_errno=True)
CHILDREN = []


def attempt(operation):
    try:
        value = operation()
        return {'allowed': True, 'value': value}
    except OSError as error:
        return {'allowed': False, 'errno': error.errno, 'error': type(error).__name__}
    except urllib.error.URLError as error:
        return {'allowed': False, 'error': type(error).__name__}


def read(path):
    with open(path, 'rb') as file:
        return len(file.read(256))  # Never return harvested contents.


def write_open(path, flags):
    fd = os.open(path, flags)
    try:
        os.write(fd, b'')
    finally:
        os.close(fd)


def moved(path):
    destination = str(path)+'.adversarial-moved'
    os.rename(path, destination)
    os.rename(destination, path)


def mutation_tests(path, replacement):
    return {
        'overwrite': attempt(lambda: write_open(path, os.O_WRONLY)),
        'append': attempt(lambda: write_open(path, os.O_WRONLY|os.O_APPEND)),
        'truncate': attempt(lambda: write_open(path, os.O_WRONLY|os.O_TRUNC)),
        'rename': attempt(lambda: moved(path)),
        'replace': attempt(lambda: os.replace(replacement, path)),
        'unlink': attempt(lambda: os.unlink(path)),
        'sibling': attempt(lambda: create(Path(path).parent/'.adversarial-sibling')),
    }


def create(path):
    fd = os.open(path, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
    os.write(fd, b'synthetic probe')
    os.close(fd)
    renamed = str(path)+'.renamed'
    os.rename(path, renamed)
    os.unlink(renamed)
    return 'created, modified, renamed, deleted'


def connect(path, kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_UNIX, kind) as stream:
        stream.settimeout(.5)
        stream.connect(path)


def attach(pid):
    if LIBC.ptrace(16, pid, None, None) == -1:  # PTRACE_ATTACH
        raise OSError(ctypes.get_errno(), 'ptrace denied')
    os.waitpid(pid, 0)
    assert LIBC.ptrace(17, pid, None, None) == 0  # PTRACE_DETACH


def process(pid, pidfd_signal_number=signal.SIGTERM):
    result = {name: attempt(lambda name=name: read(f'/proc/{pid}/{name}'))
              for name in ('cmdline', 'status', 'environ', 'maps', 'mem')}
    result['fds'] = attempt(lambda: os.listdir(f'/proc/{pid}/fd'))
    def memory_open():
        fd = os.open(f'/proc/{pid}/mem', os.O_RDONLY)
        os.close(fd)
    result['mem_open'] = attempt(memory_open)
    result['ptrace'] = attempt(lambda: attach(pid))
    result['signal'] = attempt(lambda: os.kill(pid, signal.SIGCONT))
    result['kill_zero'] = attempt(lambda: os.kill(pid, 0))
    if hasattr(os, 'pidfd_open'):
        def pidfd():
            fd = os.pidfd_open(pid); os.close(fd)
        result['pidfd_open'] = attempt(pidfd)
        def pidfd_signal():
            fd = os.pidfd_open(pid)
            try: signal.pidfd_send_signal(fd, pidfd_signal_number)
            finally: os.close(fd)
        result['pidfd_signal'] = attempt(pidfd_signal) if pid != os.getpid() else None
    return result


def message_queue():
    # POSIX message queues are not covered by RestrictAddressFamilies or
    # PrivateTmp. Do not confuse a successful mq_open with persistent execution.
    name = b'/omneum-adversarial-queue'
    descriptor = LIBC.mq_open(name, os.O_CREAT|os.O_EXCL|os.O_RDWR, 0o600, None)
    if descriptor == -1:
        raise OSError(ctypes.get_errno(), 'mq_open denied')
    try:
        return {'path_visible': os.path.exists('/dev/mqueue/'+name.decode()[1:]),
                'ipc_namespace': os.readlink('/proc/self/ns/ipc')}
    finally:
        LIBC.mq_close(descriptor)
        assert LIBC.mq_unlink(name) == 0


def queue_open(name):
    fd = LIBC.mq_open(name.encode(), os.O_RDWR|os.O_NONBLOCK)
    if fd == -1: raise OSError(ctypes.get_errno(), 'mq_open denied')
    LIBC.mq_close(fd)


def queue_create(name):
    mask = os.umask(0)
    try: fd = LIBC.mq_open(name.encode(), os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NONBLOCK, 0o666, None)
    finally: os.umask(mask)
    if fd == -1: raise OSError(ctypes.get_errno(), 'mq_open failed')
    assert LIBC.mq_send(fd, b'test', 4, 0) == 0
    buffer = ctypes.create_string_buffer(8192)
    assert LIBC.mq_receive(fd, buffer, len(buffer), None) == 4
    assert buffer.raw[:4] == b'test'
    return fd


def ip(family, kind, operation):
    with socket.socket(family, kind) as stream:
        stream.settimeout(.5)
        host = '::1' if family == socket.AF_INET6 else '127.0.0.1'
        if operation == 'listen':
            stream.bind((host, 0)); stream.listen(1)
        elif operation == 'connect':
            stream.connect((host, 9))
        elif operation == 'send':
            stream.sendto(b'synthetic', (host, 9))


def evaluate():
    from omneum.config import load_deployment_state
    from omneum.oprf import VOPRFClient
    state = load_deployment_state()
    client = VOPRFClient(state.voprf_server.public_key)
    blind = client.blind(b'adversarial validation')
    output = client.finalize(input_data=b'adversarial validation', client_state=blind.client_state,
                             evaluation=state.voprf_server.evaluate(blind.blinded_element))
    assert len(output) == 64
    return state.voprf_server.public_key.hex()


def attack(request):
    assert os.getuid() != 0
    out = {'pid': os.getpid(), 'uid': os.getuid(), 'groups': os.getgroups(),
           'self_status': Path('/proc/self/status').read_text(),
           'proc_visible': [name for name in os.listdir('/proc') if name.isdecimal()],
           'run_visible': os.listdir('/run'),
           'self_fds': {name: attempt(lambda name=name: os.readlink('/proc/self/fd/'+name))
                        for name in os.listdir('/proc/self/fd')}}
    out['homes'] = {path: attempt(lambda path=path: read(path)) for path in request['home_files']}
    out['directories'] = {path: attempt(lambda path=path: os.listdir(path)) for path in
                          ['/root', request['home'], request['user_run'], '/var/lib/omneumd']}
    out['config_read'] = attempt(lambda: read('/etc/omneum/config.toml'))
    out['mutations'] = {path: mutation_tests(path, request['replacement']) for path in request['protected']}
    out['key_read'] = attempt(lambda: read('/var/lib/omneumd/voprf.key'))
    out['key_mutations'] = mutation_tests('/var/lib/omneumd/voprf.key', request['replacement'])
    out['storage'] = {path: attempt(lambda path=path: create(Path(path)/'.adversarial-storage'))
                      for path in ['/tmp', '/var/tmp', '/dev/shm', '/var/lib/omneum', '/opt/omneum',
                                   '/etc/omneum', '/run/omneumd', '/run']}
    out['shared_temp_read'] = {path: attempt(lambda path=path: read(path)) for path in request['temp_files']}
    out['persistence'] = {path: {'artifact': attempt(lambda path=path: create(path)),
                                'executed_after_restart': False}
                          for path in ['/var/lib/omneum/.profile', '/var/lib/omneum/.bashrc',
                          '/var/lib/omneum/.config/adversarial', '/var/lib/omneum/.local/bin/adversarial',
                          '/var/lib/omneum/.config/systemd/user/adversarial.service',
                          request['site']+'/adversarial.pth', request['site']+'/sitecustomize.py',
                          request['site']+'/json.py', '/opt/omneum/json.py']}
    for name, command in [('user_systemd', ['systemctl', '--user', 'daemon-reload']),
                          ('cron', ['crontab', '-'])]:
        try:
            result = subprocess.run(command, input=b'# no scheduled commands\n', capture_output=True, timeout=3)
            if name == 'cron' and result.returncode == 0:
                subprocess.run(['crontab', '-r'], check=True)
            out['persistence'][name] = {'artifact': {'allowed': result.returncode == 0},
                                        'helper_present': True, 'returncode': result.returncode,
                                        'executed_after_restart': False}
        except FileNotFoundError:
            out['persistence'][name] = {'helper_present': False}
    out['processes'] = {name: process(pid) for name, pid in request['pids'].items()}
    victim = request['pids']['other_session']
    out['cross_session_signal'] = attempt(lambda: os.kill(victim, signal.SIGUSR1))
    fd_path = f'/proc/{victim}/fd/{request["victim_fd"]}'
    out['cross_session_memfd_read'] = attempt(lambda: read(fd_path))
    out['cross_session_memfd_write'] = attempt(lambda: Path(fd_path).write_bytes(b'changed synthetic data'))
    out['cross_session_frontend_fd'] = attempt(lambda: read(f'/proc/{victim}/fd/0'))
    out['queues'] = {name: {'visible': os.path.exists('/dev/mqueue/'+name[1:]),
                            'open': attempt(lambda name=name: queue_open(name))}
                     for name in request['queues']}
    out['network'] = {f'{family}/{kind}/{operation}': attempt(lambda family=family,kind=kind,operation=operation: ip(family,kind,operation))
                      for family in (socket.AF_INET, socket.AF_INET6)
                      for kind,operation in ((socket.SOCK_STREAM,'create'),(socket.SOCK_STREAM,'listen'),
                                              (socket.SOCK_STREAM,'connect'),(socket.SOCK_DGRAM,'send'))}
    out['network']['DNS'] = attempt(lambda: socket.getaddrinfo('example.com', 443))
    out['network']['HTTPS'] = attempt(lambda: urllib.request.urlopen('https://example.com', timeout=3).status)
    out['unix'] = {path: {'visible': os.path.exists(path),
                          'connect': attempt(lambda path=path,kind=kind: connect(path,kind)),
                          'privileged_operation': 'not attempted'}
                   for path,kind in request['unix']}
    out['abstract'] = attempt(lambda: connect('\0omneum-adversarial-host'))
    out['frontend_path'] = attempt(lambda: connect('/run/omneum-server.sock'))
    out['message_queue'] = attempt(message_queue)
    out['mountinfo'] = Path('/proc/self/mountinfo').read_text()
    out['daemon_public_key'] = evaluate()
    out['exec'] = {'shell': attempt(lambda: subprocess.check_output(['/bin/sh','-c','printf harmless']).decode()),
                   'binary': attempt(lambda: subprocess.run(['/usr/bin/true']).returncode)}
    finished = []
    threads = [threading.Thread(target=lambda: finished.append(1)) for _ in range(4)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    out['threads'] = len(finished)
    out['child_pid'] = None
    try:
        child = subprocess.Popen(['/usr/bin/sleep','300'], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as error:
        out['own_child'] = {'spawn_allowed': False, 'errno': error.errno}
    else:
        CHILDREN.append(child)
        out['child_pid'] = child.pid
        out['own_child'] = process(child.pid, 0)
    return out


def main():
    state = {'signals': 0}
    def received(_signal, _frame): state['signals'] += 1
    signal.signal(signal.SIGUSR1, received)
    fd = os.memfd_create('omneum-adversarial-victim', os.MFD_CLOEXEC)
    os.write(fd, b'original synthetic data')
    queue_name = f'/omneum-session-{os.getpid()}'
    queue_fd = queue_create(queue_name)
    for line in sys.stdin:
        request = json.loads(line)
        if request['mode'] == 'ready':
            result = {'pid': os.getpid(), 'fd': fd, 'uid': os.getuid(), 'gid': os.getgid(),
                      'groups': os.getgroups(), 'queue': queue_name,
                      'ipc': os.readlink('/proc/self/ns/ipc')}
        elif request['mode'] == 'status':
            result = {'signals': state['signals'], 'data': os.pread(fd, 64, 0).decode(),
                      'uid': os.getuid(), 'public_key': evaluate()}
        elif request['mode'] == 'credentials':
            connect('/run/omneumd/credentials.sock')
            result = True
        elif request['mode'] == 'terminate':
            result = attempt(lambda: os.kill(request['pid'], signal.SIGTERM))
        else:
            result = attack(request)
        print(json.dumps(result), flush=True)
    LIBC.mq_close(queue_fd)
    assert LIBC.mq_unlink(queue_name.encode()) == 0


if __name__ == '__main__':
    main()
