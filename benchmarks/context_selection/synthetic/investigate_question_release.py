"""Read-only, offline audit of the frozen release run; never generate answers.

Run with .venv/bin/python -m benchmarks.context_selection.synthetic.investigate_question_release
Writes only to a new analysis directory (refuses existing output).
Replays use exact recorded counts or bounds from recorded feasibility. They
verify utility and packing decisions, not an independent tokenizer execution.
"""

from benchmarks.context_selection.paths import resolve_artifact
import argparse
from collections import Counter
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from statistics import mean

from omneum.client import _evaluate_context
from omneum.context_selection import claim_id, map_chunks, reconstruct, reconstruct_context
from omneum.query_context import discover_chunks
from omneum.question_selection import lexical_claim_relevance
from omneum.serialization import serialize_source
from .loader import load_case, load_ground_truth
from .scoring import normalize, score_answer_legacy as score_answer, score_selection
from .sdk_adapter import build_observations
from ..config import estimator_config


ROOT = Path(__file__).resolve().parent
BASELINE = ROOT / 'results/question-aware-release-v1'


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def audit(source, tokenizer=None):
    files = sorted(p for p in source.rglob('*') if p.is_file())
    hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    rows = read_rows(source / 'results.jsonl')
    selections = read_rows(source / 'selections.jsonl')
    manifest = json.loads((source / 'manifest.json').read_text())
    summary = json.loads((source / 'summary.json').read_text())
    if tokenizer is not None:
        import httpx
        http = httpx.Client(trust_env=False, timeout=30)
        models = http.get('http://127.0.0.1:11434/api/ps').raise_for_status().json()['models']
        assert len(models) == 1 and models[0]['digest'] == manifest['generator']['digest']

        @lru_cache(maxsize=None)
        def resident_count(text):
            response = http.post(tokenizer + '/tokenize', json={
                'content': text, 'add_special': False, 'parse_special': True})
            return len(response.raise_for_status().json()['tokens'])
    index = {(r['case_id'], r['arm'], r['allocated_budget'], r['trial']): r for r in rows}
    assert len(index) == len(rows) == len(selections) == 3216
    selection_index = {(r['case_id'], r['arm'], r['allocated_budget'], r['trial']): r for r in selections}
    for key, row in index.items():
        assert all(row[f] == selection_index[key][f] for f in ('selected', 'context', 'selected_tokens'))
        assert row['allocated_budget'] is None or row['selected_tokens'] <= row['allocated_budget']
        if tokenizer is not None:
            assert resident_count(row['context']) == row['selected_tokens']
            assert resident_count(row['generator_prompt']) == row['generator_input_tokens']
    frozen = {p: hashlib.sha256(resolve_artifact(p).read_bytes()).hexdigest() == h
              for p, h in manifest['frozen_inputs'].items()}
    assert all(frozen.values())
    for group, groups in (
        ('overall', {'all': rows}),
        ('by_budget', {str(b): [r for r in rows if r['allocated_budget'] == b] for b in manifest['budgets']}),
        ('by_domain', {d: [r for r in rows if r['domain'] == d] for d in {r['domain'] for r in rows}}),
    ):
        for name, subset in groups.items():
            expected = summary[group] if group == 'overall' else summary[group][name]
            for arm, values in expected.items():
                ss = [r for r in subset if r['arm'] == arm]
                assert values['attempts'] == len(ss)
                assert values['correct'] == sum(r['answer_score'] == 'correct' for r in ss)
                assert values['accuracy'] == mean(r['answer_score'] == 'correct' for r in ss)
                for metric in ('precision', 'recall'):
                    assert values[metric] == mean(r['selection_score'][metric] for r in ss)

    pairs = []
    paired_summary = {}
    for arm in ('bge', 'bm25', 'embedding'):
        counts = Counter()
        for r in rows:
            if r['arm'] != arm:
                continue
            s = index[r['case_id'], arm + '_omneum', r['allocated_budget'], r['trial']]
            outcome = ('win' if s['answer_score'] == 'correct' else 'loss') if (
                (r['answer_score'] == 'correct') != (s['answer_score'] == 'correct')) else 'tie'
            counts[outcome] += 1
            if outcome == 'tie':
                continue
            lost, added = set(r['selected']) - set(s['selected']), set(s['selected']) - set(r['selected'])
            by_id = {c['chunk_id']: c for c in r.get('selected_chunks', []) + s.get('selected_chunks', [])}
            trace = s['diagnostics']['utility_trace']
            final = {c['chunk_id']: c for c in trace[-1]['candidates']}
            reasons = {}
            for identifier in lost:
                if identifier in {c['chunk_id'] for c in s['excluded']}:
                    reasons[identifier] = 'outside_expansion'
                elif identifier in final:
                    c = final[identifier]
                    reasons[identifier] = ('over_budget' if not c['feasible'] else
                                           'nonpositive_utility' if c['utility'] <= 0 else 'unselected')
            pairs.append(dict(case_id=r['case_id'], domain=r['domain'], arm=arm,
                budget=r['allocated_budget'], trial=r['trial'], outcome=outcome,
                removed=[by_id[k] for k in r['selected'] if k in lost],
                added=[by_id[k] for k in s['selected'] if k in added],
                retained=[by_id[k] for k in s['selected'] if k in set(r['selected'])],
                removal_reasons=reasons, same_set=not lost and not added,
                baseline_order=r['selected'], hybrid_order=s['selected'],
                baseline_context=r['context'], hybrid_context=s['context'],
                baseline_answer=r['answer'], hybrid_answer=s['answer'],
                baseline_grade=r['answer_score'], hybrid_grade=s['answer_score'],
                baseline_metrics=r['selection_score'], hybrid_metrics=s['selection_score']))
        paired_summary[arm] = dict(counts)

    replay = []
    standalone = []
    grading = []
    for case_id in manifest['cases']:
        case = load_case(ROOT / 'cases' / case_id / 'case.json')
        truth = load_ground_truth(ROOT / 'cases' / case_id / 'ground_truth.json')
        observations, _ = build_observations(case)
        chunks = [dict(chunk_id='chunk-' + c.source_id, raw_text=c.text,
                       claim_ids=[claim_id(o.claim)], source=o.source)
                  for c, o in zip(case.candidates, observations, strict=True)]
        evaluation = _evaluate_context(observations, estimator=estimator_config())
        support = {claim_id(c.claim): c.support for c in evaluation.claim_support}
        mapping = map_chunks(chunks, support)
        tokens = {'': 0}
        bounds = {}

        def remember(text, count):
            if text in tokens:
                assert tokens[text] == count
            tokens[text] = count

        case_rows = [r for r in rows if r['case_id'] == case_id]
        for row in case_rows:
            remember(row['context'], row['selected_tokens'])
            assert row['answer_score'] == score_answer(row['answer'], truth)
            assert row['selection_score'] == score_selection(
                [k.removeprefix('chunk-') for k in row['selected']], truth)
            for phrase in truth.scoring.forbidden:
                if normalize(phrase) in normalize(row['answer']):
                    grading.append(dict(case_id=case_id, arm=row['arm'], budget=row['allocated_budget'],
                        trial=row['trial'], grade=row['answer_score'], forbidden=phrase, answer=row['answer']))
            if not row.get('sdk_result'):
                continue
            actual = row['sdk_result']['evaluation']
            assert all(abs(support[k] - v) < 1e-12 for k, v in actual['claim_support'].items())
            reliability = {serialize_source(c.source.kind, c.source.identifier).hex(): c.reliability
                           for c in evaluation.source_reliability}
            assert all(abs(reliability[k] - v) < 1e-12 for k, v in actual['source_reliability'].items())
            # Every candidate proposal was rendered in static descending support
            # order by production select_chunks, including infeasible proposals.
            eligible = row['diagnostics'].get('eligible_chunk_ids', mapping['retrieval_order'])
            ordered = sorted(eligible, key=lambda k: -sum(support[c] for c in mapping['chunk_claims'][k]))
            rendered = {**mapping, 'retrieval_order': ordered}
            for step in row['diagnostics'].get('utility_trace', []):
                for c in step['candidates']:
                    text = reconstruct(rendered, [*step['selected'], c['chunk_id']])
                    if 'proposed_context_tokens' in c:
                        remember(text, c['proposed_context_tokens'])
                    else:
                        low, high = bounds.get(text, (0, 10**9))
                        budget = row['allocated_budget']
                        bounds[text] = ((low, min(high, budget)) if c['feasible']
                                        else (max(low, budget + 1), high))
                    if c['utility'] > 0:
                        # Frozen hybrids used gain / standalone rendered tokens,
                        # gamma=1 and no relevance/penalty. Infer integer costs.
                        cost = c['marginal_gain'] / c['utility']
                        assert abs(cost - round(cost)) < 1e-8
                        remember(reconstruct(mapping, [c['chunk_id']]), round(cost))

        for text, (low, high) in bounds.items():
            assert low <= high
            if text in tokens:
                assert low <= tokens[text] <= high

        def count(text):
            if tokenizer is not None:
                return resident_count(text)
            if text in tokens:
                return tokens[text]
            # A representative satisfying every frozen feasibility constraint.
            # This cannot establish the original count for an intermediate set.
            return bounds[text][0]

        retrieval = json.loads((source / (case_id + '-retrieval.json')).read_text())
        for arm in ('omneum', 'bm25_omneum', 'embedding_omneum', 'bge_omneum'):
            chosen = chunks
            options = {'question': case.question}
            if arm != 'omneum':
                ranked = retrieval[arm.removesuffix('_omneum')]
                discovery = discover_chunks(observations, mapping, ranked['raw_scores'],
                    'reranker_score' if arm == 'bge_omneum' else 'similarity', 'expanded', 3, 2)
                chosen = [c for c in chunks if c['chunk_id'] in discovery['eligible_chunk_ids']]
                options = dict(strategy='coverage_support_density', complementary_evidence=True,
                               token_cost_exponent=1, _allow_unmapped_claims=True)
            for budget in manifest['budgets']:
                trace = []
                old = index[case_id, arm, budget, 1]
                try:
                    new = reconstruct_context(evaluation, chosen, token_budget=budget,
                        count_tokens=count, _selection_trace=trace, **options)
                except KeyError as missing:
                    replay.append(dict(case_id=case_id, arm=arm, budget=budget,
                        status='unobserved_token_count', missing_context=str(missing)))
                    continue
                if new['context'] != old['context']:
                    if tokenizer is not None:
                        raise AssertionError((case_id, arm, budget, new['selected_chunk_ids'], old['selected']))
                    replay.append(dict(case_id=case_id, arm=arm, budget=budget,
                        status='intermediate_token_costs_unresolved',
                        representative_counter_selection=new['selected_chunk_ids'],
                        frozen_selection=old['selected']))
                    continue
                assert new['selected_chunk_ids'] == old['selected']
                assert new['token_usage'] == old['selected_tokens']
                assert old['context'] == index[case_id, arm, budget, 2]['context']
                if arm != 'omneum':
                    frozen_trace = old['diagnostics']['utility_trace']
                    assert len(trace) == len(frozen_trace)
                    for current_step, frozen_step in zip(trace, frozen_trace, strict=True):
                        assert current_step['selected'] == frozen_step['selected']
                        assert current_step.get('best_feasible_chunk_id') == frozen_step.get('best_feasible_chunk_id')
                        for current, frozen_candidate in zip(current_step['candidates'], frozen_step['candidates'], strict=True):
                            for field in ('chunk_id', 'feasible', 'marginal_gain', 'utility'):
                                if field in ('marginal_gain', 'utility'):
                                    assert abs(current[field] - frozen_candidate[field]) < 1e-12, (case_id, arm, budget, field)
                                else:
                                    assert current[field] == frozen_candidate[field], (case_id, arm, budget, field)
                final = trace[-1]['candidates'] if trace else []
                feasible = [c for c in final if c['feasible']]
                replay.append(dict(case_id=case_id, arm=arm, budget=budget,
                    status='exact_tokenizer_parity' if tokenizer is not None else 'frozen_feasibility_parity',
                    selected=old['selected'], tokens=new['token_usage'],
                    stop=('exhausted_candidates' if len(new['selected_chunk_ids']) == len(chosen) else
                          'no_feasible_candidate' if not feasible else 'nonpositive_utility'),
                    final_candidates=final))

        relevance = lexical_claim_relevance(case.question, {claim_id(o.claim): o.claim for o in observations})
        # Unlimited budget isolates coverage saturation from token packing. This
        # is explicitly a diagnostic in character units, not a benchmark result.
        saturation = reconstruct_context(evaluation, chunks, question=case.question,
                                          token_budget=10**9, count_tokens=len)
        standalone.append(dict(case_id=case_id, question=case.question,
            claims=[dict(attribute=o.claim.attribute, value=o.claim.value,
                         relevance=relevance[claim_id(o.claim)], claim_id=claim_id(o.claim))
                    for o in {claim_id(o.claim): o for o in observations}.values()],
            positive_claims=sum(q > 0 for q in relevance.values()),
            unlimited_character_budget_selection=saturation['selected_chunk_ids'],
            by_budget=[dict(budget=b, selected=index[case_id, 'omneum', b, 1]['selected'],
                tokens=index[case_id, 'omneum', b, 1]['selected_tokens']) for b in manifest['budgets']]))

    assert all(hashlib.sha256((source / name).read_bytes()).hexdigest() == h for name, h in hashes.items())
    if tokenizer is not None:
        http.close()
    return dict(baseline_sha256=hashes, rows=len(rows), frozen_inputs_verified=True,
        independent_tokenizer_verified=tokenizer is not None,
        summary_verified=True, paired=paired_summary,
        paired_regressions_same_set={a: sum(p['same_set'] for p in pairs if p['arm'] == a and p['outcome'] == 'loss')
                                     for a in paired_summary},
        replay_counts=dict(Counter(r['status'] for r in replay)),
        standalone_by_budget={str(b): dict(tokens=mean(r['selected_tokens'] for r in rows if r['arm'] == 'omneum' and r['allocated_budget'] == b),
            recall=mean(r['selection_score']['recall'] for r in rows if r['arm'] == 'omneum' and r['allocated_budget'] == b)) for b in manifest['budgets']}), pairs, replay, standalone, grading


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=BASELINE)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tokenizer', help='Existing local llama-server; calls /tokenize only, never generation')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output must not exist; baseline and prior audits are immutable')
    results = audit(args.source, args.tokenizer)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, value in zip(('audit', 'paired_cases', 'replay', 'standalone', 'grading_flags'), results, strict=True):
        (args.output / (name + '.json')).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: v for k, v in results[0].items() if k != 'baseline_sha256'}, indent=2))


if __name__ == '__main__':
    main()
