import pytest

from omneum.canonicalization import canonicalize_entity


@pytest.mark.parametrize(
    "namespace",
    ["company", "service", "repository", "custom_domain"],
)
def test_custom_entity_namespace(namespace):
    assert canonicalize_entity(namespace, "  Acme  ") == "acme"


@pytest.mark.parametrize("namespace", ["", " ", " company "])
def test_invalid_entity_namespace(namespace):
    with pytest.raises(ValueError):
        canonicalize_entity(namespace, "acme")