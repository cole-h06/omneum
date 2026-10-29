"""Deterministic local relevance for optional question-aware context selection.

Accepts normalized claims or caller-supplied local text. Passage text used for
question-aware selection stays in the SDK; this estimator does not persist it
or send it to graph inference.
"""

from collections.abc import Mapping
import json
import re


_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "for",
    "from", "has", "have", "how", "in", "is", "it", "of", "on", "or",
    "that", "the", "this", "to", "was", "what", "when", "where",
    "which", "who", "why", "with",
})


def claim_text(claim) -> str:
    """Stable lexical view of a normalized Claim (not source/evidence text)."""
    return " ".join((claim.attribute, json.dumps(
        claim.value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))


def lexical_claim_relevance(question: str | None, claims: Mapping[str, object]) -> dict[str, float]:
    """Return normalized query relevance for each claim.

    For Claim inputs, attribute/value overlap supplies 90% of the score and
    entity overlap supplies 10%. String inputs use the fraction of query terms
    present in that text. Empty/missing questions receive zero.
    """
    if question is not None and type(question) is not str:
        raise TypeError("question must be a string or None")
    if not isinstance(claims, Mapping):
        raise TypeError("claims must be a mapping")
    terms = {token for token in _WORD.findall((question or "").casefold())
             if len(token) > 1 and token not in _STOP}
    if not terms:
        return {key: 0.0 for key in claims}
    scores = {}
    for key, value in claims.items():
        if value is None:
            scores[key] = 0.0
            continue
        if type(value) is str:
            claim_terms = {token for token in _WORD.findall(value.casefold())
                           if len(token) > 1 and token not in _STOP}
            scores[key] = len(terms & claim_terms) / len(terms)
            continue
        else:
            entity_terms = {token for token in _WORD.findall(value.entity.casefold())
                            if len(token) > 1 and token not in _STOP}
            feature_text = claim_text(value)
        claim_terms = {token for token in _WORD.findall(feature_text.casefold())
                       if len(token) > 1 and token not in _STOP}
        content_terms = terms - entity_terms
        content_score = len(content_terms & claim_terms) / len(content_terms) if content_terms else 0.0
        entity_score = len(terms & entity_terms) / len(entity_terms) if entity_terms else 0.0
        scores[key] = min(1.0, 0.9 * content_score + 0.1 * entity_score)
    return scores

