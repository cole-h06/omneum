"""VOPRF request privacy, key-label limits, and integrity boundaries."""
import asyncio
from dataclasses import replace

import pytest

from omneum import NetworkContributionError
from omneum.contribution.linkage import NetworkLinkageClient, NetworkLinkageConfig
from omneum.linkage import LinkageClient
from omneum.oprf import VOPRFEvaluation
from test_client_contribution import network, run
from test_local_persistence import runtime
from test_storage_evaluation import computed


@pytest.mark.parametrize('invalid_proof', [False, True])
def test_private_input_and_state_never_enter_network_request(runtime, network, monkeypatch, caplog,
                                                            invalid_proof):
    blinds, requests = [], []
    original_blind = LinkageClient._blind
    original_evaluate = network[0].evaluator.evaluate

    def capture_blind(self, *args):
        result = original_blind(self, *args)
        blinds.append(result)
        return result

    async def capture_request(**kwargs):
        requests.append(kwargs)
        response = await original_evaluate(**kwargs)
        return VOPRFEvaluation(response.evaluated_element, b'\xff' * 64) if invalid_proof else response

    monkeypatch.setattr(LinkageClient, '_blind', capture_blind)
    monkeypatch.setattr(network[0].evaluator, 'evaluate', capture_request)
    if invalid_proof:
        with pytest.raises(NetworkContributionError) as caught:
            run(runtime, network_contribution=network[0])
        assert caught.value.reason == 'contribution_preparation_failed'
        assert caught.value.contribution is None
        assert network[2] == []
        assert 'private-' not in str(caught.value)
    else:
        run(runtime, network_contribution=network[0])
    assert requests
    wire = repr(requests) + caplog.text + ''.join(p.model_dump_json() for p in network[2])
    for request in requests:
        assert set(request) == {'key_version', 'blinded_element'}
        assert type(request['blinded_element']) is bytes
        assert len(request['blinded_element']) == 32
        blind = next(b for b in blinds if b.blinded_element == request['blinded_element'])
        assert blind._encoded_input not in request.values()
        assert blind._client_state not in request.values()
        assert repr(blind._encoded_input) not in wire
        assert repr(blind._client_state) not in wire
        assert blind._client_state.hex() not in wire
    for observation in runtime[2]:
        assert observation.source.identifier not in wire
        assert observation.claim.value not in wire


def test_changing_key_version_label_is_not_key_rotation(network):
    config = network[0].linkage
    first = NetworkLinkageClient(config)
    relabeled = NetworkLinkageClient(replace(config, key_version=config.key_version + 1))

    async def token(client):
        blind = client.blind_source('web_document', 'https://example.com/candidate')
        evaluation = await network[0].evaluator.evaluate(
            key_version=client.key_version, blinded_element=blind.blinded_element)
        return client.finalize(blind, evaluation)

    a, b = asyncio.run(token(first)), asyncio.run(token(relabeled))
    assert a.value == b.value
    assert a != b  # Versioned storage identities differ; bytes remain linkable.
