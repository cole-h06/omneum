"""Authenticated local VOPRF IPC. This module never opens a private-key file."""
from __future__ import annotations

import ctypes
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import socket
import struct
import sys
import time

from .oprf import (
    ELEMENT_LENGTH, PROOF_LENGTH, InvalidBlindedElementError,
    OPRFProtocolError, VOPRFEvaluation, VOPRFClient,
)

IPC_VERSION = 1
GET_PUBLIC_KEY = 1
BLIND_EVALUATE = 2
HEADER = struct.Struct("!BBH")
MAX_RESPONSE_PAYLOAD = ELEMENT_LENGTH + PROOF_LENGTH


class DaemonUnavailableError(OPRFProtocolError):
    """The authenticated daemon connection could not be established."""


class DaemonBusyError(OPRFProtocolError):
    """Daemon rate or capacity limit reached."""


class DaemonKeyMismatchError(OPRFProtocolError):
    """Daemon public key does not match the configured pin."""


def peer_uid(stream: socket.socket) -> int:
    if sys.platform == "linux":
        credentials = stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("=iII"))
        if len(credentials) != struct.calcsize("=iII"):
            raise OSError("Peer credentials unavailable.")
        _pid, uid, _gid = struct.unpack("=iII", credentials)
        return uid
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        getpeereid = libc.getpeereid
        getpeereid.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
        getpeereid.restype = ctypes.c_int
        uid, gid = ctypes.c_uint(), ctypes.c_uint()
        if getpeereid(stream.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
            raise OSError("Peer credentials unavailable.")
        return uid.value
    raise OSError("Protected serving requires Linux or macOS.")


class DaemonServerContext:
    """One pinned daemon; independent connections make evaluate thread-safe.

    Every connection authenticates the OS identity and checks the existing key
    pin. A total monotonic deadline covers connect, handshake and evaluation.
    There is no retry or in-process fallback after an uncertain request.
    """
    __slots__ = ("_socket_path", "_uid", "_public_key", "_timeout")

    def __init__(self, socket_path: str | Path, expected_uid: int,
                 public_key: bytes, timeout: float = 1.0):
        self._validate_endpoint(socket_path, expected_uid, timeout)
        VOPRFClient(public_key)  # existing public-key validation, never a server context
        self._socket_path = str(socket_path)
        self._uid = expected_uid
        self._public_key = public_key
        self._timeout = timeout
        self._exchange(None)

    @staticmethod
    def _validate_endpoint(socket_path, expected_uid, timeout):
        if not isinstance(socket_path, (str, Path)) or not Path(socket_path).is_absolute():
            raise ValueError("Daemon socket must be an absolute path.")
        if type(expected_uid) is not int or not 0 <= expected_uid < 2**32 - 1:
            raise ValueError("Daemon UID is invalid.")
        if not 0 < timeout <= 60:
            raise ValueError("Daemon deadline is invalid.")

    @classmethod
    def fetch_public_key(cls, socket_path: str | Path, expected_uid: int,
                         timeout: float = 1.0) -> bytes:
        """Read the initial public key from the authenticated daemon for init."""
        cls._validate_endpoint(socket_path, expected_uid, timeout)
        with cls._connection(socket_path, expected_uid, timeout) as (stream, deadline):
            public_key = cls._request(stream, GET_PUBLIC_KEY, b"", ELEMENT_LENGTH, deadline)
        VOPRFClient(public_key)
        return public_key

    @property
    def public_key(self) -> bytes:
        return self._public_key

    def evaluate(self, blinded_element: bytes) -> VOPRFEvaluation:
        if type(blinded_element) is not bytes:
            raise TypeError("blinded_element must be bytes.")
        if len(blinded_element) != ELEMENT_LENGTH:
            raise ValueError(f"blinded_element must be {ELEMENT_LENGTH} bytes.")
        payload = self._exchange(blinded_element)
        return VOPRFEvaluation(payload[:ELEMENT_LENGTH], payload[ELEMENT_LENGTH:])

    def _exchange(self, blinded_element: bytes | None) -> bytes:
        with self._connection(self._socket_path, self._uid, self._timeout) as (stream, deadline):
            actual = self._request(stream, GET_PUBLIC_KEY, b"", ELEMENT_LENGTH, deadline)
            if not secrets.compare_digest(actual, self._public_key):
                raise DaemonKeyMismatchError("Configured VOPRF keys do not match.")
            if blinded_element is None:
                return actual
            return self._request(stream, BLIND_EVALUATE, blinded_element,
                                 MAX_RESPONSE_PAYLOAD, deadline)

    @staticmethod
    @contextmanager
    def _connection(socket_path, expected_uid, timeout):
        deadline = time.monotonic() + timeout
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                stream.settimeout(DaemonServerContext._remaining(deadline))
                stream.connect(str(socket_path))
                if peer_uid(stream) != expected_uid:
                    raise DaemonUnavailableError("Daemon identity verification failed.")
                yield stream, deadline
        except TimeoutError:
            raise TimeoutError("VOPRF daemon deadline exceeded.") from None
        except OPRFProtocolError:
            raise
        except (OSError, AttributeError, struct.error):
            raise DaemonUnavailableError("VOPRF daemon unavailable.") from None

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        return remaining

    @classmethod
    def _read(cls, stream: socket.socket, size: int, deadline: float) -> bytes:
        result = bytearray()
        while len(result) < size:
            stream.settimeout(cls._remaining(deadline))
            chunk = stream.recv(size - len(result))
            if not chunk:
                raise OSError("Truncated daemon response.")
            result.extend(chunk)
        return bytes(result)

    @classmethod
    def _request(cls, stream, opcode, payload, expected_size, deadline):
        stream.settimeout(cls._remaining(deadline))
        stream.sendall(HEADER.pack(IPC_VERSION, opcode, len(payload)) + payload)
        version, status, size = HEADER.unpack(cls._read(stream, HEADER.size, deadline))
        if version != IPC_VERSION or status not in range(5) or size != (expected_size if status == 0 else 0):
            raise OPRFProtocolError("Malformed daemon response.")
        if status == 2:
            raise InvalidBlindedElementError("Malformed RFC 9497 VOPRF blinded element.")
        if status == 3:
            raise DaemonBusyError("VOPRF evaluation capacity is exhausted.")
        if status:
            raise OPRFProtocolError("VOPRF daemon evaluation failed.")
        return cls._read(stream, size, deadline)

    def close(self) -> None:
        # Connections are scoped to each operation, including every error path.
        pass


def get_daemon_socket() -> Path:
    default = ("/run/omneumd/eval.sock" if sys.platform == "linux" else
               "/Library/Application Support/OmneumIPC/eval.sock")
    return Path(os.environ.get("OMNEUM_DAEMON_SOCKET", default))


def get_daemon_uid() -> int:
    value = os.environ.get("OMNEUM_DAEMON_UID")
    if value is not None:
        if not value.isascii() or not value.isdecimal() or str(int(value)) != value:
            raise ValueError("Daemon UID is invalid.")
        return int(value)
    try:
        import pwd
        return pwd.getpwnam("omneum-crypto").pw_uid
    except (ImportError, KeyError):
        raise ValueError("The omneum-crypto service identity is not configured.") from None
