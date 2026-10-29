"""Offline verification of the sole canonical Gemini comparison."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

from .aggregate import summarize
from .scoring import score_answer_legacy, score_selection

BASE = Path(__file__).resolve().parent
RUN = 'bge-google-low-vs-bge-omneum-20261008'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode()).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def verify(base=BASE):
    base = Path(base)
    results, analysis = base / 'results' / RUN, base / 'analysis' / RUN
    manifest = json.loads((results / 'manifest.public-v1.json').read_text())
    for name, expected in manifest['artifacts'].items():
        path = (results if name in ('results.jsonl', 'summary.json') else analysis) / name
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, f'Gemini artifact changed: {name}')
    rows = [json.loads(line) for line in (results / 'results.jsonl').read_text().splitlines()]
    audit = json.loads((analysis / 'answer_audit.json').read_text())
    comparison = json.loads((analysis / 'comparison.json').read_text())
    summary = summarize(rows)
    require(summary == json.loads((results / 'summary.json').read_text()), 'Gemini raw/summary mismatch')
    require(manifest['run_id'] == comparison['run_id'] == RUN, 'Gemini run identity mismatch')
    cases = sorted({r['case_id'] for r in rows})
    identities = [f"{r['case_id']}/{r['method']}/{r['trial']}" for r in rows]
    require(len(cases) == 24 and identities == [f'{c}/{m}/{t}' for c in cases
            for m in ('bge_google', 'bge_omneum') for t in range(1, 11)], 'Gemini trial coverage mismatch')
    by = {a['identity']: a for a in audit}
    require(len(audit) == len(by) == 480 and set(by) == set(identities), 'Gemini adjudication coverage mismatch')
    targets = manifest['source_preservation']['target_source_record_sha256']
    require(len(targets) == 139, 'Wrong recovery target count')
    preserved = manifest['source_preservation']
    require(digest([{k: r[k] for k in ('case_id', 'method', 'trial', 'selected', 'selection', 'selection_score')}
                    for r in rows]) == preserved['selection_records_sha256'], 'Original selections changed')
    require(digest([r for r in rows if r['method'] == 'bge_omneum']) == preserved['baseline_records_sha256'],
            'Historical Omneum baseline changed')
    require(digest([r for r, identity in zip(rows, identities) if r['method'] == 'bge_google' and identity not in targets])
            == preserved['successful_gemini_records_sha256'], 'Successful Gemini generations changed')
    for recorded, expected in manifest['inputs'].items():
        path = base / 'cases' / Path(recorded).parent.name / Path(recorded).name
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'Frozen Gemini input changed')
    for row, identity in zip(rows, identities):
        truth = json.loads((base / 'cases' / row['case_id'] / 'ground_truth.json').read_text())
        case = json.loads((base / 'cases' / row['case_id'] / 'case.json').read_text())
        labels = SimpleNamespace(supporting_sources=truth['supporting_sources'],
                                 scoring=SimpleNamespace(**truth['scoring']))
        require(score_selection(row['selected'], labels) == row['selection_score'], 'Gemini source scores changed')
        gen = row['generation']
        require(gen['provider'] == 'anthropic' and gen['model'] == 'claude-sonnet-5-5', 'Wrong Gemini generator')
        require(gen['text'] == row['answer'], 'Gemini response text mismatch')
        require(type(gen['input_tokens']) is int and type(gen['output_tokens']) is int, 'Missing Gemini usage')
        require(math.isclose(row['end_to_end_latency_seconds'], row['selection']['latency_seconds'] +
                             gen['latency_seconds']), 'Gemini latency reconstruction mismatch')
        context = '\n\n'.join(f"Source: {d['source']}\n{d['text']}" for d in row['selection']['selected'])
        prompt = (f"Answer the question using only the sources below.\n\nQuestion:\n\n{case['question']}"
                  f"\n\nSources:\n\n{context}\n\nGive a concise answer and identify which sources support it.\n")
        require((gen.get('request_hash') or row.get('generation_request_hash')) == digest({'provider': 'anthropic', 'model': 'claude-sonnet-5-5',
            'prompt': prompt, 'max_tokens': 1024, 'response_schema': None}), 'Gemini generator prompt/configuration drift')
        review = by[identity]
        require(review['record_sha256'] == digest(row) and review['answer'] == row['answer'] and
                review['selected'] == row['selected'] and review['recorded_score'] == row['answer_score'],
                'Gemini review does not match raw record')
        require(bool(review['reason']), 'Missing Gemini adjudication explanation')
        if row['answer_score'] == 'generation_failure':
            require(row['failure_type'] == 'refusal' and gen['response_diagnostics']['stop_reason'] == 'refusal'
                    and review['manual_status'] == 'generator_refusal', 'Unresolved Gemini generation failure')
        else:
            require(score_answer_legacy(row['answer'], labels) == row['answer_score'], 'Frozen Gemini substring score changed')
            require(review['manual_status'] in ('correct', 'incomplete', 'substantively_incorrect'), 'Pending Gemini review')
        if identity in targets:
            require(row['recovery']['source_record_sha256'] == targets[identity] and
                    row['recovery']['source_run_id'] == RUN and row['recovery']['state'] == 'completed',
                    'Invalid Gemini recovery provenance')
    for method in ('bge_google', 'bge_omneum'):
        selected = [r for r in rows if r['method'] == method]
        require(summary[method]['generator_usage']['total_tokens']['n'] == 240, 'Partial Gemini usage')
        require(summary[method]['latency']['end_to_end_seconds']['n'] == 240, 'Partial Gemini timing')
        metrics = comparison['metrics'][method]
        expected = {'precision': summary[method]['selection_precision'], 'recall': summary[method]['selection_recall'],
            'accuracy': sum(by[f"{r['case_id']}/{method}/{r['trial']}"]['manual_status'] == 'correct' for r in selected) / 240,
            'selection_p50_seconds': summary[method]['latency']['selection_seconds']['p50'],
            'end_to_end_p50_seconds': summary[method]['latency']['end_to_end_seconds']['p50'],
            'generator_tokens': summary[method]['generator_usage']['total_tokens']['sum'],
            'generator_cost_usd': sum((r['generation']['input_tokens'] * 2 + r['generation']['output_tokens'] * 10)
                                      for r in selected) / 1e6}
        require(all(math.isclose(metrics[k], v, abs_tol=1e-12) for k, v in expected.items()), 'Gemini published metrics mismatch')
        require(comparison['counts'][method] == dict(Counter(by[f"{r['case_id']}/{method}/{r['trial']}"]['manual_status']
                for r in selected)), 'Gemini semantic outcome counts mismatch')
    require(summary['bge_google']['latency']['selection_seconds']['p50'] == 2.48713827051688,
            'Original Gemini selection median changed')
    return manifest, rows, audit, comparison


if __name__ == '__main__':
    _, rows, _, comparison = verify()
    print(json.dumps({'verified_records': len(rows), 'run_id': RUN, 'metrics': comparison['metrics']}, indent=2))
