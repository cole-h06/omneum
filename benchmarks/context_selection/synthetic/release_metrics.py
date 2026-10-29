"""Offline reporting of saved release benchmark records; no provider imports."""

from benchmarks.context_selection.paths import resolve_artifact
from .sdk_adapter import observation_chunk_pairs, claim_from_record


import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from statistics import mean
from types import SimpleNamespace

from .aggregate import _percentile
from .scoring import normalize, score_answer, score_answer_legacy, score_selection, ANSWER_GRADER_VERSION


BASE = Path(__file__).parent
DEFAULT_SOURCE = BASE / 'results/pre-release-context-v1'
METHODS = ('full', 'bm25', 'embedding', 'bge', 'cohere', 'claude', 'gpt',
           'omneum', 'bm25_omneum', 'embedding_omneum', 'bge_omneum')
COMPLETED = ('correct', 'incorrect', 'unscored')


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def distribution(values):
    samples = [v for v in values if finite(v) and v >= 0]
    return {'n': len(samples), 'missing': len(values) - len(samples),
            'mean': mean(samples) if samples else None,
            'sum': sum(samples) if samples else None,
            'p50': _percentile(samples, .5), 'p95': _percentile(samples, .95)}


def identity(row):
    return row['case_id'], row['allocated_budget'], row['trial']


def indexed(rows):
    result = {}
    for row in rows:
        key = identity(row)
        if key in result:
            raise ValueError(f'duplicate paired identity: {key}')
        result[key] = row
    return result


def paired(left, right, exact_tokens=False):
    a, b = indexed(left), indexed(right)
    keys = sorted(a.keys() & b.keys(), key=str)
    eligible = [k for k in keys if a[k]['answer_score'] in COMPLETED and b[k]['answer_score'] in COMPLETED]
    if exact_tokens:
        eligible = [k for k in eligible if finite(a[k].get('selected_tokens'))
                    and a[k]['selected_tokens'] == b[k].get('selected_tokens')]
    differences = [int(a[k]['answer_score'] == 'correct') - int(b[k]['answer_score'] == 'correct') for k in eligible]
    return {'pairs': len(eligible), 'wins': differences.count(1), 'losses': differences.count(-1),
            'ties': differences.count(0), 'left_correct': sum(a[k]['answer_score'] == 'correct' for k in eligible),
            'right_correct': sum(b[k]['answer_score'] == 'correct' for k in eligible),
            'unpaired_left': len(a.keys() - b.keys()), 'unpaired_right': len(b.keys() - a.keys()),
            'excluded_shared_pairs': len(keys) - len(eligible),
            'keys': [list(k) for k in eligible]}


def independent_mass(chunks, weights):
    # A repeated chunk from the same source and claim adds no independent mass.
    represented = {}
    for chunk in chunks:
        for claim in chunk['claim_ids']:
            item = weights[(chunk['source_id'], claim)]
            represented[(item['source_node_id'], claim)] = item['independence']
    return sum(represented.values())


def graph_references(source, rows, inputs):
    from omneum import Claim
    from omneum.context_selection import claim_id
    references = {}
    with sqlite3.connect(f'file:{source}/local/omneum.db?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        for row in rows:
            if not row.get('sdk_result') or row['case_id'] in references:
                continue
            case_id = row['case_id']
            data = inputs[case_id]
            run = row['execution_history']['evaluation_run_id']
            saved = {r['local_observation_id']: dict(r) for r in db.execute(
                'SELECT o.local_observation_id, o.source_id, s.independence '
                'FROM assertion_observation_envelopes o JOIN claim_support_sources s '
                'ON o.evaluation_run_id=s.evaluation_run_id AND o.claim_id=s.claim_id '
                'AND o.source_id=s.source_id WHERE o.evaluation_run_id=?', (run,))}
            weights = {}
            for observation, chunk in observation_chunk_pairs(data['assertion_observations'], data['chunks'], data['case']):
                item = saved[observation['observation_id']]
                for claim in [claim_id(claim_from_record(observation['claim']))]:
                    weights[(chunk['source_id'], claim)] = {
                        'observation_id': observation['observation_id'], 'source_node_id': item['source_id'],
                        'independence': item['independence']}
            references[case_id] = {'evaluation_run_id': run, 'weights': weights,
                                   'evaluation': row['sdk_result']['evaluation']}
    return references


def attempt_metrics(row, data, graph, line, *, grader_version=ANSWER_GRADER_VERSION):
    graders = {ANSWER_GRADER_VERSION: score_answer, "literal-v1": score_answer_legacy}
    if grader_version not in graders:
        raise ValueError("unknown answer grader version")
    chunks = data['chunks']
    by_id = {c['chunk_id']: c for c in chunks}
    ids = row.get('selected', [])
    if len(ids) != len(set(ids)) or any(k not in by_id for k in ids):
        raise ValueError('invalid selected chunk IDs')
    selected = [by_id[k] for k in ids]
    rendered = '\n\n'.join(f"[{c['chunk_id']}]\n{c['raw_text']}" for c in selected)
    completed = row.get('answer_score') in COMPLETED
    if completed and (rendered != row['context'] or row['context'] not in row['generator_prompt']):
        raise ValueError('saved generator evidence differs from original selected text')
    if completed:
        truth = SimpleNamespace(scoring=SimpleNamespace(**data['truth']['scoring']))
        if graders[grader_version](row['answer'], truth) != row['answer_score']:
            raise ValueError('frozen scorer result differs')
    original, tokens, budget = (row.get(k) for k in ('input_tokens', 'selected_tokens', 'allocated_budget'))
    for value in (original, tokens, budget):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError('token counts must be nonnegative integers')
    if budget is not None and tokens is not None and tokens > budget:
        raise ValueError('context exceeds token budget')
    sdk = row.get('sdk_result')
    if sdk:
        if sdk['context'] != rendered or sdk['packed_chunk_ids'] != ids:
            raise ValueError('SDK reconstruction mismatch')
        if sdk['evaluation'] != graph['evaluation']:
            raise ValueError('full-graph scores changed across SDK conditions')
        for field, expected in [('input_tokens', original), ('selected_tokens', tokens), ('token_budget', budget)]:
            if sdk['selection'][field] != expected:
                raise ValueError('SDK token metadata mismatch')
    truth = data['truth']
    required = set(truth['supporting_sources'])
    retained = {c['source_id'] for c in selected} & required
    required_chunks = [c for c in chunks if c['source_id'] in required]
    required_claims = {claim for c in required_chunks for claim in c['claim_ids']}
    claims = [claim for c in selected for claim in c['claim_ids']]
    all_claims = {claim for c in chunks for claim in c['claim_ids']}
    kept_mass = independent_mass([c for c in selected if c['source_id'] in required], graph['weights'])
    total_mass = independent_mass(required_chunks, graph['weights'])
    source_scores = score_selection({c['source_id'] for c in selected}, SimpleNamespace(supporting_sources=required))
    for name, value in source_scores.items():
        if row.get('selection_score', {}).get(name) != value:
            raise ValueError('saved supporting-passage score differs')
    # Claim IDs measure mapped coverage, while whole original passages establish text retention.
    # Neither metric establishes that a procedure or its qualifications are sufficient.
    result = {k: row.get(k) for k in ('case_id', 'arm', 'domain', 'trial', 'allocated_budget', 'answer_score',
        'generation_origin', 'reused_from', 'generator_input_tokens', 'generator_output_tokens',
        'rank_seconds', 'prepare_seconds', 'generation_seconds', 'end_to_end_seconds',
        'conflicting_chunks', 'off_task_claim_chunks')}
    result.update(record_line=line, answer_grader_version=grader_version, selected_chunk_ids=ids,
        input_tokens=original, selected_tokens=tokens,
        context_reduction=1 - tokens / original if original and tokens is not None else None,
        budget_utilization=ratio(tokens, budget) if tokens is not None else None,
        reconstruction_exact=completed, supporting_passages_retained=sorted(retained),
        supporting_passages_missing=sorted(required - retained),
        supporting_passage_recall=ratio(len(retained), len(required)),
        supporting_passage_precision=source_scores['precision'],
        all_annotated_supporting_passages_retained=required <= retained if required else None,
        required_claim_coverage=ratio(len(set(claims) & required_claims), len(required_claims)),
        distinct_claim_coverage=ratio(len(set(claims)), len(all_claims)), distinct_claims_retained=len(set(claims)),
        redundant_claim_occurrences=len(claims) - len(set(claims)),
        supporting_independence_mass_retained=kept_mass, supporting_independence_mass_total=total_mass,
        independent_support_coverage=ratio(kept_mass, total_mass),
        independent_support_reference_run=graph['evaluation_run_id'],
        complete_answer_bearing_evidence_retention=None, qualification_retention=None,
        complete_evidence_chain_retention=None)
    rank, prep, generation = (row.get(k) for k in ('rank_seconds', 'prepare_seconds', 'generation_seconds'))
    result['complete_selection_component_seconds'] = rank + prep if finite(rank) and finite(prep) else None
    component = result['complete_selection_component_seconds']
    result['end_to_end_component_seconds'] = component + generation if finite(component) and finite(generation) else None
    if row.get('selection_seconds') is not None and not math.isclose(row['selection_seconds'], component):
        raise ValueError('selection component sum mismatch')
    if row.get('component_sum_seconds') is not None and not math.isclose(row['component_sum_seconds'], result['end_to_end_component_seconds']):
        raise ValueError('end-to-end component sum mismatch')
    result['execution_history'] = row.get('execution_history')
    return result


def summarize(rows):
    evaluated = [r for r in rows if r['answer_score'] in COMPLETED]
    correct = sum(r['answer_score'] == 'correct' for r in evaluated)
    tokens = [r.get('selected_tokens') for r in evaluated]
    known_tokens = [v for v in tokens if finite(v)]
    # Include context spent on wrong answers; a zero-success batch has undefined efficiency.
    token_efficiency = sum(known_tokens) / correct if correct and len(known_tokens) == len(evaluated) else None
    result = {'attempts': len(rows), 'evaluated_answers': len(evaluated), 'correct': correct,
              'failures_or_missing': len(rows) - len(evaluated), 'accuracy': ratio(correct, len(evaluated)),
              'attempt_accuracy': ratio(correct, len(rows)), 'evidence_tokens_per_correct_answer': token_efficiency,
              'outcomes': dict(Counter(r['answer_score'] for r in rows))}
    for field in ('input_tokens', 'selected_tokens', 'context_reduction', 'budget_utilization',
        'supporting_passage_precision', 'supporting_passage_recall', 'required_claim_coverage',
        'distinct_claim_coverage', 'redundant_claim_occurrences', 'independent_support_coverage',
        'conflicting_chunks', 'off_task_claim_chunks', 'generator_input_tokens', 'generator_output_tokens',
        'rank_seconds', 'prepare_seconds', 'complete_selection_component_seconds', 'generation_seconds',
        'end_to_end_component_seconds', 'end_to_end_seconds',
        'complete_answer_bearing_evidence_retention', 'qualification_retention', 'complete_evidence_chain_retention'):
        result[field] = distribution([r.get(field) for r in rows])
    values = [r.get('all_annotated_supporting_passages_retained') for r in rows]
    known = [v for v in values if v is not None]
    result['complete_annotated_passage_set'] = {'n': len(known), 'retained': sum(known), 'rate': ratio(sum(known), len(known))}
    histories = [r.get('execution_history') or {} for r in rows]
    result['sdk_history'] = {k: distribution([h.get(k) for h in histories]) for k in (
        'sdk_end_to_end_latency_ms', 'evaluation_latency_ms', 'graph_evaluation_latency_ms',
        'mcp_roundtrip_latency_ms', 'chunk_selection_latency_ms', 'context_reconstruction_latency_ms',
        'local_inference_latency_ms', 'cpu_time_ms', 'peak_memory_bytes')}
    return result


def selector_cost(calls, method):
    selected = [r for r in calls if r['method'] == method]
    result = {'unique_selector_calls': len(selected), 'actual_paid_usd': None,
              'downstream_external_api_fee_usd': 0, 'local_compute_cost_usd': None,
              'hypothetical_local_api_equivalent_usd': None, 'list_price_estimate_usd': None}
    if method in ('claude', 'gpt'):
        if not selected:
            return result
        total = 0
        for row in selected:
            cached = ((row.get('usage_metadata') or {}).get('input_tokens_details') or {}).get('cached_tokens', 0)
            rate_in, rate_out, rate_cached = (2, 10, None) if method == 'claude' else (10, 50, 1)
            if cached and rate_cached is None:
                raise ValueError('no recorded price assumption for cached Claude input')
            total += ((row['input_tokens'] - cached) * rate_in + row['output_tokens'] * rate_out + cached * (rate_cached or 0)) / 1e6
        result.update(list_price_estimate_usd=total,
            selector_input_tokens=sum(r['input_tokens'] for r in selected),
            selector_output_tokens=sum(r['output_tokens'] for r in selected))
    elif method == 'cohere':
        result['billed_search_units'] = sum(r['billed_search_units'] for r in selected)
    else:
        result['selector_external_api_fee_usd'] = 0
    return result


def group_summary(rows, field):
    groups = defaultdict(list)
    for row in rows:
        if row[field] is not None:
            groups[(str(row[field]), row['arm'])].append(row)
    result = {}
    for (value, method), subset in sorted(groups.items()):
        result.setdefault(value, {})[method] = summarize(subset)
    return result


def table(headers, rows):
    lines = ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |']
    return '\n'.join(lines + ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows])


def show(value, digits=2):
    return 'unavailable' if value is None else f'{value:.{digits}f}'


def markdown(metrics, reviews, command):
    overall = metrics['overall']
    lines = ['# Context construction: metrics reanalysis', '',
        'Offline analysis of 2,928 saved attempts: 24 frozen cases, six budgets (64–256 tokens), two same-seed trials. '
        'No models or SDK evaluations were executed. Full context has 48 unbudgeted attempts; each other method has 288. '
        'Qwen2.5 7B Q4_K_M, temperature 0, seed 42, 8,192-token window, 256 output tokens; prompts and scorer are unchanged. '
        'This is a synthetic development-influenced regression set, not fresh held-out validation.', '',
        '## Definitions and traceability', '',
        'Accuracy is correct / completed answers; completed `unscored` responses remain in the denominator. '
        'Attempt accuracy also includes execution failures. Both denominators and missing-value coverage are saved. '
        'These are frozen substring-scorer results, not a new factual adjudication. '
        'Context tokens are the saved exact Qwen tokenizer counts of rendered original evidence, including headers and separators. '
        'Reduction is `1 - selected / original`, calculated per attempt and then averaged; zero input gives an undefined ratio. '
        'Evidence tokens per correct answer includes tokens spent on wrong answers.', '',
        'Supporting-passage recall checks annotated `supporting_sources` against complete original passages in the saved context. '
        'All selected text and order are verified against saved inputs and generator prompts. '
        'The complete annotated passage set is conservative: alternative sources are not necessarily all required. '
        'Required-claim coverage is distinct canonical claims mapped to annotated supporting passages. '
        'Independent-support coverage is retained / total independence-weighted source–claim mass among annotated supporting sources, '
        'deduplicated by graph source and claim, using one original full-graph SQLite run per case for every method. '
        'It is estimated independent mass, not a count of proven independent witnesses. '
        'None of these establishes sufficient procedural or qualified evidence.', '',
        '`metrics.json` contains definitions, all summaries and exact pairing identities. `attempt_metrics.jsonl` points to '
        'the original result line for every calculation. `graph_references.json` records source/claim mappings, weights and evaluation run IDs. '
        '`provenance.json` hashes source artifacts and frozen inputs. Existing Markdown and historical results remain unchanged.', '',
        '## Method comparison', '',
        'Equal nominal budgets, pooled over the same six budgets. Full context is separate and unbudgeted. '
        'Passage precision/recall are annotation-based, not answer sufficiency. No compression is described as lossless.', '']
    comparison = []
    for method in METHODS:
        v = overall[method]
        comparison.append([method, f"{v['correct']}/{v['evaluated_answers']} ({100*v['accuracy']:.2f}%)",
            show(v['selected_tokens']['mean']), show(100*v['context_reduction']['mean']),
            show(v['supporting_passage_precision']['mean']), show(v['supporting_passage_recall']['mean']),
            show(v['required_claim_coverage']['mean']), show(v['independent_support_coverage']['mean']),
            show(v['evidence_tokens_per_correct_answer'])])
    lines += [table(['Method', 'Accuracy', 'Context tokens', 'Reduction %', 'Passage precision', 'Passage recall',
                     'Required claim recall', 'Independent mass recall', 'Evidence tokens / correct'], comparison), '',
        '## Latency and generator usage', '',
        'All percentiles use linear interpolation at `(n - 1) * q`, excluding missing/nonfinite values. '
        'Ranker times for BM25, embedding and BGE are historical measurements reused from `retriever-native-v1`; '
        'their current-run fresh relevance work is zero. Cohere/Claude/GPT ranking times are fresh shared calls reused across budgets '
        '(Cohere also across trials). Preparation is measured packing/SDK plus harness validation/history lookup; '
        'hybrid preparation excludes external relevance scoring. Complete selection below is the per-attempt sum of ranker + preparation; '
        'E2E is selection + recorded generation. These sums are not directly measured contiguous wall clocks. '
        'Direct E2E is unavailable for all methods. SDK substage timers are nested, not additive extras. '
        'Do not interpret repeated shared timings as independent latency samples.', '']
    latency = []
    for method in METHODS:
        v = overall[method]
        cells = [method]
        for field, scale in [('rank_seconds', 1000), ('prepare_seconds', 1000),
            ('complete_selection_component_seconds', 1000), ('generation_seconds', 1), ('end_to_end_component_seconds', 1)]:
            cells.append('/'.join(show(v[field][q] * scale if v[field][q] is not None else None) for q in ('p50', 'p95')))
        cells.append(show(v['generator_input_tokens']['mean'], 1) + '/' + show(v['generator_output_tokens']['mean'], 1))
        latency.append(cells)
    lines += [table(['Method', 'Rank p50/p95 ms', 'Prep/check p50/p95 ms', 'Selection sum p50/p95 ms',
                     'Generation p50/p95 s', 'E2E sum p50/p95 s', 'Gen input/output tokens'], latency), '',
        'Generation duration and usage retain their recorded origin: ' + json.dumps(metrics['generation_origins'], sort_keys=True) + '. '
        'Cache state was uncontrolled and the fresh subset is unbalanced across methods. Some preparation overlapped regression tests; '
        'model startup/warmup is excluded. Current SDK recheck timings are a separate later phase in `metrics.json`; '
        'they are not substituted into the original cohort.', '',
        '### SDK execution history', '',
        'CPU is `sdk_process_during_evaluation`, excluding MCP/generator processes and later packing. '
        'RSS is `sdk_process_lifetime_peak_rss`, including loaded benchmark caches; it is not per-request allocation. '
        'Measured server graph, transport, selection, reconstruction and local verification distributions remain in the JSON.', '',
        table(['Method', 'CPU p50/p95 ms', 'Lifetime peak RSS max MiB'], [[m,
            '/'.join(show(overall[m]['sdk_history']['cpu_time_ms'][q]) for q in ('p50', 'p95')),
            show(metrics['sdk_peak_rss_max_bytes'][m] / 2**20)] for m in METHODS if metrics['sdk_peak_rss_max_bytes'][m] is not None]), '',
        '## Evidence quality and efficiency', '',
        table(['Method', 'Distinct claim recall', 'Repeated occurrences', 'Complete annotated passage sets', 'Budget use %'], [[m,
            show(overall[m]['distinct_claim_coverage']['mean']), show(overall[m]['redundant_claim_occurrences']['mean']),
            str(overall[m]['complete_annotated_passage_set']['retained']) + '/' + str(overall[m]['complete_annotated_passage_set']['n']),
            show(100*overall[m]['budget_utilization']['mean']) if overall[m]['budget_utilization']['mean'] is not None else 'unbudgeted'] for m in METHODS]), '',
        'Whole-passages are preserved exactly, but the frozen annotations do not define necessary exception spans or complete multi-hop packets. '
        'Consequently complete answer-bearing evidence retention, qualification retention and chain retention remain null rather than being inferred from claim IDs. '
        'The inspected examples below show why this distinction matters.', '',
        '## Accuracy by nominal token budget', '']
    for field, title in [('by_budget', 'budget'), ('by_domain', 'domain')]:
        lines += [table([title, *METHODS[1:]], [[k, *[f"{v[m]['correct']}/{v[m]['evaluated_answers']}" for m in METHODS[1:]]]
            for k, v in sorted(metrics[field].items(), key=lambda item: int(item[0]) if field == 'by_budget' else item[0])]), '']
        if field == 'by_budget':
            lines += ['## Accuracy by domain', '']
    lines += ['Full-context domain breakdowns, token distributions and all budget/domain metrics are also in the machine-readable summary.', '',
        '## Paired comparisons with BGE', '',
        table(['Method', 'Nominal W/L/T', 'Exact nominal token pairs', 'Exact subset W/L/T'], [[m,
            '/'.join(str(metrics['paired_nominal'][m][k]) for k in ('wins', 'losses', 'ties')),
            metrics['paired_exact_nominal'][m]['pairs'],
            '/'.join(str(metrics['paired_exact_nominal'][m][k]) for k in ('wins', 'losses', 'ties'))] for m in METHODS[1:] if m != 'bge']), '',
        'Pairs align case, nominal budget and trial. Exact comparisons additionally require identical actual evidence tokens. '
        'Both-wrong pairs are ties only in binary scorer outcome. Exact subsets are selected cohorts, not all-case estimates. '
        'The full-context arm is not replicated six times or compared as budgeted.', '',
        '### Secondary exact-token BGE controls', '',
        'The saved secondary BGE control maximizes summed BGE score over exhaustive whole-chunk subsets at exactly the target token count, '
        'then renders in BGE order. This differs from normal BGE first-fit packing. No approximate matches are included.', '',
        table(['Target', 'Exact pairs', 'Unmatchable', 'Target correct', 'BGE correct', 'W/L/T'], [[m, v['pairs'], v['unmatchable'],
            v['left_correct'], v['right_correct'], '/'.join(str(v[k]) for k in ('wins', 'losses', 'ties'))]
            for m, v in metrics['paired_exact_controls'].items()]), '',
        'Equal accuracy counts do not establish statistical equivalence. `accuracy_vs_actual_tokens` groups observations by exact consumption '
        'for plotting; these groups generally contain different cases and are descriptive curves, not controlled matched comparisons.', '',
        '## Cost', '',
        table(['Method', 'Unique paid-selector calls', 'Selector list-price estimate USD', 'Billed search units', 'Actual expenditure USD'], [[m,
            v['unique_selector_calls'], show(v['list_price_estimate_usd'], 6), v.get('billed_search_units', 'n/a'), 'unavailable']
            for m, v in metrics['costs'].items()]), '',
        'Provider call costs are counted once, not multiplied across six budgets or cached answers. '
        'Claude and GPT estimates reuse the original recorded price assumptions: Claude $2/M input, $10/M output; '
        'GPT $10/M uncached input, $1/M cached input, $50/M output. No price was fetched or updated during reanalysis. '
        'Cohere has 24 billed search units but no verified v4 Pro tariff. Invoices, credits and negotiated discounts are absent. '
        'Actual total API expenditure is therefore unavailable. Qwen and local rankers have no external API charge; '
        'hardware/energy cost and hypothetical API-equivalent cost are unmeasured. Cost is not reported as zero total compute cost. '
        'Generator usage includes logical reused attempts, not 2,928 newly paid generation calls. Price source URLs and scope are in the JSON.', '',
        '## Inspected reconstruction and answer examples', '']
    for review in reviews:
        lines += [f"### {review['case_id']} — {review['budget']} tokens, trial {review['trial']}", '',
            review['observation'], '', 'Frozen answer: ' + review['expected'], '']
        for condition in review['conditions']:
            if condition['arm'] not in ('omneum', 'bge'):
                continue
            lines += [f"**{condition['arm']}** — `{', '.join(condition['selected'])}`; frozen grade `{condition['answer_score']}`.", '',
                '```text', condition['context'], '```', '', 'Model response:', '', condition['answer'], '']
    lines += ['These are post-hoc inspections, not new gold labels. `case_reviews.json` and source pointers preserve their original annotations. '
        'The config and stale-runbook failures omit answer-bearing text despite exact reconstruction. '
        'The package-lineage response illustrates an inflection/substring grading artifact; no frozen score is changed.', '',
        '## Missing measurements and minimal collection', '',
        table(['Metric', 'Affected records', 'Required action', 'Command availability'], [[g['metric'], len(g['affected_attempts']),
            g['collection_type'], g['minimal_command'] or 'No existing command closes this gap; see execution_gaps.json'] for g in metrics['execution_gaps']]), '',
        'No generator rerun is needed for passage/qualification annotation or substantive answer review: all original text and answers are saved. '
        'Fresh execution is needed only for absent timing measurements, not for recomputing accuracy or token metrics. '
        'The staged runner cannot recover contiguous E2E by being rerun unchanged; it first needs a targeted clock/filter option. '
        'Do not rerun all competitors to obtain an invoice, price rate, annotation, or the six impossible whole-chunk token matches.', '',
        '## Reproduce this offline report', '', '```sh', command, '```', '',
        'Use a new output directory. Reporting imports no SDK, generator, semantic model or provider client. '
        'No historical output or existing Markdown is written.', '']
    return '\n'.join(lines)


def gaps(rows, controls):
    all_ids = [dict(zip(('case_id', 'allocated_budget', 'trial'), identity(r)), arm=r['arm']) for r in rows]
    unmatched = [dict(case_id=r['case_id'], allocated_budget=r['allocated_budget'], trial=r['trial'], arm=r['matched_target'])
                 for r in controls if r['answer_score'] == 'not_matched']
    def entry(metric, affected, reason, kind, steps):
        return dict(metric=metric, affected_attempts=affected, reason=reason, collection_type=kind,
                    minimal_command=None, minimal_steps=steps, executed=False)
    return [
        entry('Complete answer-bearing evidence / qualification / chain retention', all_ids,
            'Frozen truth has supporting_sources and answer substring rules, but no required spans, exception labels or reasoning chains.',
            'human annotation and offline rescoring; no model execution',
            'Annotate necessary evidence spans against existing frozen questions/answers without altering them; review saved contexts against those labels. No existing CLI accepts such annotations.'),
        entry('Contiguous end-to-end and complete preparation wall-clock latency', all_ids,
            'Selection is staged before generation; complete selection is ranker + preparation component sums, with shared/cached rankings.',
            'targeted fresh execution after timing support is added',
            'Add per-method/per-case filters and a clock around fresh relevance + SDK/packing + generation. The existing release_benchmark CLI cannot collect this boundary; rerunning it unchanged does not close the gap.'),
        entry('Actual billed API expenditure', [a for a in all_ids if a['arm'] in ('cohere', 'claude', 'gpt')],
            'Usage is saved, but no invoice, account tariff, discount or credit allocation is present.',
            'billing metadata and offline calculation; no model execution',
            'Obtain billing export for the 120 saved provider calls and reconcile usage. No repository command accesses account invoices.'),
        entry('Cohere v4 Pro dollar estimate', [a for a in all_ids if a['arm'] == 'cohere'],
            '24 billed search units exist; an applicable per-unit price does not.',
            'pricing metadata and offline calculation; no model execution',
            'Obtain the applicable v4 Pro price per search unit; multiply by the 24 saved billed units. No reranking is necessary.'),
        entry('Exactly matched BGE whole-chunk control', unmatched,
            'No whole-chunk BGE subset renders to these six target token counts; exhaustive saved search found none.',
            'unmatchable under the frozen packing protocol; no rerun',
            'Keep unmatched cases excluded and report them explicitly. Changing passage boundaries would change the comparison.'),
        entry('Uniform fresh latency cohort / upstream corpus retrieval latency', all_ids,
            'Native ranker timings and most generator durations are historical/reused; upstream corpus search is outside this frozen-pool experiment.',
            'targeted fresh timing execution; corpus retrieval is outside current protocol',
            'Do not rerun for reporting. A future latency-only study needs method filters, fresh ranking/generation timers and controlled cache state. Corpus retrieval needs a separately specified corpus and is not recoverable from candidate pools.'),
    ]


def build(source, output, *, grader_version=ANSWER_GRADER_VERSION):
    if output.exists() or source.resolve() == output.resolve():
        raise FileExistsError('output must be a new separate directory')
    paths = sorted(p for p in source.rglob('*') if p.is_file() and not p.name.endswith(('-wal', '-shm')))
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    manifest = json.loads((source / 'manifest.json').read_text())
    for name, expected in manifest['frozen_inputs'].items():
        path = resolve_artifact(name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'frozen input changed: {path}')
    inputs = {p.name.removesuffix('-inputs.json'): json.loads(p.read_text()) for p in source.glob('*-inputs.json')}
    rows = read_rows(source / 'results.jsonl')
    expected = {(c, b, t, m) for c in manifest['cases'] for b in manifest['budgets']
                for t in range(1, manifest['trials'] + 1) for m in manifest['methods']}
    expected |= {(c, None, t, 'full') for c in manifest['cases'] for t in range(1, manifest['trials'] + 1)}
    actual = {(*identity(r), r['arm']) for r in rows}
    if actual != expected or len(rows) != len(expected):
        raise ValueError('incomplete or duplicate frozen schedule')
    references = graph_references(source, rows, inputs)
    attempts = [attempt_metrics(r, inputs[r['case_id']], references[r['case_id']], n, grader_version=grader_version) for n, r in enumerate(rows, 1)]
    full_tokens = {r['case_id']: r['selected_tokens'] for r in attempts if r['arm'] == 'full'}
    if any(r['input_tokens'] != full_tokens[r['case_id']] for r in attempts):
        raise ValueError('inconsistent original candidate tokens')
    overall = {m: summarize([r for r in attempts if r['arm'] == m]) for m in METHODS}
    baseline = [r for r in attempts if r['arm'] == 'bge']
    controls = read_rows(source / 'matched-bge/results.jsonl')
    control_metrics = [attempt_metrics(r, inputs[r['case_id']], references[r['case_id']], n, grader_version=grader_version)
                       for n, r in enumerate(controls, 1) if r['answer_score'] in COMPLETED]
    matched = {}
    for method in ('omneum', 'bm25_omneum', 'embedding_omneum', 'bge_omneum'):
        subset = [r for r in controls if r['matched_target'] == method]
        valid = [r for r in subset if r['answer_score'] in COMPLETED]
        targets = [r for r in attempts if r['arm'] == method]
        result = paired(targets, valid, exact_tokens=True)
        if result['pairs'] != len(valid):
            raise ValueError('invalid exact-token control alignment')
        result['unmatchable'] = sum(r['answer_score'] == 'not_matched' for r in subset)
        matched[method] = result
    providers = read_rows(source / 'provider_results.jsonl')
    costs = {m: selector_cost(providers, m) for m in METHODS}
    reviews = json.loads((source / 'case_reviews.json').read_text())
    execution_gaps = gaps(attempts, controls)
    current = read_rows(source / 'current-sdk-recheck/results.jsonl')
    metrics = {'schema_version': 1, 'source': str(source), 'manifest': manifest,
        'definitions': {
            'accuracy': 'correct / completed answers including unscored as noncorrect; failures separately',
            'context_reduction': 'mean of 1 - selected_tokens / input_tokens; zero input undefined',
            'evidence_tokens_per_correct_answer': 'sum context tokens for all completed attempts / correct, null if zero successes or missing tokens',
            'percentiles': 'linear interpolation at (n - 1) * q; missing/nonfinite/negative values excluded with coverage',
            'supporting_passage_recall': 'annotated supporting source IDs with whole original text in context / annotated supporting sources',
            'independent_support_coverage': 'retained / available annotated-supporter source-claim independence mass; one full graph reference per case',
            'selection_latency_scope': 'rank_seconds + prepare_seconds; component sum, not contiguous wall; SDK preparation includes harness checks',
            'end_to_end_latency_scope': 'complete selection component sum + recorded generation_seconds; direct wall absent',
            'cpu_scope': 'sdk_process_during_evaluation; excludes packing, MCP and generator processes',
            'rss_scope': 'sdk_process_lifetime_peak_rss; includes benchmark caches, not request allocation',
            'evidence_sufficiency': 'not annotated; no full-evidence/qualification/chain rate inferred from claim or passage coverage'},
        'overall': overall, 'by_budget': group_summary(attempts, 'allocated_budget'),
        'by_domain': group_summary(attempts, 'domain'),
        'accuracy_vs_actual_tokens': group_summary(attempts, 'selected_tokens'),
        'paired_nominal': {m: paired([r for r in attempts if r['arm'] == m], baseline) for m in METHODS[1:]},
        'paired_exact_nominal': {m: paired([r for r in attempts if r['arm'] == m], baseline, True) for m in METHODS[1:]},
        'paired_exact_controls': matched, 'costs': costs,
        'secondary_control_metrics': {m: summarize([r for r in control_metrics if r['arm'] == 'bge_matched_' + m])
            for m in ('omneum', 'bm25_omneum', 'embedding_omneum', 'bge_omneum')},
        'claim_omission_stages': json.loads((source / 'analysis.json').read_text())['failure_layers'],
        'pricing_assumptions': {'basis': 'original report recorded list prices; no refreshed prices or invoices',
            'claude': {'input_per_million_usd': 2, 'output_per_million_usd': 10,
                'source': 'https://platform.claude.com/docs/en/models/sonnet-5-5/overview'},
            'gpt': {'input_per_million_usd': 10, 'cached_input_per_million_usd': 1, 'output_per_million_usd': 50,
                'source': 'https://developers.openai.com/api/docs/models/gpt-6-astra'},
            'cohere': {'per_search_unit_usd': None, 'source': 'https://cohere.com/pricing'}},
        'generation_origins': dict(Counter(r.get('generation_origin') for r in rows)),
        'generator_stop_reasons': dict(Counter((r.get('generator_metadata') or {}).get('done_reason') for r in rows)),
        'sdk_peak_rss_max_bytes': {m: max((r['execution_history']['peak_memory_bytes'] for r in attempts
            if r['arm'] == m and r.get('execution_history') and r['execution_history'].get('peak_memory_bytes') is not None), default=None) for m in METHODS},
        'current_sdk_recheck_prepare_seconds': {m: distribution([r['prepare_seconds'] for r in current if r['arm'] == m])
            for m in ('omneum', 'bm25_omneum', 'embedding_omneum', 'bge_omneum')},
        'execution_gaps': execution_gaps}
    command = f'.venv/bin/python -m benchmarks.context_selection.synthetic.release_metrics --source {source} --output NEW_OUTPUT_DIRECTORY'
    report = markdown(metrics, reviews, command)
    # Reanalysis must not mutate input artifacts, including either saved SQLite database.
    if any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != value for p, value in hashes.items()):
        raise ValueError('source artifact changed during reporting')
    output.mkdir(parents=True)
    def write(name, data):
        with (output / name).open('x') as stream:
            json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write('\n')
    write('metrics.json', metrics)
    write('execution_gaps.json', execution_gaps)
    write('graph_references.json', {c: {'evaluation_run_id': v['evaluation_run_id'],
        'weights': [dict(source_id=s, claim_id=k, **w) for (s, k), w in v['weights'].items()]}
        for c, v in references.items()})
    write('case_reviews.json', reviews)
    write('provenance.json', {'source_sha256': hashes, 'frozen_input_sha256': manifest['frozen_inputs'],
        'reporter_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'model_executions': 0, 'input_artifacts_unchanged': True,
        'token_measurement': 'Saved exact tokenizer counts; prior live verification in source/artifact_verification.json; tokenizer not invoked during reporting'})
    with (output / 'attempt_metrics.jsonl').open('x') as stream:
        for row in attempts:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
    with (output / 'report.md').open('x') as stream:
        stream.write(report)
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--grader-version', choices=[ANSWER_GRADER_VERSION, 'literal-v1'], default=ANSWER_GRADER_VERSION,
                        help='Use literal-v1 only to validate historical frozen labels; never relabel those artifacts.')
    args = parser.parse_args()
    result = build(args.source, args.output, grader_version=args.grader_version)
    print(json.dumps({'output': str(args.output), 'attempts': sum(v['attempts'] for v in result['overall'].values()),
                      'model_executions': 0}, allow_nan=False))


if __name__ == '__main__':
    main()
