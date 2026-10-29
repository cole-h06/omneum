import json
import hashlib
from datetime import datetime
from pathlib import Path

from omneum import Claim, Observation, Source, SourceReference
from omneum.canonicalization import canonicalize_source

from .schema import (
    AnswerScoring,
    BenchmarkCase,
    CandidateSpec,
    ClaimSpec,
    GroundTruth,
    ProvenanceSpec,
    SourceSpec,
)


# Frozen benchmark source kinds describe artifact roles, not SDK transport kinds.
# These roles identify URL-backed documents. Keep SourceSpec unchanged so the
# original role remains available, and use the same conversion for every edge.
_WEB_DOCUMENT_ROLES = frozenset({
    "analysis",
    "analyst_agent",
    "announcement",
    "api_result",
    "archived_handbook",
    "change_record",
    "changelog",
    "ci_config",
    "code_agent",
    "confluence_page",
    "current_api_docs",
    "current_docs",
    "current_policy",
    "current_query",
    "current_runbook",
    "dashboard",
    "dashboard_snapshot",
    "data_agent",
    "data_catalog",
    "database_result",
    "dataset",
    "deployment_config",
    "derived_table",
    "drive_document",
    "email",
    "email_summary",
    "example",
    "example_config",
    "exported_dataset",
    "exported_report",
    "filing",
    "finance_report",
    "hr_record",
    "hr_system",
    "incident_record",
    "independent_report",
    "integration_test",
    "kb_article",
    "manager_note",
    "metric_docs",
    "metric_store",
    "migration_guide",
    "monitoring_result",
    "news_article",
    "old_api_docs",
    "old_example",
    "old_runbook",
    "old_team_page",
    "operations_agent",
    "operations_doc",
    "original_report",
    "package_metadata",
    "policy",
    "policy_changelog",
    "policy_record",
    "primary_publication",
    "primary_record",
    "project_doc",
    "publication",
    "query_result",
    "readme",
    "release_notes",
    "report",
    "repository_code",
    "researcher_agent",
    "reviewer_agent",
    "runbook",
    "semantic_layer",
    "service_state",
    "slack_message",
    "source_code",
    "source_table",
    "specialist_agent",
    "summary_agent",
    "system_record",
    "team_wiki",
    "test_output",
    "ticket",
    "tool_result",
    "transformation",
    "unit_test",
    "verifier_agent",
    "warehouse_query",
    "warehouse_table",
    "web_page",
    "web_result",
})


def _omneum_source(spec, source_type):
    kind = "web_document" if spec.kind in _WEB_DOCUMENT_ROLES else spec.kind
    # Validate at the adapter boundary; unknown roles and invalid identifiers
    # must still fail under the SDK's unmodified canonical source contract.
    canonicalize_source(kind, spec.identifier)
    return source_type(kind, spec.identifier)


def _datetime(value):
    if value is None:
        return None

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _source(data):
    return SourceSpec(
        kind=data["kind"],
        identifier=data["identifier"],
    )


def _references(values):
    return tuple(_source(value) for value in values)


def load_case(path):
    path = Path(path)
    data = json.loads(path.read_text())

    candidates = []

    for item in data["candidates"]:
        provenance = item["provenance"]
        claims = []
        fields = ('entity_namespace', 'entity', 'attribute', 'value')
        if 'claims' in item:
            if any(k in item for k in fields):
                raise ValueError('candidate must use claims or legacy claim fields, not both')
            if type(item['claims']) is not list or not item['claims']:
                raise ValueError('claims must be a nonempty list')
            for index, record in enumerate(item['claims']):
                if type(record) is not dict or not set(fields) <= record.keys():
                    raise ValueError('claim requires the four structured claim fields')
                if any(type(record[k]) is not str or not record[k].strip() for k in fields[:3]):
                    raise ValueError('claim identities must be nonempty strings')
                oid = record.get('observation_id', provenance['assertion_id'] +
                                 ('' if index == 0 else ':claim:' + str(index + 1)))
                if type(oid) is not str or not oid.strip():
                    raise ValueError('claim observation ID must be a nonempty string')
                if index == 0 and oid != provenance['assertion_id']:
                    raise ValueError('first claim must retain the original assertion ID')
                evidence = record.get('evidence', [])
                if type(evidence) is not list:
                    raise ValueError('claim evidence must be a list')
                for span in evidence:
                    if (type(span) is not dict or not {'source_id', 'start', 'end', 'text'} <= span.keys()
                            or span['source_id'] != item['source_id']
                            or type(span['start']) is not int or type(span['end']) is not int
                            or not 0 <= span['start'] < span['end'] <= len(item['text'])
                            or item['text'][span['start']:span['end']] != span['text']):
                        raise ValueError('claim evidence must match its original passage')
                catalog_id = record.get('claim_id')
                if catalog_id is not None:
                    encoded = json.dumps({k:record[k] for k in fields},sort_keys=True,
                                         separators=(',', ':'),ensure_ascii=False,allow_nan=False)
                    if catalog_id != 'sha256:' + hashlib.sha256(encoded.encode()).hexdigest():
                        raise ValueError('canonical claim ID does not match its fields')
                claims.append(ClaimSpec(*(record[k] for k in fields), oid,
                                        catalog_id, tuple(evidence)))

        candidates.append(
            CandidateSpec(
                source_id=item["source_id"],
                source=_source(item["source"]),
                text=item["text"],
                entity_namespace=None if claims else item["entity_namespace"],
                entity=None if claims else item["entity"],
                attribute=None if claims else item["attribute"],
                value=None if claims else item["value"],
                provenance=ProvenanceSpec(
                    assertion_id=provenance["assertion_id"],
                    observed_at=_datetime(
                        provenance["observed_at"]
                    ),
                    source_modified_at=_datetime(
                        provenance.get("source_modified_at")
                    ),
                    upstream_sources=_references(
                        provenance.get("upstream_sources", [])
                    ),
                    cited_sources=_references(
                        provenance.get("cited_sources", [])
                    ),
                    parent_assertion_ids=tuple(
                        provenance.get(
                            "parent_assertion_ids",
                            [],
                        )
                    ),
                ),
                claims=tuple(claims),
            )
        )

    ids = [claim.observation_id for candidate in candidates for claim in candidate.claims]
    ids.extend(c.provenance.assertion_id for c in candidates if not c.claims)
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate claim observation ID')

    return BenchmarkCase(
        case_id=data["id"],
        domain=data["domain"],
        question=data["question"],
        context_budget=data["context_budget"],
        candidates=tuple(candidates),
        category=data.get("category"),
        adversarial_category=data.get("adversarial_category"),
    )


def load_ground_truth(path):
    path = Path(path)
    data = json.loads(path.read_text())

    scoring = data["scoring"]

    return GroundTruth(
        case_id=data["case_id"],
        answer=data["answer"],
        supporting_sources=tuple(
            data["supporting_sources"]
        ),
        scoring=AnswerScoring(
            required=tuple(scoring["required"]),
            forbidden=tuple(scoring.get("forbidden", [])),
        ),
    )


def _omneum_entity(namespace, entity):
    """Losslessly transport a benchmark identity through the service profile.

    Benchmark namespaces are semantic labels, not SDK canonicalization profiles.
    Encode the entire pair, so namespace boundaries, case, whitespace and Unicode
    spelling survive service canonicalization. See ADAPTER.md for the contract.
    """
    for name, value in (("entity_namespace", namespace), ("entity", entity)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a nonempty string")
    identity = json.dumps([namespace, entity], ensure_ascii=True, separators=(",", ":"))
    return "service", "heldout-entity-v1:" + identity.encode("ascii").hex()


def build_observations(case):
    # One maintained boundary for legacy singletons and canonical multi-claims.
    from .sdk_adapter import build_observations as adapt
    return adapt(case)


def application_candidates(case):
    return [
        {
            "source": candidate.source_id,
            "text": candidate.text,
        }
        for candidate in case.candidates
    ]
