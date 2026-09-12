import json

from benchmarks.financial_dependency_suite.heldout.loader import (
    application_candidates,
    build_observations,
    load_case,
    load_ground_truth,
)


def test_case_loader(tmp_path):
    case_path = tmp_path / "case.json"
    case_path.write_text(json.dumps({
        "id": "test_case",
        "domain": "test",
        "question": "What happened?",
        "context_budget": 1,
        "candidates": [
            {
                "source_id": "source_a",
                "source": {
                    "kind": "web_document",
                    "identifier": "https://example.com/a",
                },
                "text": "Candidate text.",
                "entity_namespace": "test",
                "entity": "example",
                "attribute": "value",
                "value": 42,
                "provenance": {
                    "assertion_id": "assertion-a",
                    "observed_at": "2026-09-11T00:00:00Z",
                    "source_modified_at": "2026-09-10T00:00:00Z",
                    "upstream_sources": [],
                    "cited_sources": [],
                    "parent_assertion_ids": [],
                },
            }
        ],
    }))

    case = load_case(case_path)
    observations, source_ids = build_observations(case)
    candidates = application_candidates(case)

    assert case.case_id == "test_case"
    assert case.context_budget == 1
    assert len(observations) == 1
    assert next(iter(source_ids.values())) == "source_a"
    assert candidates == [
        {
            "source": "source_a",
            "text": "Candidate text.",
        }
    ]


def test_ground_truth_separate(tmp_path):
    case_path = tmp_path / "case.json"
    truth_path = tmp_path / "ground_truth.json"

    case_path.write_text(json.dumps({
        "id": "test_case",
        "domain": "test",
        "question": "What happened?",
        "context_budget": 1,
        "candidates": [],
    }))

    truth_path.write_text(json.dumps({
        "case_id": "test_case",
        "answer": "secret answer",
        "supporting_sources": ["source_a"],
        "scoring": {
            "required": ["secret answer"],
            "forbidden": ["wrong answer"],
        },
    }))

    case = load_case(case_path)
    truth = load_ground_truth(truth_path)

    assert case.case_id == truth.case_id
    assert not hasattr(case, "answer")
    assert not hasattr(case, "supporting_sources")
    assert truth.answer == "secret answer"
