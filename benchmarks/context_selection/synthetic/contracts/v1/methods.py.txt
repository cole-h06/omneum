from dataclasses import dataclass

from benchmarks.financial_dependency_suite.application_comparison import (
    LLM_SELECTORS,
)


@dataclass(frozen=True)
class MethodSpec:
    name: str
    method: str
    provider: str | None = None
    model: str | None = None
    stochastic: bool = False


METHODS = (
    MethodSpec(
        name="vector",
        method="vector",
    ),
    MethodSpec(
        name="bge",
        method="bge",
    ),
    MethodSpec(
        name="cohere",
        method="cohere",
        provider="cohere",
        model="rerank-v4.0-pro",
    ),
    *(
        MethodSpec(
            name=provider,
            method="llm",
            provider=provider,
            model=model,
            stochastic=True,
        )
        for provider, model in LLM_SELECTORS
    ),
    *(
        MethodSpec(
            name=f"{provider}_provenance",
            method="llm_provenance",
            provider=provider,
            model=model,
            stochastic=True,
        )
        for provider, model in LLM_SELECTORS
    ),
    MethodSpec(
        name="braid",
        method="braid",
    ),
)


def method_by_name(name):
    for method in METHODS:
        if method.name == name:
            return method

    raise KeyError(name)
