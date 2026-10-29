import argparse
import json
import logging
import sys
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator
from typing import Any
from contextlib import contextmanager, nullcontext, redirect_stdout

from omneum.metrics import HumanExecutionFormatter, JsonExecutionFormatter
from .context_preparation import GenerationInput, PreparationOptions


def selection_summary(generation: GenerationInput, result: dict[str, Any] | None = None) -> dict[str, Any]:
    chunks = generation["retrieved_chunks"]
    if result is None:
        packet = generation["prepared_context"]
        identifiers = packet["packed_chunk_ids"]
        selection = packet["selection"]
        covered = sorted({claim for chunk in chunks if chunk["chunk_id"] in identifiers
                          for claim in chunk["claim_ids"]})
        usage, budget, coverage = (selection["selected_tokens"], selection["token_budget"],
                                  selection["claim_coverage"])
    else:
        identifiers = result["selected_chunk_ids"]
        covered = result["covered_claim_ids"]
        usage, budget, coverage = result["token_usage"], result["token_budget"], result["claim_coverage"]
    return {"selected_chunk_ids": list(identifiers), "rendering_order": list(identifiers),
            "token_usage": usage, "token_budget": budget, "claim_coverage": coverage,
            "covered_claim_ids": covered,
            "excluded_chunk_ids": [chunk["chunk_id"] for chunk in chunks if chunk["chunk_id"] not in identifiers]}


def format_comparison(generation: GenerationInput) -> str:
    if generation["comparison"] is None:
        raise ValueError("comparison was not requested")
    rows = generation["structural_evaluation"]
    duplicates = Counter(row["attribute"] for row in rows)
    labels = [row["attribute"] + (" = " + json.dumps(row["value"], ensure_ascii=False)
              if duplicates[row["attribute"]] > 1 else "") for row in rows]
    claim_labels = {row["claim_id"]: label for row, label in zip(rows, labels, strict=True)}
    width = max((len(label) for label in labels), default=0) + 1
    lines = ["Structural evaluation (all retrieved evidence)"]
    for row, label in zip(rows, labels, strict=True):
        lines.append(f"  {label + ':':<{width}} {row['supporting_source_count']} sources, "
                     f"{row['estimated_independent_support']:.2f} estimated independent support")
    for label, result in (("Raw RAG", generation["comparison"]["raw_rag"]), ("Omneum", None)):
        selected = selection_summary(generation, result)
        coverage = selected["claim_coverage"]
        covered = ", ".join(claim_labels[identifier] for identifier in selected["covered_claim_ids"]) or "none"
        lines.extend(("", label,
            "  Selected (rendering order): " + (", ".join(selected["rendering_order"]) or "none"),
            f"  Token usage: {selected['token_usage']}/{selected['token_budget']}",
            f"  Claim coverage: {coverage['covered']}/{coverage['total']} ({covered})",
            "  Excluded: " + (", ".join(selected["excluded_chunk_ids"]) or "none")))
    return "\n".join(lines)


def inspection_record(generation: GenerationInput, framework: str, *, include_context: bool = False) -> dict[str, Any]:
    packet = generation["prepared_context"]
    summary = selection_summary(generation)
    result = {
        "framework": framework, "query": generation["question"],
        "configuration": generation["configuration"],
        "retrieved_chunk_ids": [chunk["chunk_id"] for chunk in generation["retrieved_chunks"]],
        **summary, "selection": packet["selection"],
        "reduction_ratio": packet["selection"]["reduction_ratio"],
        "structural_evaluation": [{key: value for key, value in row.items() if key != "value"}
                                  for row in generation["structural_evaluation"]],
        "evaluation": packet["evaluation"], "selection_diagnostics": generation["query_diagnostics"],
        "evaluation_run_id": generation["evaluation"].evaluation_run_id,
    }
    if "telemetry" in packet:
        result["telemetry"] = packet["telemetry"]
    if generation["comparison"] is not None:
        result["comparison"] = {
            "raw_rag": selection_summary(generation, generation["comparison"]["raw_rag"]),
            "omneum": summary,
        }
    if include_context:
        result.update(context=packet["context"], chunks=packet["chunks"], messages=generation["messages"])
        if generation["comparison"] is not None:
            result["comparison"]["raw_rag"]["context"] = generation["comparison"]["raw_rag"]["context"]
            result["comparison"]["omneum"] = {**summary, "context": packet["context"]}
    json.dumps(result, allow_nan=False)
    return result


def print_routing_status(scenario, initial_count, observations, history, retries, evaluation):
    print(f"\n=== {scenario} ===")
    print(f"Observations: {initial_count} -> {len(observations)}")
    print("Routing: " + " -> ".join(history))
    print(f"Retries: {retries}")
    print("\nClaim support:")
    for item in sorted(evaluation.claim_support, key=lambda item: (item.claim.attribute, -item.support)):
        print(f"  {item.claim.attribute}: {item.claim.value} | support={item.support:.4f}"
              f" | independent={item.estimated_independent_support_count:.3f}")


def parser(*, routing: bool = False) -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--token-budget", type=int, default=600,
                        help="Unicode word/punctuation units, including context headers; excludes prompt overhead")
    result.add_argument("--compare", action="store_true")
    result.add_argument("--json", action="store_true")
    result.add_argument("--include-context", action="store_true", help="include original evidence and model messages in JSON")
    result.add_argument("--inspect-context", action="store_true")
    result.add_argument("--include-telemetry", action="store_true")
    result.add_argument("--collect-telemetry", action="store_true")
    result.add_argument("--telemetry-format", choices=("json", "human"), default="json")
    result.add_argument("--telemetry-log-file")
    if routing:
        result.add_argument("--scenario", choices=("diversify_sources", "retrieve_support", "resolve_conflicts", "all"), default="all")
    return result


@contextmanager
def execution_logging(args: argparse.Namespace) -> Iterator[None]:
    if not args.collect_telemetry:
        if args.telemetry_log_file:
            raise ValueError("--telemetry-log-file requires --collect-telemetry")
        yield
        return
    logger = logging.getLogger("omneum.execution")
    handler = logging.FileHandler(args.telemetry_log_file, encoding="utf-8") if args.telemetry_log_file else logging.StreamHandler(sys.stderr)
    handler.setFormatter(HumanExecutionFormatter() if args.telemetry_format == "human" else JsonExecutionFormatter())
    previous_level, previous_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        yield
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


async def run_cli(
    framework: str,
    execute: Callable[[PreparationOptions, argparse.Namespace, str | None], Awaitable[tuple[GenerationInput | None, str | None]]],
    *, routing: bool = False, debug_json: bool = False,
) -> None:
    args = parser(routing=routing).parse_args()
    args.json = args.json or debug_json
    options = PreparationOptions(args.token_budget, args.compare, args.include_telemetry, args.collect_telemetry)
    args.inspect_context = args.inspect_context or args.json or args.compare
    scenarios = ("diversify_sources", "retrieve_support", "resolve_conflicts") if routing and args.scenario == "all" else (args.scenario if routing else None,)
    records = []
    with execution_logging(args):
        for scenario in scenarios:
            # Framework progress output must not contaminate a JSON document.
            with redirect_stdout(sys.stderr) if args.json or args.compare else nullcontext():
                generation, answer = await execute(options, args, scenario)
            if generation is None:
                record = {"framework": framework, "scenario": scenario, "outcome": answer}
                if not args.json:
                    print(answer)
            else:
                record = inspection_record(generation, framework, include_context=args.include_context)
                if scenario is not None:
                    record["scenario"] = scenario
                if options.compare:
                    print(format_comparison(generation), file=sys.stderr)
                if not args.json and not options.compare:
                    print(answer if answer is not None else generation["messages"][1]["content"])
            records.append(record)
    if args.json:
        print(json.dumps({"framework": framework, "scenarios": records} if routing else records[0],
                         indent=2, allow_nan=False))
