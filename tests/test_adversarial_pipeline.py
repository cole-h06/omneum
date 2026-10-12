
from daemon_support import VOPRFServer
import json

import pytest
from omneum.mcp.types import JSONRPCMessage
from pydantic import ValidationError

from omneum.base64url import encode_unpadded
from omneum.client import LinkageToken
from omneum.linkage import LinkageClient, LinkagePurpose
from omneum.oprf import (
    OPRFProtocolError,
    VOPRFClient,
    VOPRFEvaluation,
)


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
