from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


CIPHERSUITE = "ristretto255-SHA512"
OUTPUT_LENGTH = 64


class OPRFError(Exception):
    """Base exception for Verity OPRF failures."""


class OPRFBackendUnavailableError(OPRFError):
    """Raised when the native RFC 9497 backend is unavailable."""


class OPRFProtocolError(OPRFError):
    """Raised when an OPRF message is invalid or evaluation fails."""


@dataclass(frozen=True, slots=True)
class BlindResult:
    """
    Output of the client blinding operation.

    `blinded_element` is safe to send to the deployment.
    `client_state` is private and MUST remain on the client until
    finalization.
    """

    blinded_element: bytes
    client_state: bytes


@runtime_checkable
class OPRFBackend(Protocol):
    """
    Internal backend contract for RFC 9497 base-mode OPRF using
    ristretto255-SHA512.
    """

    def blind(
        self,
        input_data: bytes,
    ) -> BlindResult:
        ...

    def evaluate(
        self,
        server_key: bytes,
        blinded_element: bytes,
    ) -> bytes:
        ...

    def finalize(
        self,
        input_data: bytes,
        client_state: bytes,
        evaluated_element: bytes,
    ) -> bytes:
        ...


class NativeOPRFBackend:
    """
    Adapter around Verity's native RFC 9497 implementation.

    The native module should wrap an RFC 9497-compatible implementation
    (e.g. the Rust `voprf` crate). Cryptographic operations should not be
    reimplemented in ordinary Python.
    """

    def __init__(self) -> None:
        try:
            import verity_oprf
        except ImportError as exc:
            raise OPRFBackendUnavailableError(
                "The Verity RFC 9497 native backend is not installed."
            ) from exc

        self._native = verity_oprf

    def blind(
        self,
        input_data: bytes,
    ) -> BlindResult:
        _require_nonempty_bytes(
            input_data,
            name="input_data",
        )

        try:
            blinded_element, client_state = self._native.blind(
                input_data
            )
        except Exception as exc:
            raise OPRFProtocolError(
                "RFC 9497 client blinding failed."
            ) from exc

        return BlindResult(
            blinded_element=_require_bytes(
                blinded_element,
                name="blinded_element",
            ),
            client_state=_require_bytes(
                client_state,
                name="client_state",
            ),
        )

    def evaluate(
        self,
        server_key: bytes,
        blinded_element: bytes,
    ) -> bytes:
        _require_nonempty_bytes(
            server_key,
            name="server_key",
        )
        _require_nonempty_bytes(
            blinded_element,
            name="blinded_element",
        )

        try:
            evaluated_element = self._native.evaluate(
                server_key,
                blinded_element,
            )
        except Exception as exc:
            raise OPRFProtocolError(
                "RFC 9497 server evaluation failed."
            ) from exc

        return _require_bytes(
            evaluated_element,
            name="evaluated_element",
        )

    def finalize(
        self,
        input_data: bytes,
        client_state: bytes,
        evaluated_element: bytes,
    ) -> bytes:
        _require_nonempty_bytes(
            input_data,
            name="input_data",
        )
        _require_nonempty_bytes(
            client_state,
            name="client_state",
        )
        _require_nonempty_bytes(
            evaluated_element,
            name="evaluated_element",
        )

        try:
            output = self._native.finalize(
                input_data,
                client_state,
                evaluated_element,
            )
        except Exception as exc:
            raise OPRFProtocolError(
                "RFC 9497 client finalization failed."
            ) from exc

        output = _require_bytes(
            output,
            name="output",
        )

        if len(output) != OUTPUT_LENGTH:
            raise OPRFProtocolError(
                "RFC 9497 ristretto255-SHA512 output must be "
                f"{OUTPUT_LENGTH} bytes; received {len(output)}."
            )

        return output


class OPRFClient:
    """
    Client-side RFC 9497 base-mode OPRF operations.
    """

    def __init__(
        self,
        backend: OPRFBackend | None = None,
    ) -> None:
        self._backend = backend or NativeOPRFBackend()

    def blind(
        self,
        input_data: bytes,
    ) -> BlindResult:
        return self._backend.blind(input_data)

    def finalize(
        self,
        *,
        input_data: bytes,
        client_state: bytes,
        evaluated_element: bytes,
    ) -> bytes:
        return self._backend.finalize(
            input_data,
            client_state,
            evaluated_element,
        )


class OPRFServer:
    """
    Deployment-side RFC 9497 base-mode OPRF evaluator.
    """

    def __init__(
        self,
        server_key: bytes,
        backend: OPRFBackend | None = None,
    ) -> None:
        self._server_key = _require_nonempty_bytes(
            server_key,
            name="server_key",
        )
        self._backend = backend or NativeOPRFBackend()

    def evaluate(
        self,
        blinded_element: bytes,
    ) -> bytes:
        return self._backend.evaluate(
            self._server_key,
            blinded_element,
        )


def _require_bytes(
    value: object,
    *,
    name: str,
) -> bytes:
    if not isinstance(value, bytes):
        raise TypeError(
            f"{name} must be bytes, received "
            f"{type(value).__name__}."
        )

    return value


def _require_nonempty_bytes(
    value: object,
    *,
    name: str,
) -> bytes:
    value = _require_bytes(
        value,
        name=name,
    )

    if not value:
        raise ValueError(
            f"{name} must not be empty."
        )

    return value