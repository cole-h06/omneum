import argparse
import asyncio
import logging
from dataclasses import asdict
from pathlib import Path

from benchmarks.financial_dependency_suite.application_comparison import (
    warm_local_models,
)
from benchmarks.financial_dependency_suite.clients import (
    DEFAULT_MODELS,
)
from benchmarks.financial_dependency_suite.reproducibility import (
    manifest,
    run_id,
    write_manifest,
)

from .aggregate import summarize
from .artifacts import checkpoint
from .checkpoint import TrialCheckpoint, implementation_hash, record_key
from .loader import (
    application_candidates,
    load_case,
    load_ground_truth,
)
from .additive_methods import ADDITIVE_METHODS, method_by_name
from .methods import METHODS
from .suite import run_case
from .cohere_cache import CohereResponseCache
from .baseline_reuse import load_anthropic_baseline


CASES_DIR = Path(__file__).parent / "cases"
RESULTS_DIR = Path(__file__).parent / "results"

GENERATOR_PROVIDER = "anthropic"
GENERATOR_MODEL = DEFAULT_MODELS[GENERATOR_PROVIDER]


def discover_cases(cases_dir):
    cases_dir = Path(cases_dir)
    discovered = []

    for directory in sorted(cases_dir.iterdir()):
        if not directory.is_dir():
            continue

        case_path = directory / "case.json"
        truth_path = directory / "ground_truth.json"

        if not case_path.exists() or not truth_path.exists():
            continue

        discovered.append(
            (
                case_path,
                truth_path,
                load_case(case_path),
                load_ground_truth(truth_path),
            )
        )

    if not discovered:
        raise RuntimeError(
            f"no benchmark cases found in {cases_dir}"
        )

    return discovered


def build_schedule(discovered, methods, trials):
    schedule = [
        (case.case_id, method.name, trial)
        for _, _, case, _ in discovered
        for method in methods
        for trial in range(1, trials + 1)
    ]
    expected = len(discovered) * len(methods) * trials
    if len(schedule) != expected or len(set(schedule)) != expected:
        raise ValueError(
            f"trial schedule cardinality mismatch: expected {expected}, got {len(schedule)} unique tuples"
        )
    return schedule


async def run_benchmark(
    *,
    cases_dir=CASES_DIR,
    results_dir=RESULTS_DIR,
    trials=10,
    identifier=None,
    resume=None,
    methods=None,
    baseline_results=None,
):
    methods = METHODS if methods is None else tuple(methods)
    if not methods:
        raise ValueError("at least one benchmark method is required")
    if trials < 1:
        raise ValueError("trials must be at least 1")
    if resume is not None and identifier is not None:
        raise ValueError("resume and identifier are mutually exclusive")
    names = {method.name for method in methods}
    if "bge_openai" in names:
        if names != {"bge_openai", "bge_omneum"}:
            raise ValueError("OpenAI pair requires exactly bge_openai and bge_omneum")
        if baseline_results is not None:
            raise ValueError("OpenAI pair cannot reuse a historical full-pool baseline")
        if GENERATOR_PROVIDER != "anthropic" or GENERATOR_MODEL != "claude-sonnet-5-5":
            raise ValueError("OpenAI pair requires Claude Sonnet 5.5 generation")
    if "bge_anthropic" in names:
        if names != {"bge_anthropic", "bge_omneum"}:
            raise ValueError("Experiment 1 requires exactly bge_anthropic and bge_omneum")
        if baseline_results is not None:
            raise ValueError("Experiment 1 cannot reuse the historical full-pool Claude baseline")
        if GENERATOR_PROVIDER != "anthropic" or GENERATOR_MODEL != "claude-sonnet-5-5":
            raise ValueError("Experiment 1 requires Claude Sonnet 5.5 generation")
    if "cohere_anthropic" in names:
        if names != {"cohere_anthropic", "cohere_omneum"}:
            raise ValueError("Experiment 2 requires exactly cohere_anthropic and cohere_omneum")
        if baseline_results is not None:
            raise ValueError("Experiment 2 cannot reuse the historical full-pool Claude baseline")
        if GENERATOR_PROVIDER != "anthropic" or GENERATOR_MODEL != "claude-sonnet-5-5":
            raise ValueError("Experiment 2 requires Claude Sonnet 5.5 generation")
    discovered = discover_cases(cases_dir)
    reused_records = {}
    baseline_reference = None
    if baseline_results is not None:
        names = {method.name for method in methods}
        if "anthropic" not in names or not names.intersection({"anthropic_omneum", "bge_omneum"}):
            raise ValueError("baseline reuse requires anthropic and either anthropic_omneum or bge_omneum")
        if trials != 1:
            raise ValueError("baseline reuse requires --trials 1")
        reused_records, baseline_reference = load_anthropic_baseline(
            baseline_results, discovered, generator_model=GENERATOR_MODEL,
        )
        if not methods or methods[0].name != "anthropic":
            raise ValueError("put anthropic first when reusing the baseline")
    identifier = identifier or (Path(resume).name if resume is not None else run_id())
    if Path(identifier).name != identifier or identifier in {".", ".."}:
        raise ValueError("identifier must be a single directory name")
    run_dir = Path(resume) if resume is not None else Path(results_dir) / identifier

    inputs = []
    for case_path, truth_path, _, _ in discovered:
        inputs.extend((case_path.resolve(), truth_path.resolve()))

    models = {
        method.name: method.model
        for method in methods
        if method.model is not None
    }
    models["generator"] = GENERATOR_MODEL

    manifest_data = manifest(
        benchmark="heldout-context-evaluation",
        track="application",
        trials=trials,
        models=models,
        inputs=inputs,
        identifier=identifier,
    )

    contract = {
        "version": 1,
        "implementation": implementation_hash(),
        "methods": [asdict(method) for method in methods],
        "generator_provider": GENERATOR_PROVIDER,
        **{key: manifest_data[key] for key in (
            "trials", "models", "inputs", "packages", "estimator", "python",
        )},
    }
    if names.intersection({"bge_anthropic", "bge_openai"}):
        pipeline = {
            "experiment": 3 if "bge_openai" in names else 1,
            "control": "bge_openai" if "bge_openai" in names else "bge_anthropic",
            "treatment": "bge_omneum",
            "relevance_model": "BAAI/bge-reranker-v2-m3",
            "shared_shortlist": "one BGE result per case/trial; IDs, order, text, and scores preserved",
            "relevance_depth": "min(candidate_pool_size, 2 * context_budget)",
            "final_context_budget": "frozen case.context_budget in both arms",
            "generator_provider": GENERATOR_PROVIDER,
            "generator_model": GENERATOR_MODEL,
            "generator_max_tokens": 1024,
            "selection_latency": "shared BGE duration plus each arm's independent judge duration",
        }
        manifest_data["selection_pipeline"] = pipeline
        contract["selection_pipeline"] = pipeline
    if "cohere_anthropic" in names:
        pipeline = {
            "experiment": 2,
            "control": "cohere_anthropic",
            "treatment": "cohere_omneum",
            "relevance_model": "rerank-v4.0-pro",
            "shared_shortlist": "one fresh Cohere result per case/trial; IDs, order, text, and scores preserved",
            "historical_rerank_reuse": False,
            "relevance_depth": "min(candidate_pool_size, 2 * context_budget)",
            "final_context_budget": "frozen case.context_budget in both arms",
            "generator_provider": GENERATOR_PROVIDER,
            "generator_model": GENERATOR_MODEL,
            "generator_max_tokens": 1024,
            "selection_latency": "shared Cohere duration plus each arm's independent judge/Omneum integration duration",
        }
        manifest_data["selection_pipeline"] = pipeline
        contract["selection_pipeline"] = pipeline
    if baseline_reference is not None:
        contract["baseline_reuse"] = baseline_reference
        manifest_data["baseline_reuse"] = baseline_reference
        manifest_data["selection_pipeline"] = {}
        if "anthropic_omneum" in names:
            manifest_data["selection_pipeline"]["anthropic_omneum"] = {
                "evaluator_provider": "local",
                "evaluator_model": "Omneum",
                "candidate_pool": "same full application_candidates pool as the Claude judge",
                "relevance_shortlist": False,
                "final_selector": "Omneum dependency-estimator-v4",
                "generator_provider": GENERATOR_PROVIDER,
                "generator_model": GENERATOR_MODEL,
            }
        if "bge_omneum" in names:
            manifest_data["selection_pipeline"]["bge_omneum"] = {
                "candidate_pool": "same full application_candidates pool as the Claude judge",
                "relevance_model": "BAAI/bge-reranker-v2-m3",
                "relevance_shortlist": True,
                "relevance_depth": "min(candidate_pool_size, 2 * context_budget)",
                "evaluator_provider": "local",
                "evaluator_model": "Omneum",
                "final_selector": "Omneum dependency-estimator-v4",
                "generator_provider": GENERATOR_PROVIDER,
                "generator_model": GENERATOR_MODEL,
            }
    manifest_data["checkpoint_contract"] = contract
    schedule = build_schedule(discovered, methods, trials)
    with TrialCheckpoint(run_dir, contract, schedule, resume=resume is not None) as progress:
        if resume is None:
            write_manifest(run_dir / "manifest.json", manifest_data)
        logging.getLogger(__name__).info("Incremental results: %s", (run_dir / "results.jsonl").resolve())
        completed = {record_key(record): record for record in progress.records}
        cohere_cache = None
        if "cohere_anthropic" not in names and any(method.method == "cohere_omneum" for method in methods):
            cohere_cache = CohereResponseCache(
                run_dir / "cohere_responses.jsonl",
                history=sorted(Path(results_dir).glob("*")), discovered=discovered,
            )
        if len(completed) < len(schedule):
            first_case = discovered[0][2]
            if any(method.method in {"bge", "vector", "bge_omneum", "bge_anthropic", "bge_openai"} for method in methods):
                warm_local_models(first_case.question, application_candidates(first_case))
            for _, _, case, truth in discovered:
                await run_case(
                    case, truth, trials=trials,
                    generator_provider=GENERATOR_PROVIDER,
                    generator_model=GENERATOR_MODEL,
                    methods=methods,
                    on_result=progress.commit,
                    completed=completed,
                    reused=reused_records,
                    **({"cohere_cache": cohere_cache} if cohere_cache is not None else {}),
                )
        checkpoint(run_dir / "summary.json", [summarize(progress.records)])

    return run_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases-dir",
        type=Path,
        default=CASES_DIR,
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_DIR,
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=10,
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=[method.name for method in (*METHODS, *ADDITIVE_METHODS)],
        help="Experiment 1: bge_anthropic bge_omneum. Experiment 2: cohere_anthropic cohere_omneum. Experiment 3: bge_openai bge_omneum.",
    )
    parser.add_argument("--baseline-results", type=Path,
                        help="reuse validated anthropic rows from a prior results.jsonl")
    continuation = parser.add_mutually_exclusive_group()
    continuation.add_argument("--run-id", dest="identifier")
    continuation.add_argument("--resume", type=Path)
    args = parser.parse_args()

    if args.trials < 1:
        parser.error("--trials must be at least 1")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    run_dir = asyncio.run(
        run_benchmark(
            cases_dir=args.cases_dir,
            results_dir=args.results_dir,
            trials=args.trials,
            identifier=args.identifier,
            resume=args.resume,
            methods=(tuple(map(method_by_name, args.methods)) if args.methods else None),
            baseline_results=args.baseline_results,
        )
    )

    print(run_dir)


if __name__ == "__main__":
    main()
