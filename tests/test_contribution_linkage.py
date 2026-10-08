import pytest

from omneum.contribution import (
    NetworkLinkageConfig,
    NetworkLinkageToken,
)


def test_network_linkage_config():
    config = NetworkLinkageConfig(
        key_version=1,
        public_key=b"x" * 32,
    )

    assert config.key_version == 1
    assert config.public_key == b"x" * 32


@pytest.mark.parametrize("version", [0, 2**32])
def test_network_linkage_key_version(version):
    with pytest.raises(ValueError):
        NetworkLinkageConfig(
            key_version=version,
            public_key=b"x" * 32,
        )


def test_network_linkage_public_key_length():
    with pytest.raises(ValueError):
        NetworkLinkageConfig(
            key_version=1,
            public_key=b"x" * 31,
        )


def test_network_token():
    token = NetworkLinkageToken(
        key_version=1,
        value=b"x" * 64,
    )

    assert token.key_version == 1
    assert token.value == b"x" * 64


def test_network_token_length():
    with pytest.raises(ValueError):
        NetworkLinkageToken(
            key_version=1,
            value=b"x" * 63,
        )


def test_network_identity_stable_across_local_deployments(tmp_path):
    from tests.test_adversarial_pipeline import (
        SECOND_KEY,
        server,
    )

    from omneum.contribution import (
        NetworkLinkageClient,
        NetworkLinkageConfig,
    )
    from omneum.linkage import LinkageClient
    from omneum.oprf import VOPRFClient

    network_server = server(tmp_path)
    local_server_a = server(tmp_path, SECOND_KEY)

    network_a = NetworkLinkageClient(
        NetworkLinkageConfig(
            key_version=1,
            public_key=network_server.public_key,
        )
    )
    network_b = NetworkLinkageClient(
        NetworkLinkageConfig(
            key_version=1,
            public_key=network_server.public_key,
        )
    )

    kind = "web_document"
    identifier = "https://example.com/report"

    blind_a = network_a.blind_source(kind, identifier)
    blind_b = network_b.blind_source(kind, identifier)

    assert blind_a.blinded_element != blind_b.blinded_element

    token_a = network_a.finalize(
        blind_a,
        network_server.evaluate(blind_a.blinded_element),
    )
    token_b = network_b.finalize(
        blind_b,
        network_server.evaluate(blind_b.blinded_element),
    )

    assert token_a == token_b

    local = LinkageClient(
        VOPRFClient(local_server_a.public_key)
    )
    local_blind = local.blind_source(kind, identifier)
    local_token = local.finalize(
        local_blind,
        local_server_a.evaluate(local_blind.blinded_element),
    )

    assert local_token != token_a.value
