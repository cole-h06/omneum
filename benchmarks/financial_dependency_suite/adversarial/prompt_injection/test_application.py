import pytest

from benchmarks.financial_dependency_suite.adversarial.prompt_injection.application import (
    TOP_N,
    case_data,
)
from benchmarks.financial_dependency_suite.application_comparison import (
    select_omneum_reranked,
)
from benchmarks.financial_dependency_suite.config import estimator_config


@pytest.mark.anyio
async def test_omneum_selection():
    clean, observations, ids = case_data("clean")
    attack, _, _ = case_data("attack")

    assert clean[-1]["text"] != attack[-1]["text"]

    clean_result = await select_omneum_reranked(
        clean,
        observations,
        ids,
        estimator=estimator_config(),
        top_n=TOP_N,
    )
    attack_result = await select_omneum_reranked(
        attack,
        observations,
        ids,
        estimator=estimator_config(),
        top_n=TOP_N,
    )

    clean_sources = [
        item["source"]
        for item in clean_result["selected"]
    ]
    attack_sources = [
        item["source"]
        for item in attack_result["selected"]
    ]

    assert clean_sources == attack_sources
    assert "untrusted_note" not in clean_sources
    assert len(clean_sources) == TOP_N
