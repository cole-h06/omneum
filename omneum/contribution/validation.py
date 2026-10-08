"""Bounded wire decoding and semantic validation of the frozen contract."""

from datetime import datetime
import json
import math
import re

from omneum.base64url import decode_unpadded
from omneum.contribution.models import EvaluationContribution

MAX_BODY_BYTES = 1_048_576
MAX_COLLECTION = 2_000
MAX_NESTED_COLLECTION = 64
COLLECTIONS = ("sources", "claims", "observations", "source_scores", "claim_scores", "dependencies")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("invalid identifier")


def unique(values):
    values = list(values)
    if len(set(values)) != len(values):
        raise ValueError("duplicate identity")
    return set(values)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def decode(body: bytes, allowed_key_versions: frozenset[int] | None = None) -> EvaluationContribution:
    # Cap bytes before JSON parsing, collection lengths before Pydantic construction.
    if type(body) is not bytes or len(body) > MAX_BODY_BYTES:
        raise ValueError("invalid body size")
    raw = json.loads(body, object_pairs_hook=_object)
    if not isinstance(raw, dict):
        raise ValueError("invalid body")
    for name in COLLECTIONS:
        items = raw.get(name)
        if not isinstance(items, list) or len(items) > MAX_COLLECTION:
            raise ValueError("invalid collection")
    for item in raw["dependencies"]:
        if not isinstance(item, dict):
            raise ValueError("invalid dependency")
        for name in ("signal_components", "qualifying_time_deltas_seconds"):
            values = item.get(name, {})
            if not isinstance(values, (dict, list)) or len(values) > MAX_NESTED_COLLECTION:
                raise ValueError("invalid nested collection")
    # JSON mode preserves the contract's strict tuple decoding.
    c = EvaluationContribution.model_validate_json(body)
    for value in (c.idempotency_key, c.evaluator_version, c.estimator_version):
        identifier(value)
    sources = unique(s.source_id for s in c.sources)
    claims = unique(s.claim_id for s in c.claims)
    versions = set()
    for items, id_attr, token_attr in ((c.sources, "source_id", "source_token"),
                                      (c.claims, "claim_id", "claim_token")):
        unique((getattr(s, token_attr), s.key_version) for s in items)
        for s in items:
            identifier(getattr(s, id_attr))
            decode_unpadded(getattr(s, token_attr), expected_length=64)
            versions.add(s.key_version)
            if allowed_key_versions is not None and s.key_version not in allowed_key_versions:
                raise ValueError("unsupported key version")
    if len(versions) > 1:
        raise ValueError("mixed key versions")
    for s in c.sources:
        identifier(s.source_kind)
    supporters = {claim: set() for claim in claims}
    for o in c.observations:
        if o.source_id not in sources or o.claim_id not in claims:
            raise ValueError("unknown observation endpoint")
        supporters[o.claim_id].add(o.source_id)
        if o.observed_bucket is not None:
            # Only UTC calendar-day buckets; never precise source timestamps.
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T00:00:00Z", o.observed_bucket):
                raise ValueError("invalid bucket")
            datetime.fromisoformat(o.observed_bucket)
    unique(s.source_id for s in c.source_scores)
    unique(s.claim_id for s in c.claim_scores)
    for s in c.source_scores:
        if s.source_id not in sources:
            raise ValueError("unknown score endpoint")
    for s in c.claim_scores:
        if s.claim_id not in claims or s.supporting_source_count != len(supporters[s.claim_id]):
            raise ValueError("inconsistent claim score")
        if s.estimated_independent_support_count > s.supporting_source_count:
            raise ValueError("inconsistent independent support")
        if s.dependency_cluster_count is not None and s.dependency_cluster_count > s.supporting_source_count:
            raise ValueError("inconsistent cluster count")
    unique((d.source_low_id, d.source_high_id) for d in c.dependencies)
    for d in c.dependencies:
        if (d.source_low_id not in sources or d.source_high_id not in sources
                or d.source_low_id >= d.source_high_id):
            raise ValueError("invalid dependency endpoints")
        for key, value in d.signal_components.items():
            identifier(key)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("invalid component")
        if any(not math.isfinite(v) or v < 0 for v in d.qualifying_time_deltas_seconds):
            raise ValueError("invalid time delta")
        if max(d.source_low_parent_count, d.source_high_parent_count, d.matching_claim_count) > 2**31 - 1:
            raise ValueError("invalid count")
    return c
