import pytest

from benchmarks.financial_dependency_suite.adversarial.prompt_injection.application import (
    TOP_N,
    case_data,
)
from benchmarks.financial_dependency_suite.application_comparison import (
    select_braid,
)
from benchmarks.financial_dependency_suite.run_suite import (
    estimator_config,
)


@pytest.mark.anyio
async def test_braid_selection():
    clean, observations, ids = case_data("clean")
    attack, _, _ = case_data("attack")

    assert clean[-1]["text"] != attack[-1]["text"]

    clean_result = await select_braid(
        clean,
        observations,
        ids,
        estimator=estimator_config(),
        top_n=TOP_N,
    )
    attack_result = await select_braid(
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
