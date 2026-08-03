import json

import pytest
from mcp.types import JSONRPCMessage
from pydantic import ValidationError

from verity.base64url import decode_unpadded, encode_unpadded
from verity.canonicalization import (
    canonicalize_entity,
    canonicalize_source,
    canonicalize_value,
)
from verity.client import LinkageToken
from verity.information import Claim
from verity.linkage import LinkageClient, LinkagePurpose
from verity.models import InferCredibilityRequest
from verity.oprf import (
    OPRFProtocolError,
    VOPRFClient,
    VOPRFEvaluation,
    VOPRFServer,
)
from verity.serialization import MAX_INTEGER, serialize_claim


DEPLOYMENT_ID = "urn:uuid:8d96fc18-f40f-4ec7-8ae8-f3711d88b741"
SERVER_KEY = b"\x01" + b"\x00" * 31
SECOND_KEY = b"\x02" + b"\x00" * 31
INTERNAL_ID = (
    "v1:12345678-1234-4abc-8def-123456789abc:"
    "11111111-1111-4111-8111-111111111111"
)


def server(tmp_path, key=SERVER_KEY):
    path = tmp_path / f"key-{key[0]}"
    path.write_bytes(key)
    return VOPRFServer(path)


def inference_request():
    token = encode_unpadded(b"s" * 64, expected_length=64)
    return {
        "protocol_version": "v1",
        "deployment_id": DEPLOYMENT_ID,
        "voprf_key_version": 1,
        "voprf_mode": "voprf",
        "voprf_ciphersuite": "ristretto255-SHA512",
        "linkage_encoding_version": 1,
        "assertions": [{
            "source_id": token,
            "attribute_id": encode_unpadded(b"a" * 64, expected_length=64),
            "claim_id": encode_unpadded(b"c" * 64, expected_length=64),
        }],
        "source_pairs": [],
    }


def test_claim_mutations():
    assert serialize_claim("service", "café", "value", True) != (
        serialize_claim("service", "café", "value", 1)
    )
    assert serialize_claim("service", "café", "value", [1]) != (
        serialize_claim("service", "café", "value", {"0": 1})
    )
    first = Claim("service", "cafe\u0301", "value", {"b": 2, "a": 1})
    second = Claim("service", "café", "value", {"a": 1, "b": 2})
    assert serialize_claim(
        first.entity_namespace,
        canonicalize_entity(first.entity_namespace, first.entity),
        first.attribute,
        first.value,
    ) == serialize_claim(
        second.entity_namespace,
        canonicalize_entity(second.entity_namespace, second.entity),
        second.attribute,
        second.value,
    )
    assert serialize_claim("service", "entity", "value", -0.0) == (
        serialize_claim("service", "entity", "value", 0.0)
    )
    assert canonicalize_value("a") != canonicalize_value("а")

    value = None
    for _ in range(32):
        value = [value]
    serialize_claim("service", "entity", "value", value)
    with pytest.raises(ValueError):
        serialize_claim("service", "entity", "value", [value])

    for invalid in (
        MAX_INTEGER + 1,
        float("nan"),
        float("inf"),
        float("-inf"),
    ):
        with pytest.raises(ValueError):
            serialize_claim("service", "entity", "value", invalid)


def test_source_mutations():
    assert canonicalize_source(
        "web_document",
        "HTTPS://EXAMPLE.COM:443/path",
    ) == "https://example.com/path"
    assert canonicalize_source(
        "web_document",
        "https://example.com:8443/path",
    ) == "https://example.com:8443/path"
    assert canonicalize_source("internal_resource", INTERNAL_ID) == INTERNAL_ID

    for invalid in (
        f" {INTERNAL_ID}",
        f"urn:{INTERNAL_ID}",
        f"{INTERNAL_ID}/path",
        f"{INTERNAL_ID}?query=secret",
        INTERNAL_ID.replace("11111111-", "{11111111-"),
        INTERNAL_ID.replace("v1:", "V1:"),
    ):
        with pytest.raises(
            ValueError,
            match="^internal source identifier is invalid$",
        ) as caught:
            canonicalize_source("internal_resource", invalid)
        assert "secret" not in repr(caught.value)


def test_json_limits():
    envelope = JSONRPCMessage.model_validate_json(
        '{"jsonrpc":"2.0","id":1,"method":"first","method":"last",'
        '"params":{"source_id":"first","source_id":"last"}}'
    )
    assert envelope.root.method == "last"
    assert envelope.root.params == {"source_id": "last"}
    assert json.loads('{"value":1e400}')["value"] == float("inf")
    with pytest.raises(json.JSONDecodeError):
        json.loads('{"protocol_version":"v1"')
    with pytest.raises(ValidationError):
        JSONRPCMessage.model_validate_json('{"jsonrpc":"2.0"')

    nested = "[" * 500 + "0" + "]" * 500
    with pytest.raises(ValidationError):
        JSONRPCMessage.model_validate_json(nested)

    baseline = inference_request()
    InferCredibilityRequest.model_validate(baseline, strict=True)
    mutations = (
        {**baseline, "unknown": "secret-marker"},
        {key: value for key, value in baseline.items() if key != "assertions"},
        {**baseline, "voprf_key_version": "1"},
        {
            **baseline,
            "assertions": [{**baseline["assertions"][0], "claim_id": 1}],
        },
    )
    for mutation in mutations:
        with pytest.raises(ValidationError):
            InferCredibilityRequest.model_validate(mutation, strict=True)


def test_base64_mutations():
    canonical = encode_unpadded(b"\x00" * 32, expected_length=32)
    for invalid in (
        canonical + "=",
        canonical[:-1] + "+",
        canonical[:-1] + " ",
        canonical[:-1],
        canonical + "A",
        canonical[:-1] + "B",
    ):
        with pytest.raises(
            ValueError,
            match="^protocol value must be canonical base64url$",
        ) as caught:
            decode_unpadded(invalid, expected_length=32)
        assert canonical not in repr(caught.value)


def test_voprf_substitution(tmp_path):
    first_server = server(tmp_path)
    second_server = server(tmp_path, SECOND_KEY)
    first_client = VOPRFClient(first_server.public_key)
    wrong_client = VOPRFClient(second_server.public_key)
    first_blind = first_client.blind(b"first")
    second_blind = first_client.blind(b"second")
    first_evaluation = first_server.evaluate(first_blind.blinded_element)
    second_evaluation = first_server.evaluate(second_blind.blinded_element)

    substitutions = (
        second_evaluation,
        VOPRFEvaluation(
            first_evaluation.evaluated_element,
            second_evaluation.proof,
        ),
    )
    for evaluation in substitutions:
        with pytest.raises(OPRFProtocolError):
            first_client.finalize(
                input_data=b"first",
                client_state=first_blind.client_state,
                evaluation=evaluation,
            )
    with pytest.raises(OPRFProtocolError):
        wrong_client.finalize(
            input_data=b"first",
            client_state=first_blind.client_state,
            evaluation=first_evaluation,
        )


def test_purpose_separation(tmp_path):
    oprf_server = server(tmp_path)
    linkage = LinkageClient(VOPRFClient(oprf_server.public_key))
    blinds = (
        linkage.blind_source("internal_resource", INTERNAL_ID),
        linkage.blind_attribute("service", "entity", "attribute"),
        linkage.blind_claim("service", "entity", "attribute", "value"),
    )
    tokens = tuple(
        linkage.finalize(
            blind,
            oprf_server.evaluate(blind.blinded_element),
        )
        for blind in blinds
    )
    assert len(set(tokens)) == 3
    assert all("_client_state" not in repr(blind) for blind in blinds)

    repeated = linkage.blind_source("internal_resource", INTERNAL_ID)
    repeated_token = linkage.finalize(
        repeated,
        oprf_server.evaluate(repeated.blinded_element),
    )
    assert repeated.blinded_element != blinds[0].blinded_element
    assert repeated_token == tokens[0]

    other_scope = INTERNAL_ID.replace(
        "12345678-1234-4abc-8def-123456789abc",
        "22345678-1234-4abc-8def-123456789abc",
    )
    scoped = linkage.blind_source("internal_resource", other_scope)
    assert linkage.finalize(
        scoped,
        oprf_server.evaluate(scoped.blinded_element),
    ) != tokens[0]

    second_server = server(tmp_path, SECOND_KEY)
    second_linkage = LinkageClient(VOPRFClient(second_server.public_key))
    keyed = second_linkage.blind_source("internal_resource", INTERNAL_ID)
    assert second_linkage.finalize(
        keyed,
        second_server.evaluate(keyed.blinded_element),
    ) != tokens[0]

    first_identity = LinkageToken(
        DEPLOYMENT_ID,
        1,
        "voprf",
        "ristretto255-SHA512",
        1,
        LinkagePurpose.SOURCE,
        tokens[0],
    )
    second_identity = LinkageToken(
        "urn:uuid:9d96fc18-f40f-4ec7-8ae8-f3711d88b741",
        1,
        "voprf",
        "ristretto255-SHA512",
        1,
        LinkagePurpose.SOURCE,
        tokens[0],
    )
    assert first_identity != second_identity
