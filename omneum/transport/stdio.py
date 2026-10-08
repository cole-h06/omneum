"""Bound incoming stdio messages before text decoding or MCP parsing."""
import sys

import anyio


# Explicit Omneum wire constraint, excluding LF (CR counts). Maximum-cardinality
# compact SDK request measured at 1,773,908 bytes; see tests/maximum_request.py.
MAX_FRAME_BYTES = 2 * 1024 * 1024
READ_SIZE = 16 * 1024


class FrameTooLarge(ValueError):
    """Fatal transport error; no part of the rejected frame may be parsed."""


class BoundedStdin:
    def __init__(self, stream=None):
        self._stream = sys.stdin.buffer if stream is None else stream
        self._pending = b''
        self._failed = False

    def __aiter__(self):
        return self

    def _readline(self):
        if self._failed:
            raise FrameTooLarge('MCP input exceeds the frame limit.')
        frame = bytearray()
        while True:
            chunk = self._pending
            self._pending = b''
            if not chunk:
                # read1 performs at most one underlying read, unlike read(n)
                # which can wait for n bytes on a live pipe/session socket.
                chunk = self._stream.read1(min(READ_SIZE, MAX_FRAME_BYTES - len(frame) + 1))
            if not chunk:
                if not frame:
                    raise EOFError
                return bytes(frame).decode('utf-8', errors='replace')
            newline = chunk.find(b'\n')
            part = chunk if newline < 0 else chunk[:newline]
            if len(frame) + len(part) > MAX_FRAME_BYTES:
                self._failed = True
                raise FrameTooLarge('MCP input exceeds the frame limit.')
            frame.extend(part)
            if newline >= 0:
                self._pending = chunk[newline + 1:]
                return bytes(frame).decode('utf-8', errors='replace') + '\n'

    async def __anext__(self):
        try:
            return await anyio.to_thread.run_sync(self._readline, abandon_on_cancel=True)
        except EOFError:
            raise StopAsyncIteration from None
