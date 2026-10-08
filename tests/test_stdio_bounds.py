import asyncio
import io
import json
import os
import subprocess
import sys

import pytest

from omneum.transport.stdio import BoundedStdin, FrameTooLarge, MAX_FRAME_BYTES, READ_SIZE
from maximum_request import maximum_wire


def collect(data):
    async def run():
        return [line async for line in BoundedStdin(io.BytesIO(data))]
    return asyncio.run(run())


def test_valid_frames_and_eof():
    assert collect(b'') == []
    assert collect(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\r\n{}') == [
        '{"jsonrpc":"2.0","id":1,"method":"ping"}\r\n', '{}',
    ]
    assert collect('"\u00e9"\n'.encode()) == ['"\u00e9"\n']


@pytest.mark.parametrize('ending', [b'', b'\n'])
def test_exact_boundary(ending):
    line = b' ' * (MAX_FRAME_BYTES - 2) + b'{}'
    result = collect(line + ending)
    assert len(result) == 1 and result[0].encode() == line + ending
    assert json.loads(result[0]) == {}


@pytest.mark.parametrize('ending', [b'', b'\n', b'\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n'])
def test_overflow_is_terminal(ending):
    # Valid-looking prefix must never reach the parser, even at later EOF/LF.
    reader = BoundedStdin(io.BytesIO(b'{}' + b' ' * (MAX_FRAME_BYTES - 1) + ending))
    with pytest.raises(FrameTooLarge):
        reader._readline()
    with pytest.raises(FrameTooLarge):
        reader._readline()


def test_infinite_no_newline_reads_only_limit_plus_one():
    class Infinite:
        total = 0
        def read1(self, size):
            assert 0 < size <= READ_SIZE
            self.total += size
            return b'x' * size
    source = Infinite()
    with pytest.raises(FrameTooLarge):
        BoundedStdin(source)._readline()
    assert source.total == MAX_FRAME_BYTES + 1


def test_byte_limit_precedes_decode():
    with pytest.raises(FrameTooLarge):
        collect(b'\xff' * (MAX_FRAME_BYTES + 1) + b'\n')
    assert collect(b'\xff\n') == ['\ufffd\n']


def test_maximum_sdk_request():
    wire = asyncio.run(maximum_wire())
    assert len(wire) - 1 < MAX_FRAME_BYTES
    assert (MAX_FRAME_BYTES - (len(wire) - 1)) / MAX_FRAME_BYTES > .10
    assert collect(wire)[0].encode() == wire


def test_foreground_overflow_ends_session_before_tool_dispatch(example_daemon):
    # Actual server entry point, including the real MCP parser. No valid prefix
    # or following ping may produce a JSON-RPC response.
    payload = b'{"jsonrpc":"2.0","id":9,"method":"ping"}'
    payload += b' ' * (MAX_FRAME_BYTES + 1 - len(payload))
    result = subprocess.run(
        [sys.executable, '-B', '-m', 'omneum.server'],
        input=payload + b'\n{"jsonrpc":"2.0","id":10,"method":"ping"}\n',
        capture_output=True, timeout=15, env=os.environ.copy(),
    )
    assert result.returncode != 0
    assert result.stdout == b''
    assert b'MCP input exceeds the frame limit.' in result.stderr


def test_foreground_no_newline_overflow_does_not_wait_for_eof(example_daemon):
    child = subprocess.Popen([sys.executable, '-B', '-m', 'omneum.server'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        child.stdin.write(b'x' * (MAX_FRAME_BYTES + 1))
        child.stdin.flush()
        assert child.wait(timeout=15) != 0
        assert child.stdout.read() == b''
        assert b'MCP input exceeds the frame limit.' in child.stderr.read()
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()
