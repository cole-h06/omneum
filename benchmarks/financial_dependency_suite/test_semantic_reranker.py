from benchmarks.financial_dependency_suite.semantic_reranker import (
    rerank_bge,
)


def test_bge_reranks_fixed_candidate_pool():
    candidates = [
        {
            "source": "unrelated",
            "score": 0.9,
            "text": "The deployment uses three availability zones.",
        },
        {
            "source": "retention",
            "score": 0.5,
            "text": "The payments-api retention period is 90 days.",
        },
        {
            "source": "timeout",
            "score": 0.7,
            "text": "The payments-api request timeout is 60 seconds.",
        },
    ]

    selected = rerank_bge(
        "What is the payments-api retention period?",
        candidates,
        top_n=2,
    )

    assert len(selected) == 2
    assert selected[0]["source"] == "retention"
    assert {
        item["source"]
        for item in selected
    }.issubset({
        item["source"]
        for item in candidates
    })
    assert all(
        "reranker_score" in item
        for item in selected
    )
