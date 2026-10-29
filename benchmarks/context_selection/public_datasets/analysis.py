"""Dataset-specific summaries and paired, question-clustered uncertainty."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import random
from statistics import mean

from benchmarks.context_selection.synthetic.aggregate import _percentile
from benchmarks.context_selection.synthetic.release_metrics import distribution, paired


def interval(values):
    if len(values) < 20:
        return None
    rng = random.Random(42)
    samples = [mean(rng.choices(values, k=len(values))) for _ in range(2000)]
    return [_percentile(samples, .025), _percentile(samples, .975)]


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['dataset'], row['domain'], row['allocated_budget'])].append(row)
    result = []
    for (dataset, domain, budget), group in sorted(groups.items()):
        arms = {}
        for method in dict.fromkeys(r['method'] for r in group):
            arm = [r for r in group if r['method'] == method]
            answered = [r for r in arm if r['answer_score'] in ('correct', 'incorrect')]
            by_question = defaultdict(list)
            for row in arm:
                by_question[row['case_id']].append(float(row['answer_score'] == 'correct'))
            arms[method] = dict(
                trials=len(arm), answered=len(answered),
                selection_failures=sum(r['answer_score'] == 'selection_failure' for r in arm),
                generation_failures=sum(r['answer_score'] == 'generation_failure' for r in arm),
                preprocessing_failures={stage: sum(r.get('preprocessing_failure_stage') == stage for r in arm)
                                        for stage in ('extraction', 'normalization', 'mapping')},
                accuracy_including_failures=mean([mean(v) for v in by_question.values()]) if dataset == 'hotpotqa' else None,
                accuracy_ci95=interval([mean(v) for v in by_question.values()]) if dataset == 'hotpotqa' else None,
                answer_f1_completed=mean(r['answer_metrics']['f1'] for r in answered) if answered else None,
                answer_f1_including_failures=(sum(r['answer_metrics']['f1'] for r in answered) / len(arm)
                                             if dataset == 'hotpotqa' else None))
            for field in ('selected_tokens', 'budget_utilization', 'selection_seconds', 'prepare_seconds',
                          'retrieval_seconds', 'rank_seconds', 'extraction_seconds', 'normalization_seconds',
                          'generation_seconds', 'end_to_end_seconds', 'generator_input_tokens', 'generator_output_tokens'):
                arms[method][field] = distribution([r.get(field) for r in arm])
            for field in ('precision', 'recall', 'pool_recall'):
                arms[method]['evidence_' + field] = distribution([r.get('selection_score', {}).get(field) for r in arm])
            for field in ('graph_evaluation_latency_ms', 'local_inference_latency_ms',
                          'chunk_selection_latency_ms', 'context_reconstruction_latency_ms'):
                arms[method][field] = distribution([(r.get('sdk_result') or {}).get('telemetry', {}).get(field) for r in arm])
            arms[method]['extraction_failure_rate'] = arms[method]['preprocessing_failures']['extraction'] / len(arm)
            arms[method]['normalization_failure_rate'] = arms[method]['preprocessing_failures']['normalization'] / len(arm)
            usage = sum(r.get('generator_input_tokens', 0) + r.get('generator_output_tokens', 0) for r in arm)
            arms[method]['correct_per_1000_generator_tokens'] = (
                1000 * sum(r['answer_score'] == 'correct' for r in arm) / usage if usage else None)
        comparisons = {}
        if dataset == 'hotpotqa':
            left = [r for r in group if r['method'] == 'omneum']
            for method in arms:
                if method == 'omneum':
                    continue
                right = [r for r in group if r['method'] == method]
                comparisons[method] = paired(left, right)
                a = {(r['case_id'], r['trial']): r for r in left}
                b = {(r['case_id'], r['trial']): r for r in right}
                differences = defaultdict(list)
                for key in sorted(a.keys() & b.keys()):
                    if a[key]['candidate_pool'] != b[key]['candidate_pool']:
                        raise ValueError('paired rows have different candidate pools')
                    differences[key[0]].append(int(a[key]['answer_score'] == 'correct') -
                                                int(b[key]['answer_score'] == 'correct'))
                values = [mean(v) for v in differences.values()]
                comparisons[method].update(accuracy_delta_including_failures=mean(values) if values else None,
                                           delta_ci95=interval(values))
        result.append(dict(dataset=dataset, domain=domain, allocated_budget=budget,
                           methods=arms, omneum_vs_method=comparisons))
    return dict(groups=result, uncertainty='95% percentile bootstrap, seed 42, 2000 question-cluster resamples; minimum 20 questions',
                evidence='Public annotation overlap, not downstream answer correctness; SciFact unjudged treated nonrelevant',
                normalization_failures='Raised production/provider errors only; internal rejected proposals not exposed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results', type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize([json.loads(v) for v in args.results.read_text().splitlines()]), indent=2))


if __name__ == '__main__':
    main()
