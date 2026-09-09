
from daemon_support import VOPRFServer
import json

from pathlib import Path

import pytest

from omneum.canonicalization import canonicalize_source
from omneum.linkage import LinkagePurpose, encode_linkage_input
from omneum.oprf import VOPRFClient
from omneum.serialization import serialize_source


VECTOR_DIR = Path(__file__).parent / "vectors"
KINDS = (
    "internal_resource",
    "internal_service",
    "database",
)


def load(name):
    return json.loads(
        (VECTOR_DIR / name).read_text(encoding="utf-8")
    )


def test_canonical():
    vector = load("internal_source_canonicalization_v1.json")

    for case in vector["canonical_cases"]:
        value = canonicalize_source(case["kind"], case["input"])

        assert value == case["expected"]
        assert len(value.encode("utf-8")) == vector[
            "canonical_identifier_length"
        ]


def test_idempotent():
    vector = load("internal_source_canonicalization_v1.json")

    for kind in KINDS:
        for value in vector["idempotence_cases"]:
            first = canonicalize_source(kind, value)
            second = canonicalize_source(kind, first)

            assert first == value
            assert second == value


def test_rejections():
    vector = load("internal_source_canonicalization_v1.json")

    for kind in KINDS:
        for case in vector["rejection_cases"]:
            with pytest.raises(ValueError) as caught:
                canonicalize_source(kind, case["input"])

            assert str(caught.value) == vector["fixed_error"]
            assert repr(caught.value) == (
                f"ValueError({vector['fixed_error']!r})"
            )
            if case["input"]:
                assert case["input"] not in str(caught.value)


def test_types():
    vector = load("internal_source_canonicalization_v1.json")

    for kind in KINDS:
        for value in vector["wrong_type_cases"]:
            with pytest.raises(TypeError) as caught:
                canonicalize_source(kind, value)

            assert str(caught.value) == vector["fixed_type_error"]
            assert repr(caught.value) == (
                f"TypeError({vector['fixed_type_error']!r})"
            )


def test_database_rejections():
    vector = load("internal_source_canonicalization_v1.json")

    for case in vector["database_rejection_cases"]:
        with pytest.raises(ValueError) as caught:
            canonicalize_source("database", case["input"])

        assert str(caught.value) == vector["fixed_error"]
        assert case["input"] not in str(caught.value)


def test_separation():
    vector = load("internal_source_canonicalization_v1.json")

    for values in vector["separation_cases"].values():
        canonical = tuple(
            canonicalize_source("internal_resource", value)
            for value in values
        )

        assert canonical[0] != canonical[1]


def test_payloads():
    vectors = load("canonical_linkage.json")

    for vector in vectors:
        values = vector["input"]
        if vector["type"] != "source" or values["kind"] not in KINDS:
            continue
        identifier = canonicalize_source(
            values["kind"],
            values["identifier"],
        )
        payload = serialize_source(values["kind"], identifier)

        assert payload.hex() == vector["canonical_hex"]


def test_linkage_inputs():
    vectors = load("linkage_input_v1.json")

    for vector in vectors:
        kind = vector["name"].removesuffix("_source")
        if kind not in KINDS:
            continue
        payload = bytes.fromhex(vector["canonical_payload_hex"])
        encoded = encode_linkage_input(
            payload,
            LinkagePurpose.SOURCE,
        )

        assert encoded.hex() == vector["encoded_input_hex"]


def test_tokens(tmp_path):
    vector = load("internal_source_canonicalization_v1.json")
    separation = vector["cross_kind_separation"]
    key = tmp_path / "voprf.key"
    key.write_bytes(bytes.fromhex(separation["private_key_hex"]))
    server = VOPRFServer(key)
    outputs = []

    assert server.public_key.hex() == separation["public_key_hex"]
    for kind in KINDS:
        identifier = canonicalize_source(
            kind,
            separation["identifier"],
        )
        payload = serialize_source(kind, identifier)
        encoded = encode_linkage_input(
            payload,
            LinkagePurpose.SOURCE,
        )
        client = VOPRFClient(server.public_key)
        blind = client.blind(encoded)
        evaluation = server.evaluate(blind.blinded_element)
        output = client.finalize(
            input_data=encoded,
            client_state=blind.client_state,
            evaluation=evaluation,
        )

        assert output.hex() == separation["tokens"][kind]
        outputs.append(output)

    assert len(set(outputs)) == len(KINDS)


def test_web_sources():
    assert canonicalize_source(
        "web_publisher",
        "https://Docs.Anthropic.com/",
    ) == "docs.anthropic.com"
    assert canonicalize_source(
        "web_document",
        "HTTPS://Example.com/docs/api#section",
    ) == "https://example.com/docs/api"


def test_default_ports(tmp_path):
    vector = load("web_source_canonicalization_v1.json")
    key = tmp_path / "web-voprf.key"
    key.write_bytes(bytes.fromhex(vector["private_key_hex"]))
    server = VOPRFServer(key)

    assert server.public_key.hex() == vector["public_key_hex"]
    for case in vector["default_port_cases"]:
        values = tuple(
            canonicalize_source("web_document", value)
            for value in case["inputs"]
        )
        payloads = tuple(
            serialize_source("web_document", value)
            for value in values
        )
        encoded = tuple(
            encode_linkage_input(payload, LinkagePurpose.SOURCE)
            for payload in payloads
        )
        outputs = []
        for value in encoded:
            client = VOPRFClient(server.public_key)
            blind = client.blind(value)
            evaluation = server.evaluate(blind.blinded_element)
            outputs.append(client.finalize(
                input_data=value,
                client_state=blind.client_state,
                evaluation=evaluation,
            ))

        assert values == (case["canonical"], case["canonical"])
        assert canonicalize_source("web_document", values[0]) == values[0]
        assert len(set(payloads)) == 1
        assert payloads[0].hex() == case["payload_hex"]
        assert len(set(encoded)) == 1
        assert encoded[0].hex() == case["encoded_input_hex"]
        assert len(set(outputs)) == 1
        assert outputs[0].hex() == case["token_hex"]


def test_nondefault_ports():
    vector = load("web_source_canonicalization_v1.json")

    for case in vector["nondefault_port_cases"]:
        canonical = canonicalize_source("web_document", case["input"])

        assert canonical == case["canonical"]
        assert canonical != canonicalize_source(
            "web_document",
            case["without_port"],
        )
        assert canonicalize_source("web_document", canonical) == canonical


def test_web_idna():
    vector = load("web_source_canonicalization_v1.json")

    for case in vector["idna_cases"]:
        canonical = canonicalize_source(case["kind"], case["input"])

        assert canonical == case["canonical"]
        assert canonicalize_source(case["kind"], canonical) == canonical


def test_package():
    with pytest.raises(ValueError, match="unknown source kind"):
        canonicalize_source(
            "package",
            "v1:01234567-89ab-4def-8123-456789abcdef:"
            "11111111-2222-4333-8444-555555555555",
        )
