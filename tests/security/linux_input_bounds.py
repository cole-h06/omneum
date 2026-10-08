"""Exercise production socket activation both through and around the proxy.

Run as a frontend-only identity after installing the managed Linux runtime.
No unit overrides or alternative transport implementations are used.
"""
import json
import os
import select
import socket
import subprocess
import time


LIMIT = 2 * 1024 * 1024
PING = b'{"jsonrpc":"2.0","id":2,"method":"ping"}'


class Session:
    def __init__(self, proxy):
        self.process = self.socket = None
        self.pending = b''
        if proxy:
            self.process = subprocess.Popen(['/usr/local/bin/omneum-server'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0)
            self.reader = self.process.stdout.fileno()
            self.writer = self.process.stdin.fileno()
        else:
            self.socket = socket.socket(socket.AF_UNIX)
            self.socket.settimeout(10)
            self.socket.connect('/run/omneum-server.sock')
            self.reader = self.writer = self.socket.fileno()

    def send(self, data):
        deadline = time.monotonic() + 10
        while data:
            assert select.select([], [self.writer], [], max(0, deadline-time.monotonic()))[1], 'write timeout'
            count = os.write(self.writer, data[:16384])
            data = data[count:]

    def receive(self):
        assert select.select([self.reader], [], [], 10)[0], 'read timeout'
        return os.read(self.reader, 16384)

    def response(self, identifier):
        while True:
            while b'\n' not in self.pending:
                chunk = self.receive()
                assert chunk, 'unexpected EOF'
                self.pending += chunk
            line, self.pending = self.pending.split(b'\n', 1)
            message = json.loads(line)
            if message.get('id') == identifier:
                assert 'result' in message, message
                return

    def initialize(self):
        self.send(b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"bounds-test","version":"1"}}}\n')
        self.response(1)
        self.send(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')

    def eof(self):
        if self.process:
            self.process.stdin.close()
        else:
            self.socket.shutdown(socket.SHUT_WR)

    def close(self):
        if self.socket:
            self.socket.close()
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
            self.process.wait(timeout=10)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                stream.close()


def main():
    for proxy in (True, False):
        for size in (len(PING), LIMIT):
            session = Session(proxy)
            try:
                session.initialize()
                session.send(PING + b' ' * (size-len(PING)) + b'\n')
                session.response(2)
                session.eof()
                assert not session.receive(), 'EOF did not end session'
            finally:
                session.close()
        for suffix in (b'', b'\n' + PING + b'\n'):
            session = Session(proxy)
            try:
                session.initialize()
                try:
                    session.send(PING + b' ' * (LIMIT+1-len(PING)) + suffix)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                # Keep input open: even a stream without LF must be closed by
                # the server. Neither the prefix nor a following ping may run.
                assert not session.pending
                try:
                    assert not session.receive(), 'oversized input produced a response'
                except ConnectionResetError:
                    pass
            finally:
                session.close()
    print('PASS: proxy and direct frontend socket enforce exact byte boundary, terminal overflow, no-newline and EOF')


if __name__ == '__main__':
    main()
