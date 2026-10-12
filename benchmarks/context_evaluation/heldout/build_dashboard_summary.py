"""Rebuild dashboard data offline; never imports selectors or provider clients.

Run from the repository root:
python -m benchmarks.context_evaluation.heldout.build_dashboard_summary
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
from datetime import datetime

from .aggregate import _percentile, summarize
from .scoring import normalize
from ..paths import verify_recorded_artifact, public_manifest, publication_contract

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
RUN = "bge-google-low-vs-bge-omneum-20261008"
METHODS = ("bge_google", "bge_omneum")
OUTPUT = BASE / "dashboard_summary.json"
SCHEMA = BASE / "dashboard_summary.schema.json"
def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key(row):
    return row["case_id"], row["trial"], row["method"]


def validate_pairing(rows, cases, trials):
    by = {key(r): r for r in rows}
    expected = {(c, t, m) for c in cases for t in range(1, trials + 1) for m in METHODS}
    require(len(rows) == len(by) and set(by) == expected, "Incomplete or duplicate paired schedule")
    for c in cases:
        for t in range(1, trials + 1):
            a, b = (by[c, t, m] for m in METHODS)
            require(a["selection"]["bge_relevance"] == b["selection"]["bge_relevance"], "Unpaired BGE shortlist")
            for r in (a, b):
                require(r["selection"]["context_budget"] == a["selection"]["context_budget"], "Unpaired context budget")
                require(r["generation"]["model"] == a["generation"]["model"], "Unpaired generator")
                require(math.isclose(r["end_to_end_latency_seconds"], r["selection"]["latency_seconds"] + r["generation"]["latency_seconds"]), "Latency stages do not reconcile")
    return by


def selection_metrics(rows):
    scores = [r["selection_score"] for r in rows]
    tp, fp, fn = (sum(s[k] for s in scores) for k in ("true_positive", "false_positive", "false_negative"))
    return {
        "macro": {"precision": mean(s["precision"] for s in scores),
                  "recall": mean(s["recall"] for s in scores),
                  "f1": mean(2*s["true_positive"] / (2*s["true_positive"] + s["false_positive"] + s["false_negative"])
                             if 2*s["true_positive"] + s["false_positive"] + s["false_negative"] else 0.0 for s in scores)},
        "micro": {"precision": tp/(tp+fp) if tp+fp else 0.0,
                  "recall": tp/(tp+fn) if tp+fn else 0.0,
                  "f1": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.0},
        "counts": {"true_positive": tp, "false_positive": fp, "false_negative": fn},
    }


def build_verified_gemini_summary():
    from .verify_gemini_recovery import verify
    manifest, rows, audit, comparison = verify(BASE)
    analysis = BASE / "analysis" / RUN
    results = BASE / "results" / RUN
    sources = {str(p.relative_to(ROOT)): sha(p) for directory in (analysis, results)
               for p in directory.iterdir() if p.is_file()}
    contract = manifest["checkpoint_contract"]
    cases = sorted({r["case_id"] for r in rows})
    validate_pairing(rows, cases, 10)
    reviewed = {key(r): r for r in audit}
    configs = []
    rates = comparison["pricing"]["usd_per_million"]
    for method in METHODS:
        rr = [r for r in rows if r["method"] == method]
        n = len(rr)
        counts = Counter(reviewed[key(r)]["manual_status"] for r in rr)
        outcomes = {name: {"count": counts[status], "rate": counts[status]/n} for name, status in (
            ("complete_answer_accuracy", "correct"), ("incorrect", "substantively_incorrect"),
            ("incomplete", "incomplete"), ("generator_refusal", "generator_refusal"))}
        sel = selection_metrics(rr)
        latency = {stage: {"p50": _percentile([r["selection"]["latency_seconds"] if stage == "selection" else r["end_to_end_latency_seconds"] for r in rr], .5),
                           "p95": _percentile([r["selection"]["latency_seconds"] if stage == "selection" else r["end_to_end_latency_seconds"] for r in rr], .95)} for stage in ("selection", "end_to_end")}
        st, gt = usage_for_run(rr, method), usage_for_run(rr, method, True)
        total = {k: nullable_sum([st[k], gt[k]]) for k in st}
        selector_cost = ((st["input"]*rates["gemini_input"] + st["output"]*rates["gemini_visible_plus_thinking_output"])/1e6
                         if st["input"] is not None and st["output"] is not None else None)
        generator_cost = (gt["input"]*rates["sonnet_input"] + gt["output"]*rates["sonnet_output"])/1e6
        cost = nullable_sum([selector_cost, generator_cost])
        gemini = method == "bge_google"
        configs.append({"id": method, "label": "BGE + Gemini" if gemini else "BGE + Omneum",
            "method_families": ["semantic_reranker", "frontier_llm_judge"] if gemini else ["semantic_reranker"],
            "configuration_kind": "baseline" if gemini else "omneum_augmented", "execution_shape": "pipeline",
            "baseline_configuration_id": None, "augmentation_target": None if gemini else "bge",
            "components": [{"role": "reranker", "method": "bge", "model": "BAAI/bge-reranker-v2-m3"},
                           {"role": "context_selector", "method": "gemini" if gemini else "omneum", "model": contract["models"][method]},
                           {"role": "answer_generator", "method": "anthropic", "model": contract["models"]["generator"]}],
            "selector_inputs": "shortlist text and source IDs" if gemini else "structured claims, provenance, and dependency observations",
            "attempts": n, "case_count": len(cases), "trials_per_case": manifest["trials"],
            "outcomes": outcomes, "selection": sel, "latency_seconds": latency,
            "api_tokens": {"selection": st, "generation": gt, "total": total},
            "cost_usd": {"estimated_api_total": cost, "estimated_api_per_answer": cost/n if cost is not None else None,
                         "selection": selector_cost, "generation": generator_cost,
                         "invoiced_api_total": None, "local_compute_total": None},
            "local_reranker_tokens": None})
    return {"$schema": "dashboard_summary.schema.json", "schema_version": "1.0.0", "benchmark_id": RUN,
        "measurement_date": "2026-10-09", "selector_version": "original recorded selector; excludes experimental conflict policies",
        "units": {"rates": "fraction", "latency": "seconds", "api_tokens": "provider_tokens", "cost": "USD"},
        "supported_method_families": ["semantic_reranker", "frontier_llm_judge", "standalone_omneum"],
        "definitions": {
            "outcomes": "Rates are fractions [0,1], counts divided by all attempts including refusals. Correct means complete semantic answer; incomplete and substantive errors remain distinct.",
            "selection": "Source-label precision=TP/(TP+FP), recall=TP/(TP+FN), F1=2TP/(2TP+FP+FN). Macro averages per-attempt metrics (equal case weights here); micro pools counts. Zero-denominator selection metrics are 0; absent measurements are null.",
            "latency": "Seconds, all attempts; p50/p95 linearly interpolate at (n-1)q. Selection includes BGE and integration; end-to-end includes generation.",
            "tokens": "Reported API tokens summed across all attempts and provider tokenizers. Output includes Gemini thinking exactly once plus reported Claude output. Reasoning is null when not separately reported; null does not mean zero. Local token usage is unavailable.",
            "cost": "USD estimated API cost at frozen reported rates, not invoices; per answer divides by attempts including refusals. Excludes local compute/hosting, credits, discounts, and unlogged retries.",
            "configuration": "Baseline means comparator, not BGE-only. BGE + Omneum augments BGE with a selector; it does not augment Gemini. No measured BGE-only counterpart exists, so baseline_configuration_id is null. Standalone results must have their own verified configurations."},
        "pairing": {"methods": list(METHODS), "pair_count": len(cases)*manifest["trials"], "keys": ["case_id", "trial"],
                    "identical_bge_shortlists": True, "identical_context_budgets": True, "shared_generator": contract["models"]["generator"]},
        "pricing": comparison["pricing"], "source_file_sha256": dict(sorted(sources.items())),
        "implementation": comparison["implementation"],
        "limitations": ["24 fixed synthetic cases with clustered repeats, not 240 independent tasks.",
                        "Selectors receive different information; original selection and recovered generation measurements are from different dates, with reconstructed E2E stage sums.",
                        "Independent incorrect estimates displaced census evidence in all ten false-consensus trials.",
                        "Every Gemini answer was reviewed against the frozen reference and selected evidence; baseline adjudications were preserved. Review was not blinded.",
                        "Dirty execution checkout has no verified source snapshot; preserved metrics are reproducible offline."],
        "unmeasured_configurations": ["BGE alone", "Standalone Gemini", "Standalone Omneum", "Gemini + Omneum"],
        "configurations": configs}



def nullable_sum(values):
    return sum(values) if all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0 for v in values) else None


def usage_for_run(rows, method, generation=False):
    local = method in ("bge", "vector", "braid", "bge_omneum")
    # anthropic_omneum denotes two different historical pipelines; inspect its recorded evaluator.
    if method == "anthropic_omneum":
        local = all(r["selection"].get("evaluator_provider") in ("local", None) and r["selection"].get("evaluator_model") == "Omneum" for r in rows)
    inputs, outputs, reasoning = [], [], []
    for r in rows:
        stage = (r.get("generation") if generation else r.get("selection")) or {}
        prefix = "" if generation else "evaluator_" if "evaluator_input_tokens" in stage else ""
        diag = (stage.get("response_diagnostics") or stage.get("evaluator_response_diagnostics") or {}).get("usage_metadata", {})
        ins, out = stage.get(prefix+"input_tokens"), stage.get(prefix+"output_tokens")
        thoughts = diag.get("reasoning_tokens")
        if not generation and local and r["answer_score"] != "selection_failure":
            ins = out = thoughts = 0
        if not generation and "google" in method:
            thoughts = diag.get("thoughts_token_count")
            out = out + thoughts if out is not None and thoughts is not None else None
            if diag.get("total_token_count") is not None and ins is not None and out is not None:
                require(diag["total_token_count"] == ins+out, "Google total usage mismatch")
        # OpenAI output_tokens already includes reasoning; never add it again.
        inputs.append(ins); outputs.append(out); reasoning.append(thoughts)
    total_input, total_output = nullable_sum(inputs), nullable_sum(outputs)
    return {"input": total_input, "output": total_output,
            "total": total_input+total_output if total_input is not None and total_output is not None else None,
            "reasoning": nullable_sum(reasoning)}


def method_description(method, rows, manifest):
    names = {"bge": "BGE", "cohere": "Cohere", "braid": "Standalone Omneum", "vector": "Vector",
             "anthropic": "Claude", "openai": "GPT (Astra)", "google": "Gemini",
             "anthropic_provenance": "Claude + provenance", "openai_provenance": "GPT (Astra) + provenance", "google_provenance": "Gemini + provenance",
             "bge_anthropic": "BGE + Claude", "cohere_anthropic": "Cohere + Claude",
             "bge_openai": "BGE + GPT (Astra)", "bge_google": "BGE + Gemini",
             "bge_omneum": "BGE + Omneum", "cohere_omneum": "Cohere + Omneum", "anthropic_omneum": "Claude + Omneum"}
    components = []
    first = rows[0]["selection"] or {}
    augmented = method in ("bge_omneum", "cohere_omneum", "anthropic_omneum")
    replacement = method == "anthropic_omneum" and first.get("evaluator_model") == "Omneum"
    if replacement:
        names[method] = "Standalone Omneum (Claude replacement)"
    reranker = "bge" if method.startswith("bge") else "cohere" if method.startswith("cohere") else None
    if reranker:
        components.append({"role": "reranker", "method": reranker, "model": "BAAI/bge-reranker-v2-m3" if reranker == "bge" else "rerank-v4.0-pro"})
    judge = next((name for name in ("anthropic", "openai", "google") if name in method), None)
    if judge and not replacement:
        model = manifest["models"].get(method) or first.get("evaluator_model") or first.get("model")
        components.append({"role": "context_selector", "method": judge, "model": model})
    if augmented or method == "braid":
        components.append({"role": "context_selector", "method": "omneum", "model": "Omneum"})
    if method == "vector":
        components.append({"role": "context_selector", "method": "vector", "model": first.get("model", "all-MiniLM-L6-v2")})
    components.append({"role": "answer_generator", "method": "anthropic", "model": manifest["models"]["generator"]})
    families = (["semantic_reranker"] if reranker else []) + (["frontier_llm_judge"] if judge and not replacement else [])
    if method == "braid" or replacement:
        families = ["standalone_omneum"]
    # Vector baselines stay in the inventory; they are not mislabeled as semantic rerankers.
    if method == "vector":
        families = ["semantic_retriever"]
    return names[method], components, families, augmented and not replacement, replacement


def outcomes_for_run(rows, method, analysis, comparison):
    n = len(rows)
    audit_path = analysis / "answer_audit.json"
    semantic = None
    basis = "unavailable; frozen substring scores provided separately"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text())
        by = {key(a): a for a in audit}
        require(len(by) == len(audit), "Duplicate adjudications")
        semantic = Counter()
        aliases = {"correct": "complete_answer_accuracy", "partial": "incomplete", "incomplete": "incomplete", "incorrect": "incorrect", "substantively_incorrect": "incorrect", "generator_refusal": "generator_refusal"}
        for r in rows:
            a = by[key(r)]
            require(a["answer"] == r["answer"] and a["selected"] == r["selected"] and a["recorded_score"] == r["answer_score"], "Adjudication does not match raw record")
            semantic[aliases[a["manual_status"]]] += 1
        basis = "preserved per-answer semantic adjudications"
    elif comparison and "metrics" in comparison and method in comparison["metrics"]:
        review = comparison["metrics"][method].get("substantive_review")
        if review:
            require(sum(review.values()) == n, "Semantic aggregate denominator mismatch")
            semantic = Counter({"complete_answer_accuracy": review["fully_correct"], "incomplete": review["partial"], "incorrect": review["wrong"], "unanswered": review.get("unanswered", 0)})
            failures = review.get("generation_failure", 0)
            refusals = sum(r.get("failure_type") == "refusal" or ((r.get("generation") or {}).get("response_diagnostics") or {}).get("stop_reason") == "refusal" for r in rows)
            require(refusals <= failures, "Review refusal counts do not reconcile")
            semantic["generator_refusal"] = refusals
            semantic["other_failure"] = failures-refusals
            basis = "preserved aggregate semantic review"
    fields = ("complete_answer_accuracy", "incorrect", "incomplete", "generator_refusal", "unanswered", "unadjudicated", "other_failure")
    if semantic is None:
        refusal = sum(r.get("failure_type") == "refusal" or ((r.get("generation") or {}).get("response_diagnostics") or {}).get("stop_reason") == "refusal" for r in rows)
        failure = sum(r["answer_score"] in ("selection_failure", "generation_failure")
                      or r.get("failure_type") == "refusal"
                      or ((r.get("generation") or {}).get("response_diagnostics") or {}).get("stop_reason") == "refusal"
                      for r in rows)
        out = {k: {"count": None, "rate": None} for k in fields}
        for k, v in (("generator_refusal", refusal), ("other_failure", failure-refusal), ("unadjudicated", n-failure)):
            out[k] = {"count": v, "rate": v/n}
    else:
        require(sum(semantic.values()) == n, "Semantic outcomes not exhaustive")
        out = {k: {"count": semantic[k], "rate": semantic[k]/n} for k in fields}
    return out, basis


def common_summary_check(saved, rebuilt, prefix=""):
    """Legacy BRAID latency keys were renamed; compare every other common scalar."""
    mismatches = []
    for k, old in saved.items():
        if k not in rebuilt:
            continue
        new = rebuilt[k]
        name = prefix + "/" + k
        if isinstance(old, dict) and isinstance(new, dict):
            mismatches += common_summary_check(old, new, name)
        elif isinstance(old, (int, float)) and isinstance(new, (int, float)):
            if not math.isclose(old, new, rel_tol=1e-10, abs_tol=1e-12): mismatches.append(name)
        elif old != new:
            mismatches.append(name)
    return mismatches


def scan_saved_runs(pricing):
    configs, inventory, sources = [], [], {}
    rates = pricing["usd_per_million"]
    # Astra prices are explicitly frozen in the preserved October 8 report/script.
    rate_pairs = {"anthropic": (rates["sonnet_input"], rates["sonnet_output"]), "google": (rates["gemini_input"], rates["gemini_visible_plus_thinking_output"]), "openai": (10, 50)}
    for run_name in sorted((*PUBLICATION_RUNS, "diagnostic-tied-maxima-selection-only-20261007")):
        directory = BASE / "results" / run_name
        require(directory.is_dir(), f"Missing publication evidence: {run_name}")
        run = directory.name
        record_path = directory/"results.jsonl"
        for p in directory.rglob('*'):
            if p.is_file() and p.name != '.run.lock': sources[str(p.relative_to(ROOT))] = sha(p)
        info = {"id": run, "status": "diagnostic_only", "records": 0, "configuration_ids": [], "issues": [], "verification": {}}
        if not record_path.exists():
            info["issues"].append("No trial records; diagnostic traces are not benchmark answers")
            inventory.append(info); continue
        rows = [json.loads(line) for line in record_path.read_text().splitlines()]
        info["records"] = len(rows)
        manifest_path = public_manifest(directory)
        if not manifest_path.exists():
            raise ValueError(f"Missing public manifest: {run}")
        manifest = json.loads(manifest_path.read_text())
        contract = manifest["checkpoint_contract"]
        for field in ("inputs", "models", "trials", "estimator", "packages", "python"):
            require(contract[field] == manifest[field], f"{run}: checkpoint mismatch {field}")
        cases, truths, hashes = {}, {}, {}
        for path, digest in manifest["inputs"].items():
            # Canonical identity is stable across recorded checkout locations.
            original = Path(path)
            p = BASE/"cases"/original.parent.name/original.name
            require(p.exists() and sha(p) == digest, f"{run}: fixture hash mismatch {path}")
            hashes[f"{original.parent.name}/{original.name}"] = digest
            sources[str(p.relative_to(ROOT))] = digest
            (truths if p.name == "ground_truth.json" else cases)[p.parent.name] = json.loads(p.read_text())
        require(set(cases) == set(truths), f"{run}: case/ground-truth mismatch")
        methods = [m["name"] for m in contract["methods"]]
        expected = {(c, t, m) for c in cases for t in range(1, manifest["trials"]+1) for m in methods}
        by = {key(r): r for r in rows}
        require(len(by) == len(rows) and set(by) <= expected, f"{run}: duplicate or off-contract records")
        complete = set(by) == expected
        info["status"] = "completed" if complete else "partial"
        info["verification"] = {"checkpoint": True, "fixture_hashes": len(hashes), "unique_records": True, "expected_records": len(expected), "missing_records": len(expected)-len(rows), "saved_summary_common_fields_match": None}
        info["dataset_sha256"] = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
        info["implementation"] = contract.get("implementation")
        info["trials_per_case"] = manifest["trials"]
        info["timestamp_utc"] = manifest.get("timestamp_utc")
        if not complete: info["issues"].append("Incomplete case/method/trial schedule; excluded from leaderboards")
        if len(cases) != 24: info["issues"].append("Subset of held-out cases; cannot compare directly to full 24-case runs")
        if any((r.get("selection") or {}).get("cohere_cache_hit") for r in rows):
            info["issues"].append("Cohere response cache reused across arms; cached timing and actual request billing differ from fresh rerank runs")
        for r in rows:
            chosen = set(r["selected"])
            pool = {d["source_id"] for d in cases[r["case_id"]]["candidates"]}
            require(len(chosen) == len(r["selected"]) and chosen <= pool and len(chosen) <= cases[r["case_id"]]["context_budget"], f"{run}: invalid selected sources")
            stage = r.get("selection") or {}
            texts = {d["source_id"]: d["text"] for d in cases[r["case_id"]]["candidates"]}
            if stage.get("selected") is not None:
                require([d["source"] for d in stage["selected"]] == r["selected"], f"{run}: selected evidence IDs mismatch")
                require(all(d["text"] == texts[d["source"]] for d in stage["selected"]), f"{run}: selected evidence text mismatch")
            for field in ("bge_relevance", "cohere_relevance"):
                if field in stage:
                    shortlist = stage[field]["selected"]
                    require(chosen <= {d["source"] for d in shortlist}, f"{run}: selection outside recorded shortlist")
                    require(all(d["text"] == texts[d["source"]] for d in shortlist), f"{run}: shortlist evidence text mismatch")
            if r["answer_score"] not in ("selection_failure", "generation_failure"):
                answer = normalize(r["answer"])
                rule = truths[r["case_id"]]["scoring"]
                reconstructed = "incorrect" if any(normalize(v) and normalize(v) in answer for v in rule["forbidden"]) else "correct" if all(normalize(v) and normalize(v) in answer for v in rule["required"]) else "unscored"
                require(reconstructed == r["answer_score"], f"{run}: frozen answer score mismatch")
            score = r.get("selection_score")
            if score is not None:
                truth = set(truths[r["case_id"]]["supporting_sources"])
                tp, fp, fn = len(chosen & truth), len(chosen-truth), len(truth-chosen)
                require((tp, fp, fn) == (score["true_positive"], score["false_positive"], score["false_negative"]), f"{run}: selection source counts mismatch")
                require(math.isclose(score["precision"], tp/len(chosen) if chosen else 0) and math.isclose(score["recall"], tp/len(truth)), f"{run}: selection ratios mismatch")
            gen = r.get("generation") or {}
            if gen:
                require(gen["model"] == manifest["models"]["generator"] and gen.get("text") == r.get("answer"), f"{run}: generator mismatch")
            if r.get("end_to_end_latency_seconds") is not None and gen.get("latency_seconds") is not None and (r.get("selection") or {}).get("latency_seconds") is not None:
                require(math.isclose(r["end_to_end_latency_seconds"], r["selection"]["latency_seconds"]+gen["latency_seconds"], abs_tol=1e-8), f"{run}: latency mismatch")
        summary_path = directory/"summary.json"
        if summary_path.exists():
            differences = common_summary_check(json.loads(summary_path.read_text()), summarize(rows))
            require(not differences, f"{run}: summary mismatch {differences}")
            info["verification"]["saved_summary_common_fields_match"] = True
        # Only recorded shared-shortlist objects prove exact relevance pairing.
        info["pairing"] = {"case_trial_pairs": len(cases)*manifest["trials"] if complete and len(methods)>1 else None,
                           "shared_shortlist_verified": None, "context_budgets_verified": True, "generator_model_verified": True}
        for field in ("bge_relevance", "cohere_relevance"):
            if complete and len(methods)>1 and all(field in (r.get("selection") or {}) for r in rows):
                require(all(all(by[c,t,m]["selection"][field] == by[c,t,methods[0]]["selection"][field] for m in methods) for c in cases for t in range(1,manifest["trials"]+1)), f"{run}: shortlist pairing mismatch")
                info["pairing"]["shared_shortlist_verified"] = True
        if info["pairing"]["shared_shortlist_verified"] is None and complete and len(methods)>1:
            info["issues"].append("Same case/trial/budget controls verified; identical shared shortlist not established for this run")
        if not complete:
            inventory.append(info); continue
        analysis = BASE/"analysis"/run
        comparison_path = analysis/"comparison.json" if (analysis/"comparison.json").exists() else directory/"comparison.json"
        comparison = json.loads(comparison_path.read_text()) if comparison_path.exists() else None
        if comparison and "source_file_sha256" in comparison:
            for p, digest in comparison["source_file_sha256"].items():
                verify_recorded_artifact(p, digest)
        for method in methods:
            rr = [r for r in rows if r["method"] == method]
            n = len(rr)
            cid = method if run == RUN else f"{run}:{method}"
            label, components, families, augmented, replacement = method_description(method, rr, manifest)
            outcomes, basis = outcomes_for_run(rr, method, analysis, comparison)
            scored = [r for r in rr if r.get("selection_score") is not None]
            selection = selection_metrics(scored) if scored else {"macro": dict.fromkeys(("precision", "recall", "f1")), "micro": dict.fromkeys(("precision", "recall", "f1")), "counts": dict.fromkeys(("true_positive", "false_positive", "false_negative"))}
            latency, coverage = {}, {"selection_scores": len(scored)}
            for stage in ("selection", "end_to_end"):
                values = []
                for r in rr:
                    value = (r.get("selection") or {}).get("latency_seconds") if stage == "selection" else r.get("end_to_end_latency_seconds")
                    if stage == "end_to_end" and value is None:
                        parts = [(r.get("selection") or {}).get("latency_seconds"), (r.get("generation") or {}).get("latency_seconds")]
                        value = nullable_sum(parts)  # Same measured-stage sum used by preserved summaries.
                    values.append(value)
                known = [v for v in values if isinstance(v, (int,float)) and math.isfinite(v)]
                coverage[stage+"_latency"] = len(known)
                # Do not turn a partial-coverage percentile into a full-pipeline statistic.
                latency[stage] = {"p50": _percentile(known,.5) if len(known)==n else None, "p95": _percentile(known,.95) if len(known)==n else None}
            st, gt = usage_for_run(rr, method), usage_for_run(rr, method, True)
            total = {k: nullable_sum([st[k], gt[k]]) for k in st}
            provider = next((c["method"] for c in components if c["role"]=="context_selector" and c["method"] in rate_pairs), None)
            cohere = method.startswith("cohere")
            cost_sel = 0.0 if provider is None and not cohere else None
            if provider and st["input"] is not None and st["output"] is not None:
                ri, ro = rate_pairs[provider]
                cost_sel = (st["input"]*ri + st["output"]*ro)/1e6
            known_judge_tokens = dict(st) if provider else {"input": 0, "output": 0, "total": 0, "reasoning": 0}
            known_judge_cost = cost_sel if provider else 0.0
            if cohere: cost_sel = None  # Rerank pricing is unverified, even when Claude judge cost is known.
            cost_gen = (gt["input"]*rates["sonnet_input"]+gt["output"]*rates["sonnet_output"])/1e6 if gt["input"] is not None and gt["output"] is not None else None
            cost = nullable_sum([cost_sel, cost_gen])
            if cohere:
                st = dict.fromkeys(st)  # No Cohere token telemetry; Claude-only totals are not entire-pipeline totals.
                total = {k: nullable_sum([st[k], gt[k]]) for k in st}
            counterpart = None
            target = None
            if augmented:
                target = "bge" if method=="bge_omneum" else "cohere" if method=="cohere_omneum" else "anthropic"
                if target in methods: counterpart = target if run==RUN else f"{run}:{target}"
            c = {"id": cid, "run_id": run, "method_id": method, "label": label, "method_families": families,
                 "configuration_kind": "omneum_augmented" if augmented else "baseline", "execution_shape": "standalone" if len(components)==2 else "pipeline",
                 "baseline_configuration_id": counterpart, "augmentation_target": target,
                 "components": components, "selector_inputs": "provenance-enabled" if "provenance" in method else "See preserved run manifest; selector information differs by method",
                 "attempts": n, "case_count": len(cases), "trials_per_case": manifest["trials"], "outcomes": outcomes,
                 "accuracy_basis": basis, "recorded_answer_scores": {"counts": dict(Counter(r["answer_score"] for r in rr)), "accuracy": sum(r["answer_score"]=="correct" for r in rr)/n, "definition": "Frozen substring correct / all attempts; not complete semantic accuracy"},
                 "selection": selection, "measurement_coverage": coverage, "latency_seconds": latency,
                 "api_tokens": {"selection": st,"generation": gt,"total": total},
                 "cost_usd": {"estimated_api_total": cost,"estimated_api_per_answer": cost/n if cost is not None else None,"selection": cost_sel,"generation": cost_gen,"invoiced_api_total": None,"local_compute_total": None},
                 "local_reranker_tokens": None, "comparison_scope": run,
                 "lineage": {"reused_baseline_run": None,
                             "implementation": contract.get("implementation")}}
            if cohere:
                c["api_tokens"]["selection_judge_only"] = known_judge_tokens
                c["cost_usd"]["known_api_subtotal"] = nullable_sum([known_judge_cost, cost_gen])
                c["cohere_billed_search_units"] = nullable_sum([(r.get("selection") or {}).get("cohere_billed_search_units") for r in rr])
            if comparison and "aggregates" in comparison:
                a = comparison["aggregates"][method]
                require(math.isclose(selection["macro"]["precision"], a["precision"]) and math.isclose(selection["macro"]["recall"],a["recall"]), f"{run}: published selection mismatch")
                require(math.isclose(cost,a["total_usd"]), f"{run}: published cost mismatch")
            configs.append(c);info["configuration_ids"].append(cid)
        if any("unavailable" in c["accuracy_basis"] for c in configs if c["run_id"]==run): info["issues"].append("Complete-answer accuracy and incorrect/incomplete rates unavailable without semantic adjudication; substring accuracy is separate")
        if any(c["measurement_coverage"]["selection_scores"]<c["attempts"] for c in configs if c["run_id"]==run): info["issues"].append("Selection metrics cover only recorded scored attempts; failure selections were not silently rescored")
        if any(c["method_id"].startswith("cohere") for c in configs if c["run_id"]==run): info["issues"].append("Cohere token telemetry and verified rerank pricing unavailable; total API tokens/cost are null")
        inventory.append(info)
    return configs, inventory, sources


def verify_publication_evidence():
    contract = publication_contract()
    require(contract["version"] == 1, "Unsupported publication evidence contract")
    for name, digest in contract["artifacts"].items():
        path = ROOT / name
        require(path.is_file() and sha(path) == digest, f"Publication artifact changed: {name}")
    return contract


def build_summary():
    verify_publication_evidence()
    original = build_verified_gemini_summary()
    configurations, inventory, sources = scan_saved_runs(original["pricing"])
    # Preserve the already-published Gemini configuration values and rich descriptions.
    for original_c in original["configurations"]:
        c = next(c for c in configurations if c["id"]==original_c["id"])
        for field in original_c:
            if field != "outcomes": c[field] = original_c[field]
        require(all(c["outcomes"][k] == v for k,v in original_c["outcomes"].items()), "Original semantic metrics changed")
    sources.update(original["source_file_sha256"])
    analyses = []
    for run_name in ("bge-google-low-vs-bge-omneum-20261008", "bge-openai-vs-bge-omneum-20261008"):
        directory = BASE / "analysis" / run_name
        files = []
        for p in sorted(directory.rglob('*')):
            if p.is_file() and '__pycache__' not in str(p):
                path = str(p.relative_to(ROOT));sources[path]=sha(p);files.append(path)
        analyses.append({"id": directory.name, "trial_run": directory.name, "files": files,
                         "status": "preserved trial analysis"})
    original.update(schema_version="1.1.0", benchmark_id="heldout-completed-runs", configurations=configurations,
                    runs=inventory, analyses=analyses, source_file_sha256=dict(sorted(sources.items())))
    original["pairing"] = {"methods": sorted({c["method_id"] for c in configurations}), "pair_count": None,
        "keys": ["run_id", "case_id", "trial"], "identical_bge_shortlists": None,
        "identical_context_budgets": None, "shared_generator": "claude-sonnet-5-5"}
    original["implementation"] = {"manifest": None, "checkout_before_analysis": None}
    original["selector_version"] = "Preserved execution-time selectors per run; excludes experimental conflict-policy trials"
    original["supported_method_families"].append("semantic_retriever")
    original["definitions"]["outcomes"] += " Semantic outcomes are null without preserved adjudications; recorded substring accuracy is separate. Unanswered, unadjudicated and other failures are explicitly tracked."
    original["definitions"]["selection"] += " Older runs may cover only scored attempts; measurement_coverage states the denominator."
    original["definitions"]["cost"] += " All estimates normalize measured usage to the October 8 snapshot; Cohere's illustrative rate is never used."
    original["definitions"]["tokens"] += " OpenAI output already includes reasoning; Cohere's absent token telemetry makes whole-pipeline totals null."
    original["definitions"]["configuration"] = "Configurations are identified by run and method, with no pooling across runs. Baseline is the within-run comparator; augmentation_target and optional baseline_configuration_id identify the actual preceding method. Replacement selectors are not mislabeled as augmentations. Family tags describe recorded components, with standalone Omneum shown as a reference in both views."
    original["pricing"]["usd_per_million"].update(astra_input=10, astra_output=50)
    original["pricing"]["openai_source"]="https://developers.openai.com/api/docs/models/gpt-6-astra"
    original["pricing"]["basis"] += "; normalized October 8 comparison rates for all measured runs; not historical invoices"
    original["unmeasured_configurations"] = ["Standalone Gemini + Omneum", "Standalone GPT + Omneum"]
    original["comparability"] = {"policy":"Compare within each run and matching metric coverage/basis; do not pool runs or reused baselines. No global rank inferred.",
        "cross_run_blockers":["Different trial counts, execution dates, selector implementation fingerprints and tuning/validation stages.", "Substring scores are not semantic complete-answer accuracy.", "Cohere pricing is illustrative and token telemetry absent; whole-pipeline cost/tokens cannot be compared.", "Some old metrics exclude failure selections or have partial telemetry; coverage is explicit.", "Only the six reviewed complete runs are publication authority; incomplete schedules cannot replace them."]}
    return apply_publication_authority(original)


# Publication authority is an explicit evidence decision, never "first row" or "latest score".
PUBLICATION_RUNS = {
    "bge-omneum-tied-maxima-20261007": {
        "family": "semantic_rerankers", "methods": ["bge", "bge_omneum"],
        "reason": "Last preserved complete BGE-only pairing; the tied-maxima diagnostic documents recovery of coding_config_conflict and research_syndicated_reporting relative to the earlier smoke. All 24 Omneum selected sets match later BGE judge experiments; generated measurements remain separate.",
        "evidence": ["results/diagnostic-tied-maxima-selection-only-20261007/selection_only_diagnostic.public-v1.json", "EVIDENCE.md"],
    },
    "20261008T014713Z": {
        "family": "semantic_rerankers", "methods": ["cohere", "cohere_omneum"],
        "reason": "Only complete dedicated Cohere-only pairing after the source-dependency commit, verified against shared request hashes and response records. Later Cohere + Claude uses a different baseline; it cannot replace Cohere-only measurements. Cached-arm latency requires the preserved within-run correction.",
        "evidence": ["LATENCY_ANALYSIS.md", "EVIDENCE.md"],
    },
    "bge-claude-vs-bge-omneum-20261008": {
        "family": "frontier_llm_judges", "methods": ["bge_anthropic", "bge_omneum"],
        "reason": "Final preserved dedicated shared-BGE Claude-judge replacement experiment with complete paired coverage and saved semantic review.",
        "evidence": ["results/bge-claude-vs-bge-omneum-20261008/report.md", "EVIDENCE.md"],
    },
    "bge-openai-vs-bge-omneum-20261008": {
        "family": "frontier_llm_judges", "methods": ["bge_openai", "bge_omneum"],
        "reason": "Complete dedicated shared-BGE Astra replacement experiment; per-answer semantic adjudications and immutable source hashes verify both original arms.",
        "evidence": ["analysis/bge-openai-vs-bge-omneum-20261008/report.md"],
    },
    "bge-google-low-vs-bge-omneum-20261008": {
        "family": "frontier_llm_judges", "methods": ["bge_google", "bge_omneum"],
        "reason": "Completed low-thinking Gemini replay with generator-only recovery; original selections, successful generations and historical Omneum baseline are preserved and all final answers adjudicated.",
        "evidence": ["analysis/bge-google-low-vs-bge-omneum-20261008/report.md"],
    },
    "cohere-claude-vs-cohere-omneum-20261008": {
        "family": "frontier_llm_judges", "methods": ["cohere_anthropic", "cohere_omneum"],
        "reason": "Additional final dedicated Cohere + Claude replacement experiment with identical shared reranks and saved all-answer semantic review; not a Cohere-only baseline.",
        "evidence": ["results/cohere-claude-vs-cohere-omneum-20261008/report.md", "EVIDENCE.md"],
    },
}
def publication_classification(run):
    if run["status"] != "completed":
        return run["status"].replace("_only", ""), "No complete benchmark schedule"
    if run["id"] in PUBLICATION_RUNS:
        return "authoritative", PUBLICATION_RUNS[run["id"]]["reason"]
    return "historical", "Outside the publication evidence contract"


def apply_publication_authority(data):
    by = {c["id"]:c for c in data["configurations"]}
    evidence = publication_contract()
    lineage = evidence["lineage_audit"]
    timeline = lineage["git_snapshots"]
    diagnostic = json.loads((BASE/"results/diagnostic-tied-maxima-selection-only-20261007/selection_only_diagnostic.public-v1.json").read_text())
    protected = diagnostic["protected_sha256"]
    for name in ("omneum/inference.py", "omneum/dependency.py"):
        matches = [s["revision"] for s in timeline if s["source_file_sha256"].get(name) == protected.get(name)]
        require(matches == lineage["tied_diagnostic"]["matching_git_revisions"][name], "Diagnostic source lineage changed")
    tie_rows = [json.loads(line) for line in (BASE/"results/bge-omneum-tied-maxima-20261007/results.jsonl").read_text().splitlines()]
    tied_by_case = {r["case_id"]:r for r in tie_rows if r["method"]=="bge_omneum"}
    diagnostic_cases = {r["case_id"]:r for r in diagnostic["per_case"]}
    require(set(tied_by_case)==set(diagnostic_cases) and all(set(r["selected"])==set(diagnostic_cases[c]["bge_omneum_selected_ids"]) for c,r in tied_by_case.items()), "Paid tied-maxima run does not reproduce preserved diagnostic memberships")
    matches = {}
    for run_id in ("bge-claude-vs-bge-omneum-20261008", "bge-openai-vs-bge-omneum-20261008", RUN):
        rows = [json.loads(line) for line in (BASE/"results"/run_id/"results.jsonl").read_text().splitlines()]
        omneum_rows = [r for r in rows if r["method"]=="bge_omneum"]
        matches[run_id] = {"matching_selected_sets":sum(set(r["selected"])==set(tied_by_case[r["case_id"]]["selected"]) for r in omneum_rows), "attempts":len(omneum_rows)}
        require(matches[run_id]["matching_selected_sets"]==len(omneum_rows), "Later Omneum source sets differ from tied-maxima reference")
    for run in data["runs"]:
        classification, reason = publication_classification(run)
        run.update(publication_status=classification, publication_reason=reason)
        d = BASE/"results"/run["id"]
        run["source_paths"] = [str(p.relative_to(ROOT)) for p in sorted(d.iterdir()) if p.is_file() and p.name!='.run.lock']
        run["recorded_evaluation_metrics"] = json.loads((d/"summary.json").read_text()) if (d/"summary.json").exists() else None
        if public_manifest(d).exists():
            m=json.loads(public_manifest(d).read_text())
            snap = next(s for s in timeline if s["revision"] == m["git"]["commit"])
            run["git"] = m["git"]
            run["dependency_estimator"] = m.get("estimator")
            run["models"] = m["models"]
            run["method_names"] = [s["name"] for s in m["checkpoint_contract"]["methods"]]
            run["case_count"] = len({Path(p).parent.name for p in m["inputs"]})
            run["implementation_lineage"] = {
                "manifest_fingerprint":m["checkpoint_contract"]["implementation"],
                "commit_snapshot":snap,
                "fingerprint_matches_committed_tree": m["checkpoint_contract"]["implementation"]==snap["committed_implementation_sha256"],
                "execution_braid_version":None, "execution_selector_version":None,
                "confidence":"Dirty execution checkout: committed algorithm declaration is a reference, not proof of exact executed source",
            }
            # Use UTC-aware comparison; source snapshot chronology is distinct from revision ancestry.
            run["implementation_lineage"]["preceded_fix_commit_by_timestamp"] = [s["revision"] for s in timeline
                if s["revision"].startswith(("b6450c0", "0d50f2e"))
                and datetime.fromisoformat(m["timestamp_utc"]) < datetime.fromisoformat(s["timestamp_utc"])]
            run["versions"] = {"declared_braid_at_git_revision":snap["braid_version"],
                               "dependency_estimator":m.get("estimator", {}).get("estimator_version"), "selector_execution_version":None}
        else:
            run["git"] = None;run["versions"] = None;run["implementation_lineage"] = None
            run["component_manifests"] = [{"path":str(p.relative_to(ROOT)), "manifest":json.loads(p.read_text())}
                                           for p in sorted(d.glob("manifest.*.json"))]
        for cid in run["configuration_ids"]:
            by[cid]["publication_status"] = classification
    publication_tables = {"semantic_rerankers":[],"frontier_llm_judges":[]}
    pairs=[]
    for run_id, authority in PUBLICATION_RUNS.items():
        info=next(r for r in data["runs"] if r["id"]==run_id)
        require(info["status"]=="completed" and info["case_count"]==24, "Publication run lacks complete held-out coverage")
        require(info["method_names"]==authority["methods"], "Publication run arms differ from reviewed evidence")
        ids = [method if run_id==RUN else f"{run_id}:{method}" for method in authority["methods"]]
        require(all(by[cid]["run_id"]==run_id for cid in ids), "Mixed-run publication pair")
        pair={"run_id":run_id,"configuration_ids":ids,"family":authority["family"],"reason":authority["reason"],
              "evidence_paths":[str((BASE/p).relative_to(ROOT)) for p in authority["evidence"]]}
        pairs.append(pair)
        corrected = None
        if run_id=="20261008T014713Z":
            from .latency_analysis import analyze, read_jsonl
            d=BASE/"results"/run_id
            corrected=analyze(read_jsonl(d/"results.jsonl"),read_jsonl(d/"cohere_responses.jsonl"))
            require(not corrected["warnings"], "Cohere recorded timing correction cannot be validated")
        for cid in ids:
            c=by[cid]
            semantic=c["outcomes"]["complete_answer_accuracy"]["rate"]
            latency=c["latency_seconds"]
            basis=("original selection plus recovered generation stage durations, including refusals; non-contemporaneous E2E sums" if run_id == RUN else "recorded full selection; end-to-end is measured selection + generation, including refusals")
            if corrected:
                metrics=corrected["metrics"][c["method_id"]]
                latency={"selection":{k:metrics["corrected_selection"][k] for k in ("p50","p95")},
                         "end_to_end":{k:metrics["corrected_end_to_end"][k] for k in ("p50","p95")}}
                basis="Preserved within-run shared-response correction (LATENCY_ANALYSIS.md); not new timing measurements"
            publication_tables[authority["family"]].append({"configuration_id":cid,"label":c["label"],"source_run":run_id,
                "attempts":c["attempts"],"accuracy":semantic if semantic is not None else c["recorded_answer_scores"]["accuracy"],
                "accuracy_basis":"manual complete-answer adjudication" if semantic is not None else "recorded substring accuracy; semantic accuracy unavailable",
                "precision":c["selection"]["macro"]["precision"],"recall":c["selection"]["macro"]["recall"],
                "selection_scored_attempts":c["measurement_coverage"]["selection_scores"],
                "selection_p50_seconds":latency["selection"]["p50"],"selection_p95_seconds":latency["selection"]["p95"],
                "end_to_end_p50_seconds":latency["end_to_end"]["p50"],"end_to_end_p95_seconds":latency["end_to_end"]["p95"],
                "latency_basis":basis,"api_tokens":c["api_tokens"]["total"]["total"],
                "estimated_api_cost_usd":c["cost_usd"]["estimated_api_total"]})
    data["leaderboards"] = {family:{"configuration_ids":[r["configuration_id"] for r in rows],
        "comparator_configuration_ids":[r["configuration_id"] for r in rows if by[r["configuration_id"]]["configuration_kind"]=="omneum_augmented"],
        "reference_configuration_ids":[]} for family,rows in publication_tables.items()}
    data["publication"] = {"authority_scope":"Best preserved matched evidence for the declared publication configurations, not a validation of today's default selector or an exact dirty execution snapshot",
        "selection_policy":"Explicit evidence-reviewed pair allowlist; never first entry, newest timestamp alone, or highest score",
        "pairs":pairs,"tables":publication_tables,
        "unverified_claims":["No preserved final BGE-only pairing establishes higher Omneum answer accuracy: tied-maxima substring correct is 21/24 versus BGE 22/24. Semantic complete-answer accuracy is unavailable for that run."]}
    publication_ids = [row["configuration_id"] for rows in publication_tables.values() for row in rows]
    data["configurations"] = [by[cid] for cid in publication_ids]
    data["lineage_audit"] = lineage
    require(len(tied_by_case) == lineage["tied_diagnostic"]["paid_tied_memberships_verified"], "Tied diagnostic coverage changed")
    require(matches == lineage["tied_diagnostic"]["later_run_membership_matches"], "Later memberships changed")
    data["publication_contract"] = {
        "version": 1, "path": "benchmarks/context_evaluation/publication_manifest_v1.json",
        "scope": evidence["scope"],
        "original_dashboard_sha256": evidence["original_dashboard_sha256"],
        "verification_limit": "Public manifest projections are verified against their own hashes. Original manifest bytes and absolute identifiers remain private; their recorded hashes and execution fingerprints are retained, not reconstructed from public projections. Git lineage snapshots are preserved reference metadata, not exact dirty execution source.",
    }
    serialized = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    require(hashlib.sha256(serialized(data["configurations"])).hexdigest() == evidence["configuration_sha256"], "Authoritative configuration objects changed")
    require(hashlib.sha256(serialized(publication_tables)).hexdigest() == evidence["publication_tables_sha256"], "Published metric values changed")
    data["schema_version"]="2.0.0"
    data["comparability"]["policy"]="Main views contain only declared authoritative matched experiments. Compare each pair within its run and declared accuracy/coverage/latency basis; historical records and reused baselines are never pooled."
    data["definitions"]["latency"] += " Missing top-level end-to-end values are reconstructed only when both measured stage durations are present, matching the preserved summaries. Publication-only cached Cohere correction uses its original shared response records."
    for path in ("EVIDENCE.md","LATENCY_ANALYSIS.md","checkpoint.py","latency_analysis.py"):
        p=BASE/path;data["source_file_sha256"][str(p.relative_to(ROOT))]=sha(p)
    data["source_file_sha256"]=dict(sorted(data["source_file_sha256"].items()))
    return data

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true", help="Read-only: require output to match deterministic rebuild")
    args = parser.parse_args()
    data = json.dumps(build_summary(), indent=2, allow_nan=False) + "\n"
    if args.check:
        require(args.output.read_text() == data, "Dashboard summary is stale")
    else:
        # Only the new dashboard artifact may be written inside heldout; historical files are protected.
        path = args.output.resolve()
        require(not path.is_relative_to(ROOT) or path == OUTPUT, "Cannot overwrite repository files other than the dashboard summary")
        path.write_text(data)
    print(f"{'Verified' if args.check else 'Wrote'} {args.output}")


if __name__ == "__main__":
    main()
