from collections.abc import Callable, Mapping, Sequence
import re
from typing import Any

from .canonicalization import canonicalize_entity
from .client import ContextEvaluation
from .information import Claim, _string
from .serialization import serialize_claim


STRATEGIES = ("retrieval", "max_support", "mean_support", "coverage_support")
TOKEN_PATTERN = r"\w+|[^\w\s]"


def claim_id(claim: Claim) -> str:
    return serialize_claim(
        claim.entity_namespace,
        canonicalize_entity(claim.entity_namespace, claim.entity),
        claim.attribute,
        claim.value,
    ).hex()


def map_chunks(chunks, claims):
    if not isinstance(chunks, Sequence) or isinstance(chunks, (str, bytes)):
        raise TypeError("chunks must be a sequence of mappings")
    chunk_text = {}
    chunk_claims = {}
    claim_chunks = {identifier: [] for identifier in claims}
    for chunk in chunks:
        if not isinstance(chunk, Mapping):
            raise TypeError("chunks must contain mappings")
        if not {"chunk_id", "raw_text", "claim_ids"} <= chunk.keys():
            raise ValueError("chunk requires chunk_id, raw_text, and claim_ids")
        identifier = chunk["chunk_id"]
        _string(identifier, "chunk ID")
        if type(chunk["raw_text"]) is not str:
            raise TypeError("chunk text must be a string")
        if not isinstance(chunk["claim_ids"], Sequence) or isinstance(chunk["claim_ids"], (str, bytes)):
            raise TypeError("claim_ids must be a sequence of strings")
        for value in chunk["claim_ids"]:
            _string(value, "claim ID")
        if identifier in chunk_text:
            raise ValueError("duplicate chunk ID")
        mapped = sorted(set(chunk["claim_ids"]))
        if not mapped or any(value not in claim_chunks for value in mapped):
            raise ValueError("chunk requires known claim mappings")
        chunk_text[identifier] = chunk["raw_text"]
        chunk_claims[identifier] = mapped
        for value in mapped:
            claim_chunks[value].append(identifier)
    if chunk_text and any(not values for values in claim_chunks.values()):
        raise ValueError("evaluated claim has no chunk mapping")
    return {
        "chunk_text": chunk_text,
        "chunk_claims": chunk_claims,
        "claim_chunks": claim_chunks,
        "retrieval_order": list(chunk_text),
    }


def token_count(text: str) -> int:
    return len(re.findall(TOKEN_PATTERN, text))


def reconstruct(mapping, chunk_ids):
    selected = set(chunk_ids)
    if not selected <= mapping["chunk_text"].keys():
        raise ValueError("unknown selected chunk")
    return "\n\n".join(
        f"[{identifier}]\n{mapping['chunk_text'][identifier]}"
        for identifier in mapping["retrieval_order"] if identifier in selected
    )


def select_chunks(mapping, support, token_budget, strategy, *, count_tokens=token_count):
    if type(token_budget) is not int or token_budget < 0:
        raise ValueError("token budget must be a nonnegative integer")
    if strategy not in STRATEGIES:
        raise ValueError("unknown selection strategy")
    if set(support) != set(mapping["claim_chunks"]):
        raise ValueError("claim scores and mappings disagree")

    def usage(text):
        count = count_tokens(text)
        if type(count) is not int or count < 0:
            raise ValueError("token counter must return a nonnegative integer")
        return count

    covered = set()
    selected = []
    selection_scores = []
    remaining = list(mapping["retrieval_order"])

    def score(identifier):
        claims = mapping["chunk_claims"][identifier]
        if strategy == "retrieval":
            return 0.0
        if strategy == "max_support":
            return max(support[value] for value in claims)
        if strategy == "mean_support":
            return sum(support[value] for value in claims) / len(claims)
        return sum(support[value] for value in claims if value not in covered)

    candidate_scores = {identifier: score(identifier) for identifier in remaining}
    render_mapping = {
        **mapping,
        "retrieval_order": sorted(remaining, key=lambda identifier: -candidate_scores[identifier]),
    }
    while remaining:
        fitting = [
            identifier for identifier in remaining
            if usage(reconstruct(render_mapping, [*selected, identifier])) <= token_budget
        ]
        if not fitting:
            break
        # Ties retain retrieval order.
        identifier = max(fitting, key=score)
        gain = score(identifier)
        if strategy == "coverage_support" and gain <= 0.0:
            break
        selected.append(identifier)
        selection_score = {"chunk_id": identifier, "score": gain}
        if strategy == "coverage_support":
            selection_score["marginal_gain"] = gain
        selection_scores.append(selection_score)
        covered.update(mapping["chunk_claims"][identifier])
        remaining.remove(identifier)

    ordered = [identifier for identifier in render_mapping["retrieval_order"] if identifier in selected]
    context = reconstruct(render_mapping, ordered)
    tokens = usage(context)
    if tokens > token_budget:
        raise ValueError("reconstructed context exceeds token budget")
    return {
        "chunks": [
            {
                "chunk_id": identifier,
                "score": candidate_scores[identifier],
                "raw_text": mapping["chunk_text"][identifier],
            }
            for identifier in ordered
        ],
        "strategy": strategy,
        "selected_chunk_ids": ordered,
        "selection_order": selected,
        "candidate_scores": candidate_scores,
        "selection_scores": selection_scores,
        "covered_claim_ids": sorted(covered),
        "claim_coverage": {"covered": len(covered), "total": len(support)},
        "covered_support": sum(support[value] for value in sorted(covered)),
        "token_usage": tokens,
        "context": context,
    }


def reconstruct_context(
    evaluation: ContextEvaluation,
    chunks: Sequence[Mapping[str, Any]],
    *,
    token_budget: int,
    strategy: str = "coverage_support",
    count_tokens: Callable[[str], int] = token_count,
) -> dict[str, Any]:
    """The default budget counts Unicode word/punctuation units, including chunk headers."""
    if type(evaluation) is not ContextEvaluation:
        raise TypeError("evaluation must be a ContextEvaluation")
    support = {claim_id(item.claim): item.support for item in evaluation.claim_support}
    mapping = map_chunks(chunks, support)
    result = select_chunks(mapping, support, token_budget, strategy, count_tokens=count_tokens)
    selected = result["selected_chunk_ids"]
    result["mapping"] = {
        "chunk_text": {identifier: mapping["chunk_text"][identifier] for identifier in selected},
        "chunk_claims": {identifier: mapping["chunk_claims"][identifier] for identifier in selected},
        "claim_chunks": {
            value: [identifier for identifier in mapping["claim_chunks"][value] if identifier in selected]
            for value in result["covered_claim_ids"]
        },
        "retrieval_order": selected,
    }
    return result
