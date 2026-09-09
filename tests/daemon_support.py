"""Same-UID functional fixtures ONLY. Not shipped in the wheel; no isolation claim."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import weakref

from omneum.daemon import DaemonServerContext
from omneum.oprf import OPRFProtocolError

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get("OMNEUM_TEST_DAEMON", ROOT / "target/test-daemon/debug/omneumd"))


_built = False

def build_daemon():
    global _built
    if not _built and "OMNEUM_TEST_DAEMON" not in os.environ:
        subprocess.run(["cargo", "build", "--locked", "--no-default-features", "--features", "test-daemon",
                        "--bin", "omneumd", "--target-dir", str(ROOT / "target/test-daemon")],
                       cwd=ROOT, check=True, capture_output=True)
    _built = True


def _cleanup(process, directory):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    directory.cleanup()


class FixtureDaemon:
    def __init__(self, key: bytes, *, options=(), public_key=None):
        build_daemon()
        # Realpath is essential on macOS, where /tmp itself is a symlink.
        self.directory = tempfile.TemporaryDirectory(prefix="od-", dir=str(Path(tempfile.gettempdir()).resolve()))
        self.root = Path(self.directory.name)
        self.key_dir = self.root / "keys"
        self.key_dir.mkdir(mode=0o700)
        self.key_file = self.key_dir / "voprf.key"
        self.key_file.write_bytes(key)
        self.key_file.chmod(0o600)
        self.socket = self.root / "eval.sock"
        self.command = [str(BINARY), "serve", "--test-mode", "--key-dir", str(self.key_dir),
                        "--socket", str(self.socket), "--client-uid", str(os.getuid()),
                        "--rate", "100000", "--burst", "100000", *options]
        self.process = subprocess.Popen(self.command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._cleanup = weakref.finalize(self, _cleanup, self.process, self.directory)
        for _ in range(300):
            if self.process.poll() is not None:
                self.close()
                raise OPRFProtocolError("VOPRF fixture daemon initialization failed.")
            if self.socket.exists():
                break
            time.sleep(.01)
        else:
            self.close()
            raise OPRFProtocolError("VOPRF fixture daemon startup timed out.")
        if public_key is None:
            # Fixture discovery only. Production always receives an administrator pin.
            import socket, struct
            from omneum.daemon import peer_uid
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as stream:
                stream.settimeout(2);stream.connect(str(self.socket))
                assert peer_uid(stream)==os.getuid()
                stream.sendall(b"\x01\x01\0\0")
                deadline=time.monotonic()+2
                header=DaemonServerContext._read(stream,4,deadline)
                assert header==b"\x01\0\0\x20",header
                public_key=DaemonServerContext._read(stream,32,deadline)
        self.public_key=public_key
        self.context=DaemonServerContext(self.socket,os.getuid(),public_key)

    def close(self):
        self._cleanup()


class VOPRFServer:
    """Compatibility fixture for old raw-key tests; server operations are IPC."""
    def __init__(self, path, backend=None):
        from omneum.oprf import VOPRFServer as ValidatedServer
        if backend is not None:
            self._server=ValidatedServer.__new__(ValidatedServer)
            self._server._context=backend.load_server(path)
            self._server._public_key=self._server._context.public_key
            from omneum.oprf import _require_protocol_length, ELEMENT_LENGTH
            _require_protocol_length(self._server._public_key,name="server_public_key",length=ELEMENT_LENGTH)
        else:
            if not isinstance(path,(str,Path)):
                raise TypeError("Fixture key must be a path.")
            self.daemon=FixtureDaemon(Path(path).read_bytes())
            # Construct only the public validation adapter without invoking the old loader.
            self._server=ValidatedServer.__new__(ValidatedServer)
            self._server._context=self.daemon.context
            self._server._public_key=self.daemon.public_key

    @property
    def public_key(self):return self._server.public_key
    def evaluate(self,element):return self._server.evaluate(element)
