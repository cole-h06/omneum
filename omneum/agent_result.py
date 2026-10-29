"""Client-side JSON projection of an evaluated, reconstructed context."""

import json
from collections.abc import Mapping

from .canonicalization import canonicalize_source
from .client import ContextEvaluation
from .context_selection import claim_id
from .serialization import serialize_source


def _serialize_context_result(result, *, token_counter="unspecified", include_dependencies=False):
    if not isinstance(result, Mapping) or type(result.get("evaluation")) is not ContextEvaluation:
        raise TypeError("result must contain a ContextEvaluation")
    if type(token_counter) is not str or not token_counter:
        raise ValueError("token_counter must be a nonempty description")
    evaluation = result["evaluation"]
    input_tokens = result["candidate_input_tokens"]
    selected_tokens = result["token_usage"]
    budget = result["token_budget"]
    for count in (input_tokens, selected_tokens, budget):
        if type(count) is not int or count < 0:
            raise ValueError("token counts must be nonnegative integers")
    if selected_tokens > budget:
        raise ValueError("selected context exceeds token budget")

    sources = {}
    for item in evaluation.source_reliability:
        source = item.source
        identifier = serialize_source(source.kind, canonicalize_source(source.kind, source.identifier)).hex()
        sources[identifier] = item.reliability
    support = {claim_id(item.claim): item.support for item in evaluation.claim_support}
    chunks = []
    for chunk in result["chunks"]:
        chunks.append({key: chunk[key] for key in ("chunk_id", "score", "raw_text")})
    if [chunk["chunk_id"] for chunk in chunks] != result["selected_chunk_ids"]:
        raise ValueError("selected chunk IDs and order disagree")

    # Tokenizers need not be additive or order invariant. A negative reduction
    # is possible; zero input has no ratio unless the selected context is empty.
    reduction = (input_tokens - selected_tokens) / input_tokens if input_tokens else (
        0.0 if selected_tokens == 0 else None
    )
    convergence = evaluation.convergence
    payload = {
        "evaluation": {
            "source_reliability": sources,
            "claim_support": support,
            "max_claim_support": max(support.values(), default=None),
            "converged": convergence.converged,
            "iterations": convergence.iterations,
            "convergence_delta": convergence.convergence_delta,
            "convergence_tolerance": convergence.convergence_tolerance,
        },
        "selection": {
            "input_tokens": input_tokens,
            "selected_tokens": selected_tokens,
            "token_budget": budget,
            "reduction_ratio": reduction,
            "token_counter": token_counter,
            "claim_coverage": dict(result["claim_coverage"]),
        },
        "packed_chunk_ids": list(result["selected_chunk_ids"]),
        "chunks": chunks,
        "context": result["context"],
    }
    if include_dependencies:
        pairs = []
        for pair in evaluation.pairwise_dependencies:
            source_a, source_b = (
                serialize_source(source.kind, canonicalize_source(source.kind, source.identifier)).hex()
                for source in (pair.source_a, pair.source_b)
            )
            pairs.append({"source_a": source_a, "source_b": source_b, "dependency": pair.dependency})
        payload["evaluation"]["pairwise_dependencies"] = pairs
    # Reject nonfinite or non-JSON values instead of relying on a host encoder.
    json.dumps(payload, allow_nan=False)
    return payload
