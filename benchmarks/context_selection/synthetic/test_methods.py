from benchmarks.context_selection.synthetic.methods import (
    METHODS,
    method_by_name,
)


def test_method_matrix():
    assert [method.name for method in METHODS] == [
        "vector",
        "bge",
        "cohere",
        "anthropic",
        "openai",
        "google",
        "anthropic_provenance",
        "openai_provenance",
        "google_provenance",
        "omneum",
    ]


def test_frontier_models():
    methods = {
        method.name: method
        for method in METHODS
    }

    for provider in (
        "anthropic",
        "openai",
        "google",
    ):
        plain = methods[provider]
        provenance = methods[f"{provider}_provenance"]

        assert plain.model == provenance.model
        assert plain.provider == provider
        assert provenance.provider == provider
        assert plain.stochastic
        assert provenance.stochastic


def test_method_lookup():
    assert method_by_name("omneum").method == "omneum"
