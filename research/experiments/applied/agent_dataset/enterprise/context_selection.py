import argparse
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys

from omneum import Claim, reconstruct_context

from .....adapters.observations import estimator, source_identifier, to_observations
from ..context_selection import LEGACY_STRATEGIES, TOKEN_PATTERN, claim_id, map_chunks
from ..dataset import DEPENDENCY_WEIGHTS
from .data import FIXTURES, controlled_clock
from .retrieve import api_snapshot, document, sql_records
from .workflow import run_enterprise


def load_chunks(sources, observations):
    by_claim = {
        (item.source_id, claim_id(value.claim)): item.assertion_id
        for item, value in zip(observations, to_observations(sources, observations))
    }
    now = controlled_clock()
    records_by_source = {
        "handbook": document("handbook", now),
        "faq": document("faq", now),
        "sql": sql_records(now),
        "vendor": api_snapshot(now),
    }
    chunks = []
    for source, records in records_by_source.items():
        groups = [records] if source == "faq" else [[record] for record in records]
        for group in groups:
            record = group[0]
            if source == "faq":
                identifier = record["resource_id"] + "#policy"
            elif source == "handbook":
                identifier = record["fields"]["chunk_id"]
            else:
                identifier = record["resource_id"] + "#" + record["fields"]["record_id"]
            claims = [
                claim_id(Claim("agent_dataset", "northstar_returns", value["attribute"], value["value"]))
                for value in group
            ]
            chunks.append({
                "chunk_id": identifier,
                "source_id": source,
                "resource_id": record["resource_id"],
                "observation_ids": [by_claim[source, value] for value in claims],
                "claim_ids": claims,
                "raw_text": "\n\n".join(value["raw_text"] for value in group),
            })
    return chunks


def run_experiment(token_budget=100):
    experiment = run_enterprise()
    evaluation = experiment["evaluation"]
    sources = experiment["sources"]
    labels = {source_identifier(source.source_id): source.source_id for source in sources}
    support = {claim_id(item.claim): item.support for item in evaluation.claim_support}
    chunks = load_chunks(sources, experiment["observations"])
    mapping = map_chunks(chunks, support)
    root = Path(__file__).resolve().parents[5]
    code_paths = (
        "uv.lock",
        "omneum/inference.py", "omneum/dependency.py", "omneum/engine_graph.py",
        "omneum/context_selection.py",
        "research/adapters/observations.py",
        "research/experiments/applied/agent_dataset/context_selection.py",
        "research/experiments/applied/agent_dataset/enterprise/context_selection.py",
        "research/experiments/applied/agent_dataset/enterprise/retrieve.py",
        "research/experiments/applied/agent_dataset/enterprise/agents.py",
        "research/experiments/applied/agent_dataset/enterprise/workflow.py",
        "research/experiments/applied/agent_dataset/enterprise/data.py",
        "research/experiments/applied/agent_dataset/dataset.py",
        "research/experiments/applied/agent_dataset/workflow/pipeline.py",
        "research/experiments/applied/agent_dataset/extraction/schema.py",
    )
    return {
        "configuration": {
            "experiment": "enterprise_chunk_selection_v1",
            "token_budget": token_budget,
            "token_counter": {"name": "unicode_regex_v1", "pattern": TOKEN_PATTERN},
            "token_scope": "reconstructed context including chunk headers",
            "chunking": "handbook_sections_faq_body_sql_rows_vendor_facts_v1",
            "claim_identity": "production canonical serialization in hexadecimal",
            "ranking": {
                "retrieval": "first fitting chunk in retrieval order",
                "max_support": "maximum support of distinct mapped claims",
                "mean_support": "mean support of distinct mapped claims",
                "coverage_support": "sum of support of previously uncovered claims; stop at zero gain",
            },
            "tie_break": "retrieval order",
            "reconstruction_order": "descending chunk utility; ties in retrieval order",
            "estimator": asdict(estimator(DEPENDENCY_WEIGHTS)),
            "python": sys.version.split()[0],
            "langgraph": version("langgraph"),
        },
        "code_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in code_paths
        },
        "fixture_sha256": {
            str(path.relative_to(FIXTURES)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(FIXTURES.rglob("*")) if path.is_file()
        },
        "sources": [
            {
                **source.model_dump(),
                "kind": "internal_resource",
                "identifier": source_identifier(source.source_id),
            }
            for source in sources
        ],
        "observations": [item.model_dump(mode="json") for item in experiment["observations"]],
        "observation_claim_ids": {
            item.assertion_id: claim_id(value.claim)
            for item, value in zip(
                experiment["observations"], to_observations(sources, experiment["observations"]),
            )
        },
        "convergence": asdict(evaluation.convergence),
        "source_reliability": {
            labels[item.source.identifier]: item.reliability for item in evaluation.source_reliability
        },
        "claims": {
            claim_id(item.claim): {
                "entity_namespace": item.claim.entity_namespace,
                "entity": item.claim.entity,
                "attribute": item.claim.attribute,
                "value": item.claim.value,
                "support": item.support,
                "agreement_weight": item.agreement_weight,
                "estimated_independent_support_count": item.estimated_independent_support_count,
                "dependency_signal_coverage": item.dependency_signal_coverage,
                "supporting_sources": [
                    {
                        "source_id": labels[value.source.identifier],
                        "independence": value.independence,
                        "contribution": value.contribution,
                    }
                    for value in item.supporting_sources
                ],
                "conflicting_claim_ids": [claim_id(value.claim) for value in item.conflicting_claims],
            }
            for item in evaluation.claim_support
        },
        "dependencies": [
            {
                "source_a": labels[pair.source_a.identifier],
                "source_b": labels[pair.source_b.identifier],
                "dependency": pair.dependency,
                "weighted_signal_coverage": pair.weighted_signal_coverage,
                "signals": asdict(pair.signals),
                "evidence": asdict(pair.evidence),
            }
            for pair in evaluation.pairwise_dependencies
        ],
        "chunks": [{key: value for key, value in chunk.items() if key != "raw_text"} for chunk in chunks],
        "mapping": mapping,
        "selections": [
            reconstruct_context(evaluation, chunks, token_budget=token_budget, strategy=strategy)
            for strategy in LEGACY_STRATEGIES
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-budget", type=int, default=100)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = run_experiment(arguments.token_budget)
    payload = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if arguments.output is None:
        print(payload, end="")
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        with arguments.output.open("x", encoding="utf-8") as output:
            output.write(payload)


if __name__ == "__main__":
    main()
