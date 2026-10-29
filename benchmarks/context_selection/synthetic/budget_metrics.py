"""Additive evaluation diagnostics; never used to rank or select evidence.

Source recall retains its original all-supporting-sources denominator. Claim
coverage is a separate annotation-derived measure, not answer correctness.
"""

from itertools import permutations
from math import perm

from .scoring import score_selection


METRIC_VERSION = "budget-aware-source-recall-v1"


def _budget(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("budget must be a nonnegative integer")


def _metrics(selected, truth, achievable):
    expected = set(truth.supporting_sources)
    recall = score_selection(selected, truth)["recall"]
    ceiling = achievable / len(expected) if expected else 0.0
    return {
        "metric_version": METRIC_VERSION,
        "annotated_supporting_sources": len(expected),
        "max_feasible_supporting_sources": achievable,
        "source_recall_ceiling": ceiling,
        "budget_normalized_source_recall": recall / ceiling if ceiling else None,
        "full_source_recall_feasible": bool(expected) and achievable == len(expected),
    }


def passage_budget_metrics(selected, truth, *, candidate_sources, passage_budget):
    """Exact ceiling for unique-source passages with at most K passages.

One candidate passage per source is required; unavailable annotated sources
remain in the original recall denominator. Undefined normalization is null.
"""
    _budget(passage_budget)
    candidates = tuple(candidate_sources)
    if len(candidates) != len(set(candidates)):
        raise ValueError("passage-count ceiling requires one candidate per source")
    selected = tuple(selected)
    if len(selected) != len(set(selected)) or not set(selected) <= set(candidates):
        raise ValueError("selection must contain distinct available sources")
    if len(selected) > passage_budget:
        raise ValueError("selection exceeds passage budget")
    achievable = min(passage_budget, len(set(candidates) & set(truth.supporting_sources)))
    return {"budget_type": "passage_count", "passage_budget": passage_budget,
            **_metrics(selected, truth, achievable)}


def token_budget_metrics(selected, truth, *, chunks, token_budget, render, count_tokens,
                         max_renderings=1_000_000):
    """Exact whole-passage ceiling using the caller's real renderer/tokenizer.

Enumerate all ordered subsets, including distractors: tokenization need not be
additive, monotone, or order invariant. No sum-of-chunk-cost approximation or
passage-count formula is used. Refuse oversized pools rather than report an
unproven bound. This offline diagnostic is deliberately outside timed selection.
    """
    _budget(token_budget)
    chunks, selected = tuple(chunks), tuple(selected)
    ids = [c["chunk_id"] for c in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("candidate chunk IDs must be unique")
    by_id = dict(zip(ids, chunks))
    selected_ids = [c["chunk_id"] for c in selected]
    if len(selected_ids) != len(set(selected_ids)) or any(
        c["chunk_id"] not in by_id or c != by_id[c["chunk_id"]] for c in selected
    ):
        raise ValueError("selection must contain distinct original candidate chunks")
    work = sum(perm(len(chunks), k) for k in range(len(chunks) + 1))
    if work > max_renderings:
        raise ValueError(f"exact feasibility requires {work} renderings; limit {max_renderings}")

    def cost(items):
        value = count_tokens(render(items))
        _budget(value)
        return value

    selected_tokens = cost(selected)
    if selected_tokens > token_budget:
        raise ValueError("selection exceeds rendered token budget")
    expected = set(truth.supporting_sources)
    achievable = 0
    for size in range(len(chunks) + 1):
        for subset in permutations(chunks, size):
            if cost(subset) <= token_budget:
                achievable = max(achievable, len({c["source_id"] for c in subset} & expected))
    return {"budget_type": "rendered_tokens", "token_budget": token_budget,
            "selected_rendered_tokens": selected_tokens, "feasibility_renderings": work,
            "feasibility_scope": "all ordered whole-candidate subsets",
            **_metrics([c["source_id"] for c in selected], truth, achievable)}


def required_claim_coverage(selected_claims, required_claims):
    """Distinct mapped claims annotated via supporting passages; no source proxy."""
    required, selected = set(required_claims), set(selected_claims)
    covered = len(required & selected)
    return {"required_claims": len(required), "covered_required_claims": covered,
            "required_claim_coverage": covered / len(required) if required else None,
            "required_claim_coverage_basis": "union of structured claims in annotated supporting passages"}


def case_claim_coverage(case, truth, selected_sources):
    from omneum.context_selection import claim_id
    from .loader import build_observations
    from .schema import candidate_claims

    observations, _ = build_observations(case)
    by_id = {o.observation_id: claim_id(o.claim) for o in observations}
    required, selected = set(), set()
    for candidate in case.candidates:
        claims = {by_id[c.observation_id] for c in candidate_claims(candidate)}
        if candidate.source_id in truth.supporting_sources:
            required.update(claims)
        if candidate.source_id in selected_sources:
            selected.update(claims)
    return required_claim_coverage(selected, required)
