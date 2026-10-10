"""Offline dashboard contract tests; no selector execution or provider imports."""
from copy import deepcopy
import hashlib
from pathlib import Path
import json
import math
import re
import statistics
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator, ValidationError

from ..paths import resolve_artifact

from .build_dashboard_summary import (
    BASE, OUTPUT, ROOT, RUN, SCHEMA, build_summary, selection_metrics,
    validate_pairing, build_verified_gemini_summary,
)


@pytest.fixture(scope="module")
def data():
    return build_verified_gemini_summary()


@pytest.fixture(scope="module")
def raw():
    return [json.loads(line) for line in (BASE/"results"/RUN/"results.jsonl").read_text().splitlines()]


def test_schema_and_deterministic_artifact(data):
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(schema)
    full = build_summary()
    Draft202012Validator(schema).validate(full)
    assert OUTPUT.read_text() == json.dumps(full, indent=2, allow_nan=False) + "\n"


@pytest.mark.parametrize("field,value", [("rate", 1.01), ("rate", -0.01), ("count", -1)])
def test_schema_rejects_invalid_rates_and_counts(data, field, value):
    bad = build_summary()
    bad["configurations"][0]["outcomes"]["incorrect"][field] = value
    with pytest.raises(ValidationError):
        Draft202012Validator(json.loads(SCHEMA.read_text())).validate(bad)


def test_families_are_pipeline_labels_not_standalone(data):
    g, o = data["configurations"]
    assert [g["label"], o["label"]] == ["BGE + Gemini", "BGE + Omneum"]
    assert g["method_families"] == ["semantic_reranker", "frontier_llm_judge"]
    assert o["method_families"] == ["semantic_reranker"]
    assert g["configuration_kind"] == "baseline"
    assert o["configuration_kind"] == "omneum_augmented"
    assert o["augmentation_target"] == "bge" and o["baseline_configuration_id"] is None
    assert all(c["execution_shape"] == "pipeline" for c in (g, o))
    assert all(c["components"][0]["model"] == "BAAI/bge-reranker-v2-m3" for c in (g, o))


def test_schema_accepts_additional_measured_configuration_and_nulls(data):
    future = build_summary()
    c = deepcopy(future["configurations"][1])
    c.update(id="omneum_future_run", label="Standalone Omneum", method_families=["standalone_omneum"],
             configuration_kind="baseline", execution_shape="standalone", augmentation_target=None)
    c["components"] = c["components"][1:]
    c["outcomes"]["incorrect"] = {"count": None, "rate": None}
    c["selection"]["macro"]["f1"] = None
    c["latency_seconds"]["selection"]["p95"] = None
    c["cost_usd"]["estimated_api_total"] = None
    future["configurations"].append(c)
    Draft202012Validator(json.loads(SCHEMA.read_text())).validate(future)
    c["execution_shape"] = "pipeline"
    with pytest.raises(ValidationError):
        Draft202012Validator(json.loads(SCHEMA.read_text())).validate(future)


def test_outcome_denominators_and_published_accuracy(data):
    for c, correct, incomplete, incorrect in zip(data["configurations"], (229, 220), (1, 0), (0, 10)):
        assert c["attempts"] == c["case_count"] * c["trials_per_case"] == 240
        outcomes = c["outcomes"]
        assert sum(v["count"] for v in outcomes.values()) == c["attempts"]
        assert sum(v["rate"] for v in outcomes.values()) == pytest.approx(1)
        assert outcomes["complete_answer_accuracy"]["count"] == correct
        assert outcomes["incomplete"]["count"] == incomplete
        assert outcomes["incorrect"]["count"] == incorrect
        assert outcomes["generator_refusal"]["count"] == 10
        for v in outcomes.values():
            assert v["rate"] == v["count"]/240


def test_selection_f1_is_mean_per_attempt_not_harmonic_macro_means():
    rows = [{"selection_score": dict(true_positive=1, false_positive=0, false_negative=3, precision=1, recall=.25)},
            {"selection_score": dict(true_positive=1, false_positive=1, false_negative=0, precision=.5, recall=1)}]
    s = selection_metrics(rows)
    assert s["macro"]["f1"] == pytest.approx((.4+2/3)/2)
    assert s["macro"]["f1"] != pytest.approx(2*.75*.625/(.75+.625))
    assert s["micro"] == pytest.approx(dict(precision=2/3, recall=2/5, f1=.5))


def test_selection_zero_denominator_definition():
    rows = [{"selection_score": dict(true_positive=0, false_positive=0, false_negative=0, precision=0, recall=0)}]
    assert selection_metrics(rows)["micro"] == dict(precision=0, recall=0, f1=0)
    assert selection_metrics(rows)["macro"]["f1"] == 0


def test_selection_denominators_against_case_labels(data, raw):
    for c in data["configurations"]:
        rr = [r for r in raw if r["method"] == c["id"]]
        tp = fp = fn = 0
        f1s = []
        for r in rr:
            truth = json.loads((BASE/"cases"/r["case_id"]/"ground_truth.json").read_text())
            wanted, chosen = set(truth["supporting_sources"]), set(r["selected"])
            a, b, d = len(wanted & chosen), len(chosen-wanted), len(wanted-chosen)
            tp += a; fp += b; fn += d
            f1s.append(2*a/(2*a+b+d))
        assert c["selection"]["counts"] == dict(true_positive=tp, false_positive=fp, false_negative=fn)
        assert c["selection"]["micro"] == pytest.approx(dict(precision=tp/(tp+fp), recall=tp/(tp+fn), f1=2*tp/(2*tp+fp+fn)))
        assert c["selection"]["macro"]["f1"] == statistics.mean(f1s)


def assert_readme_tables(readme, catalogue):
    """README columns declare generator-only usage, with row-specific pairing."""
    assert "Costs reflect estimated downstream generator API usage only" in readme
    configs = {c["id"]: c for c in catalogue["configurations"]}
    labels = {
        "bge": "BGE Reranker v2-m3", "cohere": "Cohere Rerank v4.0 Pro",
        "bge_omneum": "BGE + Omneum", "cohere_omneum": "Cohere + Omneum",
        "bge_anthropic": "BGE + Claude Sonnet 5.5 Judge",
        "bge_openai": "BGE + GPT-6 Astra Judge", "bge_google": "BGE + Gemini 3.8 Flash Judge",
    }
    for heading, family in (("Semantic Rerankers", "semantic_rerankers"),
                            ("Frontier LLM Judges", "frontier_llm_judges")):
        section = readme.split(f"### {heading}\n", 1)[1].split("\n##", 1)[0]
        assert "Generator Tokens" in section and "Generator Cost" in section
        displayed = []
        for line in section.splitlines():
            if line.startswith("|"):
                cells = [cell.strip().replace("**", "") for cell in line.strip("|").split("|")]
                if len(cells) == 8 and "%" in cells[1]:
                    displayed.append(cells)
        rows = catalogue["publication"]["tables"][family]
        if family == "frontier_llm_judges":
            # This README publishes the three BGE judge pairs; Cohere's judge
            # pair remains separately available in the full dashboard.
            rows = [row for row in rows if configs[row["configuration_id"]]["method_id"].startswith("bge")]
        assert len(displayed) == len(rows)
        for cells, row in zip(displayed, rows):
            config = configs[row["configuration_id"]]
            assert cells[0] == labels[config["method_id"]]
            assert cells[1:4] == [f"{row[field]:.2%}" for field in ("precision", "recall", "accuracy")]
            for cell, field in zip(cells[4:6], ("selection_p50_seconds", "end_to_end_p50_seconds")):
                match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ms|s)", cell)
                assert match, cell
                number, unit = match.groups()
                decimals = len(number.split(".")[1]) if "." in number else 0
                scale = 1000 if unit == "ms" else 1
                assert float(number) == round(row[field] * scale, decimals)
            assert int(cells[6].replace(",", "")) == config["api_tokens"]["generation"]["total"]
            assert float(cells[7].removeprefix("$")) == pytest.approx(config["cost_usd"]["generation"], abs=0.0000005)


def test_units_percentiles_and_published_metrics(data, raw, catalogue):
    saved = json.loads((BASE/"analysis"/RUN/"comparison.json").read_text())["aggregates"]
    assert data["units"] == dict(rates="fraction", latency="seconds", api_tokens="provider_tokens", cost="USD")
    readme = (ROOT/"README.md").read_text()
    for c in data["configurations"]:
        a = saved[c["id"]]
        assert c["selection"]["macro"]["precision"] == a["precision"]
        assert c["selection"]["macro"]["recall"] == a["recall"]
        rr = [r for r in raw if r["method"] == c["id"]]
        for stage in ("selection", "end_to_end"):
            values = sorted(r["selection"]["latency_seconds"] if stage == "selection" else r["end_to_end_latency_seconds"] for r in rr)
            for name, q in (("p50", .5), ("p95", .95)):
                p = (len(values)-1)*q
                expected = values[math.floor(p)]*(1-p%1)+values[math.ceil(p)]*(p%1)
                assert c["latency_seconds"][stage][name] == pytest.approx(expected)
    assert_readme_tables(readme, catalogue)


@pytest.mark.parametrize("old,new", [("112,349", "406,605"), ("$0.669282", "$1.553232")])
def test_readme_generator_columns_reject_whole_pipeline_metrics(catalogue, old, new):
    readme = (ROOT / "README.md").read_text()
    assert old in readme
    with pytest.raises(AssertionError):
        assert_readme_tables(readme.replace(old, new), catalogue)


def test_tokens_cost_and_unavailable_measurements(data, raw):
    rates = data["pricing"]["usd_per_million"]
    for c in data["configurations"]:
        rr = [r for r in raw if r["method"] == c["id"]]
        sel, gen, total = (c["api_tokens"][s] for s in ("selection", "generation", "total"))
        assert gen["reasoning"] is None and total["reasoning"] is None
        assert c["local_reranker_tokens"] is None
        assert c["cost_usd"]["invoiced_api_total"] is None and c["cost_usd"]["local_compute_total"] is None
        for stage in (sel, gen, total):
            assert stage["total"] == stage["input"]+stage["output"]
        assert total["total"] == sel["total"]+gen["total"]
        assert total["input"] == sum(r["selection"]["evaluator_input_tokens"]+r["generation"]["input_tokens"] for r in rr)
        thinking = sum(r["selection"].get("response_diagnostics", {}).get("usage_metadata", {}).get("thoughts_token_count", 0) for r in rr)
        assert sel["reasoning"] == thinking
        assert sel["output"] == sum(r["selection"]["evaluator_output_tokens"] for r in rr)+thinking
        cost = (sel["input"]*rates["gemini_input"]+sel["output"]*rates["gemini_visible_plus_thinking_output"]+gen["input"]*rates["sonnet_input"]+gen["output"]*rates["sonnet_output"])/1e6
        assert c["cost_usd"]["estimated_api_total"] == pytest.approx(cost)
        assert c["cost_usd"]["estimated_api_per_answer"] == pytest.approx(cost/240)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "shortlist", "budget", "generator"])
def test_rejects_broken_pairing(raw, mutation):
    rows = deepcopy(raw)
    if mutation == "missing": rows.pop()
    elif mutation == "duplicate": rows.append(deepcopy(rows[0]))
    elif mutation == "shortlist": rows[10]["selection"]["bge_relevance"]["selected"].pop()
    elif mutation == "budget": rows[10]["selection"]["context_budget"] += 1
    elif mutation == "generator": rows[10]["generation"]["model"] = "other"
    with pytest.raises(ValueError):
        validate_pairing(rows, sorted({r["case_id"] for r in raw}), 10)


def test_rebuild_preserves_sources_and_read_only_check(data):
    files = {p: digest for p, digest in data["source_file_sha256"].items()}
    result = subprocess.run([sys.executable, "-m", "benchmarks.context_evaluation.heldout.build_dashboard_summary", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert all(hashlib.sha256(resolve_artifact(p, expected_sha256=digest).read_bytes()).hexdigest() == digest for p, digest in files.items())


def test_cli_rejects_historical_output_path():
    target = BASE/"analysis"/RUN/"report.md"
    before = target.read_bytes()
    result = subprocess.run([sys.executable, "-m", "benchmarks.context_evaluation.heldout.build_dashboard_summary", "--output", str(target)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode != 0
    assert target.read_bytes() == before


@pytest.fixture(scope="module")
def catalogue():
    return build_summary()


def test_entire_directory_inventory_and_complete_schedules(catalogue):
    folders = {p.name for p in (BASE/"results").iterdir() if p.is_dir()}
    inventory = {r["id"]: r for r in catalogue["runs"]}
    assert set(inventory) == folders
    assert {r["id"] for r in catalogue["analyses"]} == {p.name for p in (BASE/"analysis").iterdir() if p.is_dir()}
    configurations = {c["id"]: c for c in catalogue["configurations"]}
    assert len(configurations) == len(catalogue["configurations"])
    for r in inventory.values():
        if r["status"] != "completed":
            assert r["configuration_ids"] == []
            continue
        rows = [json.loads(l) for l in (BASE/"results"/r["id"]/"results.jsonl").read_text().splitlines()]
        assert len(rows) == r["verification"]["expected_records"]
        assert r["verification"]["missing_records"] == 0
        for cid in r["configuration_ids"]:
            c = configurations[cid]
            assert c["attempts"] == c["case_count"]*c["trials_per_case"]
            assert c["attempts"] == sum(row["method"]==c["method_id"] for row in rows)


def test_all_publication_methods_present(catalogue):
    methods = {c["method_id"] for c in catalogue["configurations"]}
    assert methods == {"bge", "cohere", "bge_omneum", "cohere_omneum",
                       "bge_anthropic", "cohere_anthropic", "bge_openai", "bge_google"}
    assert len([r for r in catalogue["runs"] if r["status"] == "completed"]) == 6
    assert len(catalogue["configurations"]) == 12


def test_both_leaderboard_families_preserve_hybrid_and_comparator_identity(catalogue):
    by = {c["id"]:c for c in catalogue["configurations"]}
    for name, family in (("semantic_rerankers","semantic_reranker"),("frontier_llm_judges","frontier_llm_judge")):
        board = catalogue["leaderboards"][name]
        assert board["configuration_ids"]
        assert all(family in by[cid]["method_families"] or cid in board["comparator_configuration_ids"] for cid in board["configuration_ids"])
        assert all(by[cid]["publication_status"]=="authoritative" for cid in board["configuration_ids"])
        assert all("standalone_omneum" in by[cid]["method_families"] for cid in board["reference_configuration_ids"])
        assert all(by[cid]["configuration_kind"]=="omneum_augmented" for cid in board["comparator_configuration_ids"])
    assert "bge_google" in catalogue["leaderboards"]["frontier_llm_judges"]["configuration_ids"]
    assert "bge_omneum" in catalogue["leaderboards"]["frontier_llm_judges"]["comparator_configuration_ids"]


def test_unadjudicated_accuracy_is_null_not_substring_accuracy(catalogue):
    c = next(c for c in catalogue["configurations"] if c["id"] == "bge-omneum-tied-maxima-20261007:bge")
    assert c["outcomes"]["complete_answer_accuracy"] == {"count": None, "rate": None}
    assert c["outcomes"]["incomplete"]["count"] is None
    assert c["recorded_answer_scores"]["accuracy"] == 22/24


def test_saved_semantic_reviews_and_astra_reasoning(catalogue):
    by = {c["id"]:c for c in catalogue["configurations"]}
    astra = by["bge-openai-vs-bge-omneum-20261008:bge_openai"]
    assert astra["outcomes"]["complete_answer_accuracy"]["count"]==222
    assert astra["outcomes"]["incomplete"]["count"]==8
    assert astra["api_tokens"]["selection"]["output"]==14699
    assert astra["api_tokens"]["selection"]["reasoning"]==9194
    assert astra["api_tokens"]["total"]["total"]==197556
    assert astra["cost_usd"]["estimated_api_total"]==pytest.approx(2.110048)
    claude = by["bge-claude-vs-bge-omneum-20261008:bge_anthropic"]
    assert claude["outcomes"]["complete_answer_accuracy"]["count"]==23
    assert claude["outcomes"]["incomplete"]["count"]==1
    cohere = by["cohere-claude-vs-cohere-omneum-20261008:cohere_omneum"]
    assert cohere["outcomes"]["complete_answer_accuracy"]["count"]==21
    assert cohere["outcomes"]["unanswered"]["count"]==1
    assert cohere["outcomes"]["generator_refusal"]["count"]==0


def test_cohere_missing_telemetry_and_illustrative_cost_are_not_filled(catalogue):
    for c in catalogue["configurations"]:
        if not c["method_id"].startswith("cohere"):continue
        assert c["api_tokens"]["selection"]["total"] is None
        assert c["api_tokens"]["total"]["total"] is None
        assert c["cost_usd"]["estimated_api_total"] is None
        assert c["cost_usd"]["estimated_api_per_answer"] is None
    c = next(c for c in catalogue["configurations"] if c["id"]=="cohere-claude-vs-cohere-omneum-20261008:cohere_anthropic")
    assert c["api_tokens"]["selection_judge_only"]["total"]==16527
    assert c["cohere_billed_search_units"]==24
    assert c["cost_usd"]["known_api_subtotal"]==pytest.approx(.109626)


def test_coverage_and_publication_lineage(catalogue):
    by = {c["id"]: c for c in catalogue["configurations"]}
    c = by["bge-omneum-tied-maxima-20261007:bge_omneum"]
    assert c["measurement_coverage"]["selection_scores"] == 23 < c["attempts"]
    assert all(c["lineage"]["reused_baseline_run"] is None for c in by.values())
    assert catalogue["pairing"]["pair_count"] is None
    assert catalogue["pairing"]["identical_bge_shortlists"] is None


def test_preserved_directories_unchanged_by_catalogue_rebuild():
    files = [p for folder in ("results","analysis") for p in (BASE/folder).rglob('*') if p.is_file() and '__pycache__' not in str(p)]
    before = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    build_summary()
    assert before == {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def test_publication_authority_is_explicit_and_pairs_never_mix_runs(catalogue):
    expected = {
        "bge-omneum-tied-maxima-20261007": ["bge","bge_omneum"],
        "20261008T014713Z": ["cohere","cohere_omneum"],
        "bge-claude-vs-bge-omneum-20261008": ["bge_anthropic","bge_omneum"],
        "bge-openai-vs-bge-omneum-20261008": ["bge_openai","bge_omneum"],
        "bge-google-vs-bge-omneum-20261008": ["bge_google","bge_omneum"],
        "cohere-claude-vs-cohere-omneum-20261008": ["cohere_anthropic","cohere_omneum"],
    }
    by = {c["id"]:c for c in catalogue["configurations"]}
    assert {p["run_id"] for p in catalogue["publication"]["pairs"]} == set(expected)
    for pair in catalogue["publication"]["pairs"]:
        cc = [by[cid] for cid in pair["configuration_ids"]]
        assert {c["run_id"] for c in cc} == {pair["run_id"]}
        assert [c["method_id"] for c in cc] == expected[pair["run_id"]]
        assert all(c["publication_status"]=="authoritative" for c in cc)
        assert all(resolve_artifact(p).exists() for p in pair["evidence_paths"])
    assert len(catalogue["publication"]["tables"]["semantic_rerankers"])==4
    assert len(catalogue["publication"]["tables"]["frontier_llm_judges"])==8


def test_only_contracted_runs_are_inventoried(catalogue):
    from .build_dashboard_summary import PUBLICATION_RUNS
    assert {r["id"] for r in catalogue["runs"]} == set(PUBLICATION_RUNS) | {"diagnostic-tied-maxima-selection-only-20261007"}
    assert "historical_inventory" not in catalogue
    assert catalogue["publication_contract"]["version"] == 1


def test_chronology_distinguishes_committed_reference_from_dirty_execution(catalogue):
    runs = {r["id"]:r for r in catalogue["runs"]}
    for r in runs.values():
        if r["git"] is None:continue
        assert r["git"]["dirty"] is True
        assert r["implementation_lineage"]["execution_braid_version"] is None
        assert r["implementation_lineage"]["execution_selector_version"] is None
        assert r["implementation_lineage"]["fingerprint_matches_committed_tree"] is False
    assert runs["bge-omneum-tied-maxima-20261007"]["versions"]["declared_braid_at_git_revision"]=="braid-1.1.0"
    d = catalogue["lineage_audit"]["tied_diagnostic"]
    assert d["matching_git_revisions"]["omneum/inference.py"]
    assert d["matching_git_revisions"]["omneum/dependency.py"]
    assert d["timestamp_utc"] < "2026-10-08T01:33:13+00:00"


def test_recorded_metrics_and_source_paths_remain_complete(catalogue):
    for r in catalogue["runs"]:
        path = BASE/"results"/r["id"]/"summary.json"
        assert r["recorded_evaluation_metrics"] == (json.loads(path.read_text()) if path.exists() else None)
        assert all(resolve_artifact(p).exists() for p in r["source_paths"])


def test_authoritative_bge_claim_matches_saved_results(catalogue):
    rows = catalogue["publication"]["tables"]["semantic_rerankers"]
    bge, augmented = rows[:2]
    assert bge["source_run"]==augmented["source_run"]=="bge-omneum-tied-maxima-20261007"
    assert bge["accuracy"]==22/24 and augmented["accuracy"]==21/24
    assert augmented["accuracy"] < bge["accuracy"]
    assert "substring" in bge["accuracy_basis"] and "substring" in augmented["accuracy_basis"]
    assert augmented["precision"] > bge["precision"] and augmented["recall"] > bge["recall"]
    assert augmented["selection_scored_attempts"]==23 and bge["selection_scored_attempts"]==24
    # Missing top-level E2E on refusal is a sum of two present measured stages, not a fabricated timing.
    saved = json.loads((BASE/"results"/bge["source_run"]/"summary.json").read_text())
    assert augmented["end_to_end_p50_seconds"]==saved["bge_omneum"]["latency"]["end_to_end_seconds"]["p50"]


def test_publication_omneum_arms_not_substituted_even_when_selection_matches(catalogue):
    rows = catalogue["publication"]["tables"]["frontier_llm_judges"]
    omneum = {r["source_run"]:r for r in rows if r["label"]=="BGE + Omneum"}
    assert omneum["bge-google-vs-bge-omneum-20261008"]["api_tokens"]==115535
    assert omneum["bge-openai-vs-bge-omneum-20261008"]["api_tokens"]==115119
    assert omneum["bge-claude-vs-bge-omneum-20261008"]["api_tokens"]==11811
    assert len({r["end_to_end_p50_seconds"] for r in omneum.values()})==3


def test_published_cohere_latency_uses_existing_within_run_correction(catalogue):
    from .latency_analysis import analyze, read_jsonl
    d = BASE/"results/20261008T014713Z"
    corrected = analyze(read_jsonl(d/"results.jsonl"), read_jsonl(d/"cohere_responses.jsonl"))
    rows = catalogue["publication"]["tables"]["semantic_rerankers"][2:]
    for method,row in zip(("cohere","cohere_omneum"),rows):
        assert row["source_run"]==d.name
        assert row["selection_p50_seconds"]==corrected["metrics"][method]["corrected_selection"]["p50"]
        assert row["end_to_end_p50_seconds"]==corrected["metrics"][method]["corrected_end_to_end"]["p50"]
        assert row["api_tokens"] is None and row["estimated_api_cost_usd"] is None
        assert "within-run" in row["latency_basis"]


def test_main_configuration_array_cannot_default_to_early_historical_run(catalogue):
    assert len(catalogue["configurations"])==12
    assert all(c["publication_status"]=="authoritative" for c in catalogue["configurations"])
    assert catalogue["configurations"][0]["run_id"]=="bge-omneum-tied-maxima-20261007"
    main = {c["id"] for c in catalogue["configurations"]}
    assert main == {cid for b in catalogue["leaderboards"].values() for cid in b["configuration_ids"]}
    assert len(main) == 12


def test_incomplete_publication_schedule_is_not_promoted(monkeypatch):
    from . import build_dashboard_summary as dashboard
    read_text = Path.read_text
    directory = BASE / "results" / RUN
    rows = [json.loads(line) for line in (directory / "results.jsonl").read_text().splitlines()][:3]

    def partial(path, *args, **kwargs):
        if path == directory / "results.jsonl":
            return "\n".join(json.dumps(row) for row in rows)
        if path == directory / "summary.json":
            return json.dumps(dashboard.summarize(rows))
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", partial)
    configurations, runs, _ = dashboard.scan_saved_runs(json.loads(OUTPUT.read_text())["pricing"])
    run = next(r for r in runs if r["id"] == RUN)
    assert run["status"] == "partial"
    assert run["configuration_ids"] == []
    assert dashboard.publication_classification(run)[0] == "partial"
    assert not any(c["run_id"] == RUN for c in configurations)
