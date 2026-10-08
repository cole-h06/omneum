"""Opt-in methods outside the frozen benchmark matrix."""

from .methods import METHODS, MethodSpec
from benchmarks.financial_dependency_suite.clients import DEFAULT_MODELS


ADDITIVE_METHODS = (
    MethodSpec(name="bge_openai", method="bge_openai", provider="openai", model=DEFAULT_MODELS["openai"], stochastic=True),
    MethodSpec(name="cohere_anthropic", method="cohere_anthropic", provider="anthropic", model="claude-sonnet-5-5", stochastic=True),
    MethodSpec(name="bge_anthropic", method="bge_anthropic", provider="anthropic", model="claude-sonnet-5-5", stochastic=True),
    MethodSpec(name="bge_omneum", method="bge_omneum", model="Omneum"),
    MethodSpec(name="cohere_omneum", method="cohere_omneum", provider="cohere", model="rerank-v4.0-pro"),
    MethodSpec(name="anthropic_omneum", method="anthropic_omneum", model="Omneum"),
)


def method_by_name(name):
    for method in (*METHODS, *ADDITIVE_METHODS):
        if method.name == name:
            return method
    raise KeyError(name)
