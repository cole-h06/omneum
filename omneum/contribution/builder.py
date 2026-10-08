"""Allowlisted structural projection; never serialize local information objects."""
from __future__ import annotations

from typing import TYPE_CHECKING
from collections.abc import Sequence
from uuid import uuid4

from ..serialization import serialize_claim

from ..base64url import encode_unpadded
from ..canonicalization import canonicalize_source, canonicalize_entity, canonicalize_attribute, canonicalize_value
from .linkage import NetworkLinkageClient
from .config import NetworkContributionConfig
from ..information import Claim, Observation
from ..dependency import DependencyEstimatorConfig

if TYPE_CHECKING:
    from ..client import ContextEvaluation
from .models import (ContributionSource, ContributionClaim, ContributionObservation,
                     ContributionSourceScore, ContributionClaimScore,
                     ContributionDependency, EvaluationContribution)


def _source(value):
    return value.kind, canonicalize_source(value.kind, value.identifier)


def _claim(value):
    return serialize_claim(value.entity_namespace, canonicalize_entity(value.entity_namespace, value.entity),
                           canonicalize_attribute(value.attribute), canonicalize_value(value.value))


async def build_contribution(
    config: NetworkContributionConfig,
    evaluation: ContextEvaluation,
    observations: Sequence[Observation],
    estimator: DependencyEstimatorConfig,
) -> EvaluationContribution:
    # Observation is the current assertion DTO; its required Claim represents
    # the subtype. Reject future envelopes before issuing network tokens.
    for observation in observations:
        if (type(observation) is not Observation
                or observation.observation_type != "assertion"
                or type(observation.claim) is not Claim):
            raise ValueError("contributions require valid assertion observations")
    linkage = NetworkLinkageClient(config.linkage)

    async def token(blind):
        response = await config.evaluator.evaluate(
            key_version=linkage.key_version, blinded_element=blind.blinded_element,
        )
        return encode_unpadded(linkage.finalize(blind, response).value, expected_length=64)

    sources, claims = [], []
    source_ids, claim_ids = {}, {}
    for index, result in enumerate(evaluation.source_reliability):
        s = result.source
        identity = f"s{index:08d}"
        source_ids[_source(s)] = identity
        sources.append(ContributionSource(source_id=identity, source_kind=s.kind,
            source_token=await token(linkage.blind_source(s.kind, s.identifier)),
            key_version=linkage.key_version))
    for index, result in enumerate(evaluation.claim_support):
        c = result.claim
        identity = f"c{index:08d}"
        claim_ids[_claim(c)] = identity
        claims.append(ContributionClaim(claim_id=identity,
            claim_token=await token(linkage.blind_claim(c.entity_namespace, c.entity, c.attribute, c.value)),
            key_version=linkage.key_version))
    dependencies = []
    for pair in evaluation.pairwise_dependencies:
        low, high = sorted((source_ids[_source(pair.source_a)], source_ids[_source(pair.source_b)]))
        # Explicit allowlist, including directional evidence remapped to payload order.
        evidence = {}
        if pair.evidence is not None:
            e = pair.evidence
            a_is_low = source_ids[_source(pair.source_a)] == low
            a, b = ("a", "b") if a_is_low else ("b", "a")
            evidence = {
                "source_low_upstream_of_source_high": getattr(e, f"source_{a}_upstream_of_source_{b}"),
                "source_high_upstream_of_source_low": getattr(e, f"source_{b}_upstream_of_source_{a}"),
                "source_low_cites_source_high": getattr(e, f"source_{a}_cites_source_{b}"),
                "source_high_cites_source_low": getattr(e, f"source_{b}_cites_source_{a}"),
                "source_low_parent_count": getattr(e, f"source_{a}_parent_count"),
                "source_high_parent_count": getattr(e, f"source_{b}_parent_count"),
                "same_owner": e.same_owner,
                "matching_claim_count": e.matching_claim_count,
                "qualifying_time_deltas_seconds": e.qualifying_time_deltas_seconds,
            }
        signals = {f"{name}_signal": getattr(pair.signals, name)
                   if getattr(pair.signals, f"{name}_observable") else None
                   for name in ("upstream", "citation", "assertion_lineage", "ownership", "temporal", "graph", "retrieval")}
        dependencies.append(ContributionDependency(source_low_id=low, source_high_id=high,
            dependency_score=pair.dependency, signal_coverage=pair.weighted_signal_coverage, **signals, **evidence))
    return EvaluationContribution(
        idempotency_key=str(uuid4()), evaluator_version=evaluation.convergence.algorithm_version,
        estimator_version=estimator.estimator_version, sources=tuple(sources), claims=tuple(claims),
        observations=tuple(ContributionObservation(source_id=source_ids[_source(o.source)],
            claim_id=claim_ids[_claim(o.claim)]) for o in observations),
        source_scores=tuple(ContributionSourceScore(source_id=source_ids[_source(r.source)], reliability=r.reliability)
                            for r in evaluation.source_reliability),
        claim_scores=tuple(ContributionClaimScore(claim_id=claim_ids[_claim(r.claim)], support=r.support,
            supporting_source_count=r.supporting_source_count,
            estimated_independent_support_count=r.estimated_independent_support_count,
            dependency_cluster_count=None if r.dependency_clusters is None else len(r.dependency_clusters),
            dependency_signal_coverage=r.dependency_signal_coverage) for r in evaluation.claim_support),
        dependencies=tuple(dependencies),
    )
