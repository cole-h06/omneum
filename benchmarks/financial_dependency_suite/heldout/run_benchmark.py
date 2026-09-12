import argparse
import asyncio
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
from .artifacts import write_json, write_jsonl
from .loader import (
    application_candidates,
    load_case,
    load_ground_truth,
)
from .methods import METHODS
from .suite import run_case


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


async def run_benchmark(
    *,
    cases_dir=CASES_DIR,
    results_dir=RESULTS_DIR,
    trials=10,
):
    discovered = discover_cases(cases_dir)

    first_case = discovered[0][2]
    warm_local_models(
        first_case.question,
        application_candidates(first_case),
    )

    records = []

    for _, _, case, truth in discovered:
        records.extend(
            await run_case(
                case,
                truth,
                trials=trials,
                generator_provider=GENERATOR_PROVIDER,
                generator_model=GENERATOR_MODEL,
            )
        )

    identifier = run_id()
    run_dir = Path(results_dir) / identifier

    inputs = []
    for case_path, truth_path, _, _ in discovered:
        inputs.extend((case_path, truth_path))

    models = {
        method.name: method.model
        for method in METHODS
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

    summary = summarize(records)

    write_manifest(
        run_dir / "manifest.json",
        manifest_data,
    )
    write_jsonl(
        run_dir / "results.jsonl",
        records,
    )
    write_json(
        run_dir / "summary.json",
        summary,
    )

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
    args = parser.parse_args()

    if args.trials < 1:
        parser.error("--trials must be at least 1")

    run_dir = asyncio.run(
        run_benchmark(
            cases_dir=args.cases_dir,
            results_dir=args.results_dir,
            trials=args.trials,
        )
    )

    print(run_dir)


if __name__ == "__main__":
    main()
