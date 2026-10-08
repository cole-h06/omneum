"""Offline analysis only. Reads frozen inputs; writes separate analysis artifacts."""
import collections
import hashlib
import json
import math
from pathlib import Path
import re
import statistics as st

OUT = Path(__file__).resolve().parent
BASE = OUT.parents[1]
ROOT = BASE.parents[2]
RESULTS = BASE / "results" / OUT.name
METHODS = ("bge_openai", "bge_omneum")
files = [RESULTS / name for name in ("manifest.json", "summary.json", "results.jsonl")]
before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
rows = [json.loads(line) for line in files[2].read_text().splitlines()]
manifest = json.loads(files[0].read_text())
cases = sorted({r["case_id"] for r in rows})
by = {(r["case_id"], r["trial"], r["method"]): r for r in rows}
assert len(rows) == len(by) == 480 and len(cases) == 24
truths = {c: json.loads((BASE / "cases" / c / "ground_truth.json").read_text()) for c in cases}
inputs = {c: json.loads((BASE / "cases" / c / "case.json").read_text()) for c in cases}


def norm(s):
    return " ".join(re.sub(r"[^\w\s]", " ", s.lower()).split())


def manual(r):
    c, m, t = r["case_id"], r["method"], r["trial"]
    if c == "support_stale_runbook":
        return "generator_refusal", "Explicit Anthropic stop_reason=refusal; empty content; no answer to assess."
    if c == "research_independent_false_consensus" and m == "bge_omneum":
        return "incorrect", "Answers 240 occupied homes; census reference is 216. Caveats acknowledge missing census evidence but still give the wrong answer."
    if c == "support_resolution_conflict" and m == "bge_openai" and t not in (3, 4):
        return "partial", "Correct rollback action and retained TLS verification, but explicitly cannot identify tb17; selected context lacks that revision."
    if r["answer_score"] == "unscored":
        reason = {
            "coding_package_fix_lineage": "Correct bounding and eviction fix with reuse enabled; inflected/rephrased wording fails exact required substrings.",
            "multi_agent_independent_error": "Correct 120-second delay; normalized 120-second is not required substring 120 seconds.",
            "support_resolution_conflict": "Correct tb18-to-tb17 rollback and keeping upstream_tls_verify enabled; wording lacks required substring verification.",
        }[c]
        return "correct", reason
    return "correct", "Main answer matches the frozen reference in meaning; recorded correct answer retained after semantic review."


audit = []
for r in rows:
    status, reason = manual(r)
    truth = truths[r["case_id"]]
    if r["answer_score"] != "generation_failure":
        s = norm(r["answer"])
        rule = truth["scoring"]
        score = ("incorrect" if any(norm(v) and norm(v) in s for v in rule["forbidden"])
                 else "correct" if all(norm(v) and norm(v) in s for v in rule["required"])
                 else "unscored")
        assert score == r["answer_score"]
    audit.append({"case_id": r["case_id"], "method": r["method"], "trial": r["trial"],
                  "recorded_score": r["answer_score"], "manual_status": status,
                  "reason": reason, "reference_answer": truth["answer"],
                  "selected": r["selected"], "answer": r["answer"],
                  "failure_type": r.get("failure_type"),
                  "generator_diagnostics": r["generation"]["response_diagnostics"]})

checks = collections.Counter()
same_set = same_order = 0
for c in cases:
    for t in range(1, 11):
        a, o = (by[c, t, m] for m in METHODS)
        assert a["selection"]["bge_relevance"] == o["selection"]["bge_relevance"]
        checks["identical_paired_bge_results"] += 1
        same_set += set(a["selected"]) == set(o["selected"])
        same_order += a["selected"] == o["selected"]
        for r in (a, o):
            s = r["selection"]
            short = s["bge_relevance"]["selected"]
            assert hashlib.sha256(json.dumps(short, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == s["bge_shortlist_hash"]
            checks["shortlist_hashes"] += 1
            assert len(short) == min(len(inputs[c]["candidates"]), 2 * inputs[c]["context_budget"])
            assert len(r["selected"]) == len(set(r["selected"])) == inputs[c]["context_budget"]
            assert set(r["selected"]) <= {d["source"] for d in short}
            checks["selection_contracts"] += 1
            context = "\n\n".join(f"Source: {d['source']}\n{d['text']}" for d in s["selected"])
            prompt = f"Answer the question using only the sources below.\n\nQuestion:\n\n{inputs[c]['question']}\n\nSources:\n\n{context}\n\nGive a concise answer and identify which sources support it.\n"
            payload = {"provider": "anthropic", "model": "claude-sonnet-5-5", "prompt": prompt,
                       "max_tokens": 1024, "response_schema": None}
            h = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
            assert h == r["generation"].get("request_hash", r.get("generation_request_hash"))
            checks["generation_request_hashes"] += 1
            assert r["generation"]["provider"] == "anthropic" and r["generation"]["model"] == "claude-sonnet-5-5"
            judge = s["evaluator_latency_seconds"] if r["method"] == "bge_openai" else s["omneum_latency_seconds"]
            assert math.isclose(s["latency_seconds"], s["bge_latency_seconds"] + judge)
            assert math.isclose(r["end_to_end_latency_seconds"], s["latency_seconds"] + r["generation"]["latency_seconds"])
            checks["latency_reconciliations"] += 1
            expected = set(truths[c]["supporting_sources"])
            tp = len(set(r["selected"]) & expected)
            score = r["selection_score"]
            assert (tp, len(set(r["selected"]) - expected), len(expected - set(r["selected"]))) == (score["true_positive"], score["false_positive"], score["false_negative"])
            checks["selection_scores"] += 1
for path, h in manifest["inputs"].items():
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == h
    checks["frozen_input_hashes"] += 1


def percentile(values, q):
    a = sorted(values)
    pos = (len(a) - 1) * q
    lo = int(pos)
    return a[lo] + (a[min(lo + 1, len(a) - 1)] - a[lo]) * (pos - lo)


def metrics(rr):
    scores = collections.Counter(r["answer_score"] for r in rr)
    verified = collections.Counter(manual(r)[0] for r in rr)
    tp, fp, fn = (sum(r["selection_score"][k] for r in rr) for k in ("true_positive", "false_positive", "false_negative"))
    ei = sum(r["selection"]["evaluator_input_tokens"] for r in rr)
    eo = sum(r["selection"]["evaluator_output_tokens"] for r in rr)
    gi = sum(r["generation"]["input_tokens"] for r in rr)
    go = sum(r["generation"]["output_tokens"] for r in rr)
    return {"n": len(rr), "recorded": dict(scores), "manual": dict(verified),
            "precision": st.mean(r["selection_score"]["precision"] for r in rr),
            "recall": st.mean(r["selection_score"]["recall"] for r in rr),
            "micro_precision": tp / (tp + fp), "micro_recall": tp / (tp + fn),
            "tp": tp, "fp": fp, "fn": fn,
            "selection_p50": st.median(r["selection"]["latency_seconds"] for r in rr),
            "selection_p95": percentile([r["selection"]["latency_seconds"] for r in rr], .95),
            "e2e_p50": st.median(r["end_to_end_latency_seconds"] for r in rr),
            "e2e_p95": percentile([r["end_to_end_latency_seconds"] for r in rr], .95),
            "generator_p50": st.median(r["generation"]["latency_seconds"] for r in rr),
            "openai_input": ei, "openai_output": eo, "anthropic_input": gi, "anthropic_output": go,
            "openai_usd": (ei * 10 + eo * 50) / 1e6,
            "anthropic_usd": (gi * 2 + go * 10) / 1e6,
            "total_usd": (ei * 10 + eo * 50 + gi * 2 + go * 10) / 1e6}


aggregates = {m: metrics([r for r in rows if r["method"] == m]) for m in METHODS}
per_case = {c: {m: metrics([r for r in rows if r["case_id"] == c and r["method"] == m]) for m in METHODS} for c in cases}
per_trial = {t: {m: metrics([r for r in rows if r["trial"] == t and r["method"] == m]) for m in METHODS} for t in range(1, 11)}
a, o = (aggregates[m] for m in METHODS)
savings = {"selection_median_percent": 100 * (1 - o["selection_p50"] / a["selection_p50"]),
           "end_to_end_median_percent": 100 * (1 - o["e2e_p50"] / a["e2e_p50"]),
           "api_cost_percent": 100 * (1 - o["total_usd"] / a["total_usd"]),
           "api_token_percent": 100 * (1 - (o["anthropic_input"] + o["anthropic_output"]) / (a["openai_input"] + a["openai_output"] + a["anthropic_input"] + a["anthropic_output"]))}
(OUT / "comparison.json").write_text(json.dumps({"aggregates": aggregates, "per_case": per_case, "per_trial": per_trial,
    "savings": savings, "integrity_checks": checks, "same_selected_set_pairs": same_set,
    "same_order_and_generation_prompt_pairs": same_order, "source_file_sha256": before}, indent=2) + "\n")
(OUT / "answer_audit.json").write_text(json.dumps(audit, indent=2) + "\n")

intro = """This is a read-only analysis of 480 saved records: 24 cases × 10 trials × 2 selection arms. GPT-6 Astra and Omneum select context after shared BGE; Claude Sonnet 5.5 generates every answer in both arms. This does not compare their abilities as answer generators. No API calls were made.

The original recorded accuracy is tied at 209/240 (87.08%). Semantic review gives 222 fully reference-complete answers for Astra and 220 for Omneum. Astra additionally has eight correct but incomplete rollback answers (they omit tb17), yielding 230 operationally correct answers if these receive credit. Omneum has ten substantive false-consensus errors, all on the same case. Both arms have ten explicit generator refusals on support_stale_runbook. No full abstentions were identified; Omneum's census caveats still accompany a wrong numeric answer.

Verified complete answer accuracy is **Astra 92.50% (222/240)** and **Omneum 91.67% (220/240)**. Median selection latency reduction is **81.26%**, median end-to-end latency reduction is **49.00%**, and estimated total API cost reduction is **66.91%**. This demonstrates **comparable observed accuracy, not statistical equivalence**.

Publication normalization replaces machine-specific absolute input paths in the manifest with repository-relative paths. All input hashes, configuration values, and raw result/summary bytes are retained. The original pre-normalization manifest SHA-256 was 512a34c35813bdbfb9d795a7262251ca0dcf41ed2ae48cf19b3818166f6bc493. Analysis source-artifact paths are also repository-relative; the hashes below describe the published files.

Semantic assessment concerns the requested answer and essential conditions; it is not an independent blinded human-panel assessment or an exhaustive score for every ancillary sentence and citation. Manual labels are separate analysis annotations and do not replace frozen scores.

Every unscored record and generation failure is reproduced and adjudicated below. The 20 package-fix answers correctly describe bounding/eviction while keeping reuse; exact substring matching misses inflected wording. Astra Retry-After trials 3, 7, 10 correctly say 120-second rather than the required 120 seconds. Omneum TLS trial 7 correctly rolls back to tb17 and retains upstream_tls_verify, but lacks the substring verification. Astra TLS trials 1, 2, 5–10 omit tb17 because their selected sources do not identify it; these are partial answers, not wholly incorrect answers and not mere synonym mismatches. Omneum census trials 1–10 answer 240 instead of 216; the correct dataset and census summary were available in BGE's shortlist but were discarded.

Selection precision/recall use the frozen supporting-source labels. Macro means weight each record equally; micro scores pool TP/FP/FN. Those labels can exclude useful diagnostic context: service_state is not a labeled supporting source in the TLS case despite explaining the failure. Recall is also budget-limited: the average theoretical case-budget ceiling is 71.14%, and the shared-shortlist ceiling is 66.28%. Recall against all supporting sources is not a measure of whether enough evidence exists to answer.

All 240 paired BGE results match exactly, including IDs, order, texts, scores, and duration. All 480 shortlist hashes, context-budget/subset contracts, generation request hashes, selection scores, and latency sums validate. All 48 case/reference file hashes match the manifest. Identical generation settings reconstructed from all hashes are Anthropic claude-sonnet-5-5, the common question/source prompt, max_tokens=1024, and no response schema. Actual prompts differ when source order or membership differs: 112 pairs share selected sets and 72 share exact source order and request hashes. Current client code sets no explicit temperature, seed, thinking, or effort overrides.

Two integrity qualifications: (1) Omneum uses structured claims/provenance plus recursively relevant dependency observations, whereas Astra's judge prompt contains shortlist text and IDs. The shortlist and answer-generation controls are matched, but judge information is not identical. No ground-truth source labels enter current selector code. (2) The manifest records a dirty checkout at commit 66f9b5552d13943193f3b92b66ddb348b84eb25a. Saved implementation fingerprint cefc953e9e029ef8a8e58994e887de8eac2923062abbf6c2c4aef456b91a6394 differs from checkout fingerprint ca26fec535a2741eb12a3efbe3b1a66187460f0890b75906491432b8ebeb6c6a, computed before these analysis artifacts were created. Current source explains the observed contracts but is not a verified execution-time snapshot. Request hashes establish the encoded settings, not undocumented server defaults. Current suite code schedules all ten Astra trials before the ten Omneum trials within each case, rather than randomizing/interleaving arms; timing can reflect temporal service variation.

Costs use standard short-context USD rates per million tokens: Astra $10 input/$50 output, Sonnet 5.5 $2 input/$10 output, verified October 8, 2026 in [OpenAI's model documentation](https://developers.openai.com/api/docs/models/gpt-6-astra) and [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing). Saved inference_cost fields are unavailable; these are estimates, not invoices. Astra cached input is zero. Its 9,194 reasoning tokens are included in 14,699 output tokens and must not be billed twice. Claude reasoning-token metadata is null, not an established zero. All 480 generator calls have token telemetry; refusal input tokens are included. Local BGE/Omneum compute and hosting, account discounts, tier or region adjustments, and any unlogged transport retries are excluded. No prompt-cache controls are set in the current client code.

Median selection includes shared BGE and each selector's full measured duration, including Omneum integration. Omneum's core evaluator median is 30.66 ms, but the full pipeline selection median is 640.89 ms; do not advertise the core timing as total latency. End-to-end is selection plus that arm's independent generation call. Percentiles use linear interpolation at (n−1)q and include refusals. Local models are warmed by current runner code.

Omneum has identical ordered selections across all ten trials in every case. Astra has 17 cases with identical ordered selections, 20 with identical sets; seven cases vary in order and four in membership. Membership varies in research_conflicting_reports, research_independent_false_consensus, support_resolution_conflict, and support_ticket_reference_loop. Omneum is faster on selection in 240/240 pairs and end-to-end in 239/240 pairs; every per-case median improves. Deterministic consistency includes consistently wrong census selection and is not proof of correctness.

The ten repetitions are clustered within 24 fixed synthetic cases, not 240 independent tasks. Under full-reference correctness, Astra wins 10 paired observations (the census case), Omneum wins eight (TLS completeness), and 222 tie; the net difference is only two answers, but no noninferiority margin or representative sample establishes general equivalence. Under operational credit for partial TLS answers, Astra leads by one case, repeated ten times. A trial-level significance test would exaggerate the evidence by treating repeats as independent.

Omneum is competitive on most cases and much cheaper/faster in this controlled selection experiment. It is not a demonstrated accuracy-equivalent replacement: it has lower selection precision/recall and a persistent independent-false-consensus failure. It also provides more specific TLS rollback context than Astra usually selects. The shared refusal case provides no evidence favoring either selector.
"""
lines = [intro, "\nAggregate comparison\n", "| Metric | BGE + Astra | BGE + Omneum |", "|---|---:|---:|"]
for label, key in [("Records", "n"), ("Macro precision", "precision"), ("Macro recall", "recall"), ("Micro precision", "micro_precision"), ("Micro recall", "micro_recall"), ("Selection median seconds", "selection_p50"), ("Selection p95 seconds", "selection_p95"), ("End-to-end median seconds", "e2e_p50"), ("End-to-end p95 seconds", "e2e_p95"), ("Generation median seconds", "generator_p50"), ("OpenAI input tokens", "openai_input"), ("OpenAI output tokens", "openai_output"), ("Anthropic input tokens", "anthropic_input"), ("Anthropic output tokens", "anthropic_output"), ("OpenAI estimated USD", "openai_usd"), ("Anthropic estimated USD", "anthropic_usd"), ("Total estimated USD", "total_usd")]:
    lines.append(f"| {label} | {a[key]:.6f} | {o[key]:.6f} |")
lines += [f"\nSavings: {json.dumps(savings)}. Total API tokens: 197,556 versus 115,119. Generator tokens increase 3.48%, output tokens increase 7.23%, and generator cost increases 5.97%. Eliminating Astra saves $1.451050 at the judge, offset by $0.039312 additional generation cost: net $1.411738 saved across 240 attempts. Estimated combined paired-run API cost: $2.808358.\n",
          "Per-case table: A = Astra, O = Omneum. C/U/F = recorded correct/unscored/generation failure. Manual full means complete against the reference; partial rollback answers remain separate. Every metric averages or takes the median over that case's ten trials.\n",
          "| Case | Recorded C/U/F A; O | Manual full A/O | Precision A/O | Recall A/O | Selection median s A/O | E2E median s A/O |",
          "|---|---|---:|---:|---:|---:|---:|"]
for c in cases:
    aa, oo = (per_case[c][m] for m in METHODS)
    counts = lambda z: "/".join(str(z["recorded"].get(k, 0)) for k in ("correct", "unscored", "generation_failure"))
    lines.append(f"| {c} | {counts(aa)}; {counts(oo)} | {aa['manual'].get('correct',0)}/{oo['manual'].get('correct',0)} | {aa['precision']:.4f}/{oo['precision']:.4f} | {aa['recall']:.4f}/{oo['recall']:.4f} | {aa['selection_p50']:.4f}/{oo['selection_p50']:.4f} | {aa['e2e_p50']:.4f}/{oo['e2e_p50']:.4f} |")
lines += ["\nPer-trial consistency\n", "| Trial | Recorded correct A/O | Manual full A/O | Macro precision A/O | Macro recall A/O | Selection median s A/O | E2E median s A/O | Estimated USD A/O |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
for t in range(1, 11):
    aa, oo = (per_trial[t][m] for m in METHODS)
    lines.append(f"| {t} | {aa['recorded']['correct']}/{oo['recorded']['correct']} | {aa['manual']['correct']}/{oo['manual']['correct']} | {aa['precision']:.4f}/{oo['precision']:.4f} | {aa['recall']:.4f}/{oo['recall']:.4f} | {aa['selection_p50']:.4f}/{oo['selection_p50']:.4f} | {aa['e2e_p50']:.4f}/{oo['e2e_p50']:.4f} | {aa['total_usd']:.6f}/{oo['total_usd']:.6f} |")
lines += ["\nSelection memberships by case and arm (ordered tuples and trial counts)\n"]
for c in cases:
    lines.append(f"\n**{c}**")
    for m in METHODS:
        counts = collections.Counter(tuple(r["selected"]) for r in rows if r["case_id"] == c and r["method"] == m)
        lines.append(f"\n{m}: " + "; ".join(f"{list(k)} × {v}" for k, v in counts.items()))
lines += ["\nIndividual audit of every unscored answer and generation failure (42 unscored + 20 refusals)\n"]
for record in audit:
    if record["recorded_score"] == "correct":
        continue
    lines += [f"\n**{record['case_id']} / {record['method']} / trial {record['trial']}**\n",
              f"Recorded: {record['recorded_score']}. Manual: {record['manual_status']}. {record['reason']}\n",
              f"Reference: {record['reference_answer']}\n",
              f"Selected: {', '.join(record['selected'])}\n",
              record["answer"] or f"Empty answer. Diagnostics: `{json.dumps(record['generator_diagnostics'])}`", "\n"]
lines += ["\nSource artifact SHA-256 hashes\n", "```json", json.dumps(before, indent=2), "```"]
(OUT / "report.md").write_text("\n".join(lines) + "\n")
assert before == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
print(json.dumps({"output": str(OUT), "integrity_checks": checks, "manual_counts": {m: aggregates[m]["manual"] for m in METHODS}, "savings": savings}, indent=2))
