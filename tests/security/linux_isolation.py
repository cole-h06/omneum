"""Run as root ONLY in a disposable Linux host/VM, against a production binary.

No user accounts are created. Children drop supplementary groups and use three
numeric identities. Root is the test orchestrator, never the serving identity.
"""
import ctypes
import errno
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time

CRYPTO, MCP, OTHER = 61001, 61002, 61003


def force_openat_fallback():
    # Linux UAPI: openat2 is syscall437 on both supported test architectures.
    # Return ENOSYS solely for that syscall to exercise the production fallback.
    import platform
    assert platform.machine() in ('aarch64', 'x86_64')
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                    ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ushort), ('filters', ctypes.POINTER(Filter))]
    # Also force close_range's descriptor-directory fallback (syscall 436).
    filters = (Filter * 5)(Filter(0x20, 0, 0, 0), Filter(0x15, 2, 0, 437),
                          Filter(0x15, 1, 0, 436), Filter(0x06, 0, 0, 0x7fff0000),
                          Filter(0x06, 0, 0, 0x50000 | errno.ENOSYS))
    program = Program(5, filters)
    libc = ctypes.CDLL(None, use_errno=True)
    assert libc.prctl(38, 1, 0, 0, 0) == 0  # PR_SET_NO_NEW_PRIVS
    assert libc.prctl(22, 2, ctypes.byref(program), 0, 0) == 0  # SECCOMP_MODE_FILTER


def identity(uid, gid=None, fallback=False):
    def drop():
        os.setgroups([])
        os.setgid(uid if gid is None else gid)
        os.setuid(uid)
        if fallback:
            force_openat_fallback()
    return drop


def denied(action):
    try:
        action()
    except OSError as exc:
        assert exc.errno in (errno.EACCES, errno.EPERM), exc
    else:
        raise AssertionError('access unexpectedly permitted')


def child(uid, fn):
    pid = os.fork()
    if pid == 0:
        try:
            identity(uid)()
            fn()
        except BaseException:
            import traceback
            traceback.print_exc()
            os._exit(1)
        os._exit(0)
    assert os.waitpid(pid, 0)[1] == 0, f'UID {uid} checks failed'


def public_key(path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(2)
        stream.connect(str(path))
        pid, uid, gid = struct.unpack('=iII', stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        assert uid == CRYPTO
        stream.sendall(b'\x01\x01\0\0')
        data = b''
        while len(data) < 36:
            part = stream.recv(36-len(data))
            assert part
            data += part
        assert data[:4] == b'\x01\0\0\x20'
        return data[4:]


def main(binary):
    assert sys.platform == 'linux' and os.geteuid() == 0, 'requires disposable Linux root runner'
    # /run is noexec on supported systemd hosts; the fixture includes a binary.
    root = Path(tempfile.mkdtemp(prefix='omneum-security-', dir='/var/lib'))
    root.chmod(0o755)
    daemon = None
    try:
        installed = root/'omneumd'
        shutil.copyfile(binary, installed)
        installed.chmod(0o755)  # root owned, executable but never writable by MCP
        config = root/'omneumd.service'
        shutil.copyfile(Path(__file__).resolve().parents[2]/'deploy/systemd/omneumd.service', config)
        config.chmod(0o644)
        private = root/'private'
        private.mkdir(mode=0o700)
        os.chown(private, CRYPTO, CRYPTO)
        ipc = root/'ipc'
        ipc.mkdir(mode=0o750)
        os.chown(ipc, CRYPTO, MCP)
        key = private/'voprf.key'
        provision = subprocess.run([str(installed), 'provision', '--key-dir', str(private)],
            preexec_fn=identity(CRYPTO, MCP), capture_output=True, check=True)
        expected = bytes.fromhex(provision.stdout.decode().strip())
        assert len(expected) == 32
        sock = ipc/'eval.sock'
        command = [str(installed), 'serve', '--key-dir', str(private), '--socket', str(sock),
                   '--client-uid', str(MCP)]
        def start(fallback=False):
            import fcntl
            import resource
            read, write = os.pipe()
            high = fcntl.fcntl(write, fcntl.F_DUPFD, 200)
            os.set_inheritable(high, True)
            os.close(write)
            def launch():
                resource.setrlimit(resource.RLIMIT_NOFILE, (64, 256))
                identity(CRYPTO, MCP, fallback)()
            process = subprocess.Popen(command, preexec_fn=launch, pass_fds=(high,),
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            os.close(high)
            for _ in range(500):
                assert process.poll() is None, process.stderr.read()
                if sock.exists():
                    os.set_blocking(read, False)
                    try:
                        assert os.read(read, 1) == b'', 'high inherited descriptor remained open'
                    finally:
                        os.close(read)
                    return process
                time.sleep(.01)
            process.kill(); process.wait()
            raise AssertionError('startup timeout')
        rejected = subprocess.run(command + ['--test-mode'],
            preexec_fn=identity(CRYPTO, MCP), capture_output=True, timeout=5)
        assert rejected.returncode != 0, 'never install a test-feature daemon'
        daemon = start()
        assert sock.stat().st_mode & 0o777 == 0o660
        def mcp_checks():
            denied(lambda: os.open(key, os.O_RDONLY))
            denied(lambda: os.listdir(private))
            denied(lambda: os.open(installed, os.O_WRONLY))
            denied(lambda: os.open(config, os.O_WRONLY))
            denied(lambda: os.open(f'/proc/{daemon.pid}/mem', os.O_RDONLY))
            libc = ctypes.CDLL(None, use_errno=True)
            assert libc.ptrace(16, daemon.pid, None, None) == -1  # PTRACE_ATTACH
            assert ctypes.get_errno() in (errno.EPERM, errno.EACCES)
            assert public_key(sock) == expected
            # The public key itself is a valid serialized group element. Check
            # that the authorized identity can also access BlindEvaluate.
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.settimeout(2); stream.connect(str(sock))
                stream.sendall(b'\x01\x02\0\x20' + expected)
                result = b''
                while len(result) < 100:
                    part = stream.recv(100-len(result))
                    assert part
                    result += part
                assert result[:4] == b'\x01\0\0\x60'
        child(MCP, mcp_checks)
        # Filesystem permission deliberately weakened: kernel UID authentication
        # must still reject the unrelated UID before processing its request.
        ipc.chmod(0o755); sock.chmod(0o666)
        def other_checks():
            denied(lambda: os.open(key, os.O_RDONLY))
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.settimeout(2); stream.connect(str(sock))
                try:
                    stream.sendall(b'\x01\x01\0\0')
                    assert stream.recv(36) == b''
                except (ConnectionResetError, BrokenPipeError):
                    pass
        child(OTHER, other_checks)
        ipc.chmod(0o750); sock.chmod(0o660)
        daemon.terminate(); assert daemon.wait(timeout=3) == 0
        assert not sock.exists()
        # Descriptor validation must independently reject wrong owner/mode.
        for owner, mode in [(MCP, 0o600), (CRYPTO, 0o640)]:
            os.chown(key, owner, CRYPTO); key.chmod(mode)
            result = subprocess.run(command, preexec_fn=identity(CRYPTO, MCP), capture_output=True, timeout=5)
            assert result.returncode != 0
            assert result.stderr == b'omneumd: startup or service failure\n'
        os.chown(key, CRYPTO, CRYPTO); key.chmod(0o600)
        daemon = start()
        child(MCP, mcp_checks)
        daemon.terminate(); assert daemon.wait(timeout=3) == 0
        daemon = start(fallback=True)
        child(MCP, mcp_checks)
        daemon.terminate(); assert daemon.wait(timeout=3) == 0
        original = root/'original'
        private.rename(original)
        private.symlink_to(original, target_is_directory=True)
        result = subprocess.run(command, preexec_fn=identity(CRYPTO, MCP, True),
                                capture_output=True, timeout=5)
        assert result.returncode != 0, 'fallback followed a symlinked parent'
        private.unlink(); original.rename(private)
        original_key = private/'original.key'
        key.rename(original_key); key.symlink_to(original_key)
        result = subprocess.run(command, preexec_fn=identity(CRYPTO, MCP, True),
                                capture_output=True, timeout=5)
        assert result.returncode != 0, 'fallback followed a key symlink'
        print('PASS: ENOSYS fallback valid traversal and parent/key symlink rejection')
        print('PASS: high inherited descriptors closed with reduced limits, including close_range ENOSYS fallback')
        print('PASS: distinct-UID key/traversal/binary/config/memory/ptrace denial, authenticated IPC, unrelated UID rejection, key owner/mode, restart, shutdown')
    finally:
        if daemon is not None and daemon.poll() is None:
            daemon.terminate(); daemon.wait(timeout=3)
        shutil.rmtree(root)


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
