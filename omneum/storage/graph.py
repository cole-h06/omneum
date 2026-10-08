"""Minimal AGE projection. Only authoritative relational UUIDs enter AGE."""

import json
from uuid import UUID


_PROJECT = """
SELECT * FROM ag_catalog.cypher('omneum_context', $$
    MERGE (s:Source {id: $source_id, workspace_id: $workspace_id})
    MERGE (c:Claim {id: $claim_id, workspace_id: $workspace_id})
    CREATE (s)-[o:OBSERVED {id: $observation_id, workspace_id: $workspace_id}]->(c)
    RETURN o.id
$$, %s::ag_catalog.agtype) AS (id ag_catalog.agtype)
"""


def project_observation(cursor, *, workspace_id: UUID, source_id: UUID,
                        claim_id: UUID, observation_id: UUID) -> None:
    """Project inside the caller's transaction, after locking Source and Claim."""
    cursor.execute("""
        SELECT o.source_id, a.claim_id FROM public.observations o
        JOIN public.assertion_observations a ON a.observation_id=o.id
        WHERE o.id=%s AND o.workspace_id=%s AND o.observation_type='assertion'
    """, (observation_id, workspace_id))
    if cursor.fetchone() != (source_id, claim_id):
        raise ValueError("AGE projection requires a valid assertion subtype")
    cursor.execute("LOAD 'age'")
    cursor.execute("SELECT current_setting('search_path')")
    search_path = cursor.fetchone()[0]
    cursor.execute("SET LOCAL search_path = ag_catalog, pg_catalog, public")
    parameters = json.dumps({
        "workspace_id": str(workspace_id),
        "source_id": str(source_id),
        "claim_id": str(claim_id),
        "observation_id": str(observation_id),
    })
    # AGE requires a prepared statement for its Cypher parameter map.
    cursor.execute(_PROJECT, (parameters,), prepare=True)
    if cursor.fetchone() is None:
        raise RuntimeError("AGE did not project the observation")
    cursor.execute("SELECT set_config('search_path', %s, true)", (search_path,))


_PROJECT_DEPENDENCY = """
SELECT * FROM ag_catalog.cypher('omneum_context', $$
    MERGE (a:Source {id: $source_a_id, workspace_id: $workspace_id})
    MERGE (b:Source {id: $source_b_id, workspace_id: $workspace_id})
    MERGE (a)-[d:DEPENDENT {evaluation_run_id: $evaluation_run_id,
                           workspace_id: $workspace_id}]->(b)
    RETURN d.evaluation_run_id
$$, %s::ag_catalog.agtype) AS (id ag_catalog.agtype)
"""


def project_dependency(cursor, *, workspace_id: UUID, evaluation_run_id: UUID,
                       source_a_id: UUID, source_b_id: UUID) -> None:
    """Project a persisted canonical pair; query DEPENDENT without direction.

    Endpoints plus evaluation_run_id join to the relational composite PK. The
    caller holds the run and Source row locks. MERGE is safe to repeat under
    those locks. Direction encodes UUID ordering, not causal provenance.
    """
    if source_a_id >= source_b_id:
        raise ValueError("dependency UUIDs must be canonically ordered")
    cursor.execute("LOAD 'age'")
    cursor.execute("SELECT current_setting('search_path')")
    search_path = cursor.fetchone()[0]
    cursor.execute("SET LOCAL search_path = ag_catalog, pg_catalog, public")
    parameters = json.dumps({
        "workspace_id": str(workspace_id),
        "evaluation_run_id": str(evaluation_run_id),
        "source_a_id": str(source_a_id),
        "source_b_id": str(source_b_id),
    })
    cursor.execute(_PROJECT_DEPENDENCY, (parameters,), prepare=True)
    if cursor.fetchone() is None:
        raise RuntimeError("AGE did not project the dependency")
    cursor.execute("SELECT set_config('search_path', %s, true)", (search_path,))
