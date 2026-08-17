from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


CIPHERSUITE = "ristretto255-SHA512"
ELEMENT_LENGTH = 32
CLIENT_STATE_LENGTH = 64
PROOF_LENGTH = 64
MAX_INPUT_LENGTH = 65_534
OUTPUT_LENGTH = 64


class OPRFError(Exception):
    """Base exception for Omneum OPRF failures."""


class OPRFBackendUnavailableError(OPRFError):
    """Raised when the native RFC 9497 backend is unavailable."""


class OPRFProtocolError(OPRFError):
    """Raised when an OPRF message is invalid or evaluation fails."""


class InvalidBlindedElementError(OPRFProtocolError):
    """Raised when a blinded element is not a valid protocol element."""


@dataclass(frozen=True, slots=True)
class VOPRFBlindResult:
    blinded_element: bytes
    client_state: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class VOPRFEvaluation:
    evaluated_element: bytes
    proof: bytes


@runtime_checkable
class VOPRFServerContext(Protocol):
    @property
    def public_key(self) -> bytes:
        ...

    def evaluate(
        self,
        blinded_element: bytes,
    ) -> VOPRFEvaluation:
        ...


@runtime_checkable
class VOPRFBackend(Protocol):
    def blind(
        self,
        input_data: bytes,
    ) -> VOPRFBlindResult:
        ...

    def load_server(
        self,
        private_key_file: str,
    ) -> VOPRFServerContext:
        ...

    def validate_public_key(
        self,
        server_public_key: bytes,
    ) -> None:
        ...

    def finalize(
        self,
        input_data: bytes,
        client_state: bytes,
        evaluation: VOPRFEvaluation,
        server_public_key: bytes,
    ) -> bytes:
        ...


class NativeVOPRFBackend:
    def __init__(self) -> None:
        try:
            import omneum_oprf
        except ImportError as exc:
            raise OPRFBackendUnavailableError(
                "The Omneum RFC 9497 native backend is not installed."
            ) from exc

        self._native = omneum_oprf

    def blind(
        self,
        input_data: bytes,
    ) -> VOPRFBlindResult:
        _require_input(input_data)

        try:
            blinded_element, client_state = self._native.blind(
                input_data
            )
        except Exception as exc:
            raise OPRFProtocolError(
                "RFC 9497 VOPRF client blinding failed."
            ) from exc

        return VOPRFBlindResult(
            blinded_element=_require_bytes(
                blinded_element,
                name="blinded_element",
            ),
            client_state=_require_bytes(
                client_state,
                name="client_state",
            ),
        )

    def load_server(
        self,
        private_key_file: str,
    ) -> VOPRFServerContext:
        try:
            context = self._native._VOPRFServerContext(
                private_key_file
            )
        except Exception as exc:
            raise OPRFProtocolError(
                "RFC 9497 VOPRF server initialization failed."
            ) from exc

        return NativeVOPRFServerContext(context)

    def validate_public_key(
        self,
        server_public_key: bytes,
    ) -> None:
        try:
            self._native.validate_public_key(
                server_public_key
            )
        except Exception as exc:
            raise OPRFProtocolError(
                "Malformed RFC 9497 VOPRF public key."
            ) from exc

    def finalize(
        self,
        input_data: bytes,
        client_state: bytes,
        evaluation: VOPRFEvaluation,
        server_public_key: bytes,
    ) -> bytes:
        _require_input(input_data)

        try:
            output = self._native.finalize(
                input_data,
                client_state,
                evaluation.evaluated_element,
                evaluation.proof,
                server_public_key,
            )
        except Exception as exc:
            message = str(exc)
            if "Malformed RFC 9497 VOPRF proof" in message:
                public_message = "Malformed RFC 9497 VOPRF proof."
            elif "Malformed RFC 9497 VOPRF public key" in message:
                public_message = (
                    "Malformed RFC 9497 VOPRF public key."
                )
            elif "proof failed to verify" in message:
                public_message = (
                    "RFC 9497 VOPRF proof verification failed."
                )
            else:
                public_message = (
                    "RFC 9497 VOPRF client finalization failed."
                )
            raise OPRFProtocolError(public_message) from exc

        return _require_bytes(
            output,
            name="output",
        )


class NativeVOPRFServerContext:
    def __init__(self, context: object) -> None:
        self._context = context

    @property
    def public_key(self) -> bytes:
        return _require_bytes(
            self._context.public_key,
            name="server_public_key",
        )

    def evaluate(
        self,
        blinded_element: bytes,
    ) -> VOPRFEvaluation:
        try:
            evaluated_element, proof = (
                self._context.evaluate(blinded_element)
            )
        except Exception as exc:
            if (
                "Malformed RFC 9497 VOPRF blinded element"
                in str(exc)
            ):
                raise InvalidBlindedElementError(
                    "Malformed RFC 9497 VOPRF blinded element."
                ) from exc
            raise OPRFProtocolError(
                "RFC 9497 VOPRF server evaluation failed."
            ) from exc

        return VOPRFEvaluation(
            evaluated_element=_require_bytes(
                evaluated_element,
                name="evaluated_element",
            ),
            proof=_require_bytes(
                proof,
                name="proof",
            ),
        )


class VOPRFClient:
    def __init__(
        self,
        server_public_key: bytes,
        backend: VOPRFBackend | None = None,
    ) -> None:
        self._server_public_key = _require_value_length(
            server_public_key,
            name="server_public_key",
            length=ELEMENT_LENGTH,
        )
        self._backend = backend or NativeVOPRFBackend()
        self._backend.validate_public_key(
            self._server_public_key
        )

    def blind(
        self,
        input_data: bytes,
    ) -> VOPRFBlindResult:
        _require_input(input_data)
        result = self._backend.blind(input_data)

        _require_protocol_length(
            result.blinded_element,
            name="blinded_element",
            length=ELEMENT_LENGTH,
        )
        _require_protocol_length(
            result.client_state,
            name="client_state",
            length=CLIENT_STATE_LENGTH,
        )

        return result

    def finalize(
        self,
        *,
        input_data: bytes,
        client_state: bytes,
        evaluation: VOPRFEvaluation,
    ) -> bytes:
        _require_input(input_data)
        _require_value_length(
            client_state,
            name="client_state",
            length=CLIENT_STATE_LENGTH,
        )
        if type(evaluation) is not VOPRFEvaluation:
            raise TypeError(
                "evaluation must be a VOPRFEvaluation."
            )
        _require_value_length(
            evaluation.evaluated_element,
            name="evaluated_element",
            length=ELEMENT_LENGTH,
        )
        _require_value_length(
            evaluation.proof,
            name="proof",
            length=PROOF_LENGTH,
        )
        output = self._backend.finalize(
            input_data,
            client_state,
            evaluation,
            self._server_public_key,
        )
        _require_protocol_length(
            output,
            name="output",
            length=OUTPUT_LENGTH,
        )
        return output


class VOPRFServer:
    def __init__(
        self,
        private_key_file: str | Path,
        backend: VOPRFBackend | None = None,
    ) -> None:
        private_key_file = _require_path(
            private_key_file,
            name="private_key_file",
        )
        self._backend = backend or NativeVOPRFBackend()
        self._context = self._backend.load_server(
            private_key_file
        )
        self._public_key = self._context.public_key
        _require_protocol_length(
            self._public_key,
            name="server_public_key",
            length=ELEMENT_LENGTH,
        )

    @property
    def public_key(self) -> bytes:
        return self._public_key

    def evaluate(
        self,
        blinded_element: bytes,
    ) -> VOPRFEvaluation:
        _require_value_length(
            blinded_element,
            name="blinded_element",
            length=ELEMENT_LENGTH,
        )
        evaluation = self._context.evaluate(
            blinded_element,
        )
        if type(evaluation) is not VOPRFEvaluation:
            raise OPRFProtocolError(
                "backend evaluation must be a VOPRFEvaluation."
            )
        _require_protocol_length(
            evaluation.evaluated_element,
            name="evaluated_element",
            length=ELEMENT_LENGTH,
        )
        _require_protocol_length(
            evaluation.proof,
            name="proof",
            length=PROOF_LENGTH,
        )
        return evaluation


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


def _require_path(
    value: object,
    *,
    name: str,
) -> str:
    if not isinstance(value, (str, Path)):
        raise TypeError(
            f"{name} must be a filesystem path."
        )
    return str(value)


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


def _require_input(input_data: object) -> bytes:
    input_data = _require_nonempty_bytes(
        input_data,
        name="input_data",
    )
    if len(input_data) > MAX_INPUT_LENGTH:
        raise ValueError(
            "input_data must be at most "
            f"{MAX_INPUT_LENGTH} bytes."
        )
    return input_data


def _require_value_length(
    value: object,
    *,
    name: str,
    length: int,
) -> bytes:
    value = _require_bytes(
        value,
        name=name,
    )
    if len(value) != length:
        raise ValueError(
            f"{name} must be {length} bytes; "
            f"received {len(value)}."
        )
    return value


def _require_protocol_length(
    value: object,
    *,
    name: str,
    length: int,
) -> bytes:
    value = _require_bytes(
        value,
        name=name,
    )
    if len(value) != length:
        raise OPRFProtocolError(
            f"{name} must be {length} bytes; "
            f"received {len(value)}."
        )
    return value
