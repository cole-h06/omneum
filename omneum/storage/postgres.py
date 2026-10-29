"""Explicit synchronous PostgreSQL persistence using a caller-installed psycopg driver."""

from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING
from uuid import UUID

from ..client import ContextEvaluation, LinkageToken
from ..canonicalization import canonicalize_source
from ..dependency import DependencyEstimatorConfig
from ..information import Claim, Observation, Source
from ..linkage import LinkagePurpose
from . import graph

if TYPE_CHECKING:
    from psycopg import Connection


from .base import EXECUTION_FIELDS, PersistedObservation, execution_values


class PostgresStorage:
    """Use a caller-owned psycopg connection against the storage migrations.

    Calls commit atomically on an idle connection; inside an existing
    transaction they use a savepoint and the caller owns the final commit.
    Evaluation persistence requires migration 003.
    Do not share a connection between concurrent operations. Token issuance remains the caller's
    responsibility, using Omneum's configured VOPRF deployment/key for the workspace.
    """

    def __init__(self, connection: "Connection") -> None:
        self.connection = connection

    def transaction(self):
        """Delegate to the caller-owned PostgreSQL transaction/savepoint boundary."""
        return self.connection.transaction()

    def persist_context(self, *, evaluation, workspace_id, occurrences,
                        source_tokens, claim_tokens, estimator) -> UUID:
        with self.transaction():
            for observation, source_token, claim_token in occurrences:
                self.persist_observation(
                    workspace_id=workspace_id, observation=observation,
                    source_token=source_token, claim_token=claim_token,
                )
            return self.persist_evaluation(
                workspace_id=workspace_id, evaluation=evaluation,
                source_tokens=source_tokens, claim_tokens=claim_tokens, estimator=estimator,
            )

    def persist_observation(
        self, *, workspace_id: UUID, observation: Observation,
        source_token: LinkageToken, claim_token: LinkageToken,
    ) -> PersistedObservation:
        """Append an occurrence, reusing workspace-scoped Source and Claim.

        Observation.observation_id is evaluation-local, not a persistent retry
        key. Each call creates a new relational Observation UUID and AGE edge.
        Only timestamps and metadata are retained from the observation. Raw
        source identifiers/claim values, lineage and dependency signals are not
        persisted by this slice. Public payload columns remain unset.
        """
        if not isinstance(workspace_id, UUID):
            raise TypeError("workspace_id must be a UUID")
        if type(observation) is not Observation or observation.observation_type != "assertion":
            raise TypeError("observation must be an Observation")
        for token, purpose in ((source_token, LinkagePurpose.SOURCE),
                               (claim_token, LinkagePurpose.CLAIM)):
            if not isinstance(token, LinkageToken) or token.purpose != purpose:
                raise ValueError(f"expected a {purpose.name} LinkageToken")
        if (source_token.deployment_id, source_token.voprf_key_version) != (
            claim_token.deployment_id, claim_token.voprf_key_version
        ):
            raise ValueError("tokens must use the same VOPRF deployment and key version")

        # Keep optional imports at the actual persistence boundary.
        from psycopg.rows import tuple_row
        from psycopg.types.json import Jsonb

        with self.connection.transaction():
            with self.connection.cursor(row_factory=tuple_row) as cursor:
                # ON CONFLICT locks reused rows through graph projection, so
                # concurrent writers cannot MERGE duplicate identity vertices.
                cursor.execute("""
                    INSERT INTO public.sources (workspace_id, source_token)
                    VALUES (%s, %s)
                    ON CONFLICT (workspace_id, source_token) DO UPDATE
                    SET source_token = EXCLUDED.source_token RETURNING id
                """, (workspace_id, source_token.value))
                source_id = cursor.fetchone()[0]
                cursor.execute("""
                    INSERT INTO public.claims (workspace_id, claim_token)
                    VALUES (%s, %s)
                    ON CONFLICT (workspace_id, claim_token) DO UPDATE
                    SET claim_token = EXCLUDED.claim_token RETURNING id
                """, (workspace_id, claim_token.value))
                claim_id = cursor.fetchone()[0]
                cursor.execute("""
                    INSERT INTO public.observations
                        (workspace_id, source_id, observation_type, observed_at,
                         source_modified_at, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                """, (workspace_id, source_id, "assertion", observation.observed_at,
                      observation.source_modified_at, Jsonb(observation.metadata)))
                observation_id = cursor.fetchone()[0]
                cursor.execute("""
                    INSERT INTO public.assertion_observations (observation_id, claim_id)
                    VALUES (%s, %s)
                """, (observation_id, claim_id))
                graph.project_observation(
                    cursor, workspace_id=workspace_id, source_id=source_id,
                    claim_id=claim_id, observation_id=observation_id,
                )
        return PersistedObservation(workspace_id, source_id, claim_id, observation_id)

    def persist_evaluation(
        self, *, workspace_id: UUID, evaluation: ContextEvaluation,
        source_tokens: Mapping[Source, LinkageToken],
        claim_tokens: Mapping[Claim, LinkageToken],
        estimator: DependencyEstimatorConfig,
    ) -> UUID:
        """Append a completed run atomically, respecting any caller transaction.

        Tokens must correspond to this result and to Sources/Claims previously
        persisted in this workspace. Pass the original estimator configuration;
        ContextEvaluation does not carry it. No evaluation or token issuance is
        performed here. Each call appends a new run (there is no public retry ID).
        Errors roll back the whole call. An existing caller transaction receives
        a savepoint and is never committed here.
        """
        if not isinstance(workspace_id, UUID):
            raise TypeError("workspace_id must be a UUID")
        if not isinstance(evaluation, ContextEvaluation):
            raise TypeError("evaluation must be a ContextEvaluation")
        if not isinstance(estimator, DependencyEstimatorConfig):
            raise TypeError("estimator must be a DependencyEstimatorConfig")
        if estimator.dependency_cluster_threshold != evaluation.dependency_cluster_threshold:
            raise ValueError("estimator threshold does not match the evaluation")

        sources = {}
        for source, token in source_tokens.items():
            if not isinstance(source, Source):
                raise TypeError("source_tokens keys must be Sources")
            key = (source.kind, canonicalize_source(source.kind, source.identifier))
            if key in sources:
                raise ValueError("duplicate canonical source in source_tokens")
            sources[key] = token
        expected_sources = {
            (item.source.kind, canonicalize_source(item.source.kind, item.source.identifier))
            for item in evaluation.source_reliability
        }
        if set(sources) != expected_sources:
            raise ValueError("source_tokens must exactly cover the evaluation sources")
        if set(claim_tokens) != {item.claim for item in evaluation.claim_support}:
            raise ValueError("claim_tokens must exactly cover the evaluation claims")
        contexts = set()
        for tokens, purpose in ((sources.values(), LinkagePurpose.SOURCE),
                                (claim_tokens.values(), LinkagePurpose.CLAIM)):
            values = set()
            for token in tokens:
                if not isinstance(token, LinkageToken) or token.purpose != purpose:
                    raise ValueError(f"expected a {purpose.name} LinkageToken")
                if token.value in values:
                    raise ValueError("distinct evaluation identities share a linkage token")
                values.add(token.value)
                contexts.add((token.deployment_id, token.voprf_key_version))
        if len(contexts) != 1:
            raise ValueError("tokens must use the same VOPRF deployment and key version")

        from psycopg.rows import tuple_row
        from psycopg.types.json import Jsonb

        with self.connection.transaction():
            with self.connection.cursor(row_factory=tuple_row) as cursor:
                # Lock existing identities in a stable order, including against
                # first-slice upserts, until all dependency projections finish.
                cursor.execute("""
                    SELECT source_token, id FROM public.sources
                    WHERE workspace_id = %s AND source_token = ANY(%s::bytea[])
                    ORDER BY id FOR UPDATE
                """, (workspace_id, [token.value for token in sources.values()]))
                source_ids = dict(cursor.fetchall())
                if len(source_ids) != len(sources):
                    raise ValueError("evaluation sources must already exist in this workspace")
                cursor.execute("""
                    SELECT claim_token, id FROM public.claims
                    WHERE workspace_id = %s AND claim_token = ANY(%s::bytea[])
                    ORDER BY id FOR KEY SHARE
                """, (workspace_id, [token.value for token in claim_tokens.values()]))
                claim_ids = dict(cursor.fetchall())
                if len(claim_ids) != len(claim_tokens):
                    raise ValueError("evaluation claims must already exist in this workspace")
                parameters = {
                    "estimator": asdict(estimator),
                    "convergence": asdict(evaluation.convergence),
                    "evaluation_latency_ms": evaluation.evaluation_latency_ms,
                }
                # The result has no wall-clock start/completion time. Do not
                # substitute persistence time for evaluation time; leave NULL.
                cursor.execute("""
                    INSERT INTO public.evaluation_runs
                        (workspace_id, algorithm, algorithm_version, status, parameters)
                    VALUES (%s, 'BRAID', %s, 'completed', %s) RETURNING id
                """, (workspace_id, evaluation.convergence.algorithm_version, Jsonb(parameters)))
                run_id = cursor.fetchone()[0]
                for item in evaluation.source_reliability:
                    key = (item.source.kind, canonicalize_source(item.source.kind, item.source.identifier))
                    cursor.execute("""
                        INSERT INTO public.source_scores
                            (workspace_id, evaluation_run_id, source_id, reliability_score)
                        VALUES (%s, %s, %s, %s)
                    """, (workspace_id, run_id, source_ids[sources[key].value], item.reliability))
                for item in evaluation.claim_support:
                    cursor.execute("""
                        INSERT INTO public.claim_scores
                            (workspace_id, evaluation_run_id, claim_id, support_score,
                             effective_independent_support, dependency_cluster_count)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (workspace_id, run_id, claim_ids[claim_tokens[item.claim].value],
                          item.support, item.estimated_independent_support_count,
                          None if item.dependency_clusters is None else len(item.dependency_clusters)))
                for pair in evaluation.pairwise_dependencies:
                    a_key = (pair.source_a.kind, canonicalize_source(pair.source_a.kind, pair.source_a.identifier))
                    b_key = (pair.source_b.kind, canonicalize_source(pair.source_b.kind, pair.source_b.identifier))
                    a, b = source_ids[sources[a_key].value], source_ids[sources[b_key].value]
                    evidence = None if pair.evidence is None else asdict(pair.evidence)
                    if a > b:
                        a, b = b, a
                        if evidence is not None:
                            # Directional evidence must follow the newly ordered
                            # endpoints even though the aggregate is symmetric.
                            for left, right in (
                                ("source_a_upstream_of_source_b", "source_b_upstream_of_source_a"),
                                ("source_a_cites_source_b", "source_b_cites_source_a"),
                                ("source_a_parent_count", "source_b_parent_count"),
                            ):
                                evidence[left], evidence[right] = evidence[right], evidence[left]
                    cursor.execute("""
                        INSERT INTO public.source_dependencies
                            (workspace_id, evaluation_run_id, source_a_id, source_b_id,
                             dependency_score, signal_coverage, components)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (workspace_id, run_id, a, b, pair.dependency,
                          pair.weighted_signal_coverage,
                          Jsonb({"signals": asdict(pair.signals), "evidence": evidence})))
                    graph.project_dependency(
                        cursor, workspace_id=workspace_id, evaluation_run_id=run_id,
                        source_a_id=a, source_b_id=b,
                    )
        return run_id

    def persist_execution(self, *, workspace_id, evaluation_run_id, execution) -> UUID:
        if not isinstance(workspace_id, UUID) or not isinstance(evaluation_run_id, UUID):
            raise TypeError("workspace and evaluation run IDs must be UUIDs")
        from psycopg.rows import tuple_row

        values = execution_values(execution)
        columns = ', '.join(EXECUTION_FIELDS)
        placeholders = ', '.join('%s' for _ in EXECUTION_FIELDS)
        with self.transaction():
            with self.connection.cursor(row_factory=tuple_row) as cursor:
                cursor.execute(
                    f'INSERT INTO public.execution_history (workspace_id, evaluation_run_id, {columns}) '
                    f'VALUES (%s, %s, {placeholders}) RETURNING id',
                    (workspace_id, evaluation_run_id, *values))
                return cursor.fetchone()[0]
