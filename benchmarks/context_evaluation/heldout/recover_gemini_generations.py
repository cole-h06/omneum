"""Recover only failed generations from the pinned October 9 Gemini replay.

Preparation and validation are offline. Execution requires --execute-paid.
An interrupted request is never automatically sent again.
"""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
from statistics import median
import tempfile
import time
from types import SimpleNamespace

from .aggregate import summarize
from .scoring import score_answer, score_selection

BASE = Path(__file__).resolve().parent
RUN = "bge-google-low-vs-bge-omneum-20261008"
MODEL = "claude-sonnet-5-5"
SDK = "0.125.0"
SOURCE_HASHES = {
    "manifest.json": "757b5f0582dab486edfaee15527d739e294dc853f580728be17d43918254c4fa",
    "results.jsonl": "863f4ee76dbe1e557941c96f77e0676e4888a6ac58059ca5728a18b99f8d04dc",
    "summary.json": "9213ce76db6efc19f77fc7b4091c4f8a45018a5fb6eab62f6583b8d44f2a70c1",
}
BASELINE_RECORDS_HASH = "d9a05d5fb1e01f85c60bd5df6edd4716b000b38de7bc0417edd29920ae056695"
STATUSES = {"correct", "incomplete", "substantively_incorrect", "generator_refusal",
            "provider_failure", "empty_output"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic(path, data):
    """Persist the file and directory before proceeding to a provider request."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".recovery-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic(path, json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n")


def read_json(path):
    return json.loads(Path(path).read_text())


def key(row):
    return f"{row['case_id']}/{row['method']}/{row['trial']}"


def request_for(row, case):
    context = "\n\n".join(f"Source: {d['source']}\n{d['text']}" for d in row['selection']['selected'])
    prompt = (f"Answer the question using only the sources below.\n\nQuestion:\n\n{case['question']}"
              f"\n\nSources:\n\n{context}\n\nGive a concise answer and identify which sources support it.\n")
    return {"provider": "anthropic", "model": MODEL, "prompt": prompt,
            "max_tokens": 1024, "response_schema": None}


def truth_for(case_id, cases_dir):
    value = read_json(Path(cases_dir) / case_id / "ground_truth.json")
    return SimpleNamespace(supporting_sources=value['supporting_sources'],
                           scoring=SimpleNamespace(**value['scoring']))


def original_rows():
    """Use the canonical run's byte-preserved historical baseline after cleanup."""
    rows = [json.loads(line) for line in (BASE / 'results' / RUN / 'results.jsonl').read_text().splitlines()]
    require(digest([r for r in rows if r['method'] == 'bge_omneum']) == BASELINE_RECORDS_HASH,
            'Original baseline artifact changed')
    return rows


def verify_source(source, cases_dir=BASE / "cases"):
    source = Path(source)
    for name, expected in SOURCE_HASHES.items():
        require(file_hash(source / name) == expected, f"Source {name} hash mismatch")
    manifest = read_json(source / "manifest.json")
    rows = [json.loads(line) for line in (source / "results.jsonl").read_text().splitlines()]
    cases = sorted({r['case_id'] for r in rows})
    expected = [f"{c}/{m}/{t}" for c in cases for m in ('bge_google', 'bge_omneum') for t in range(1, 11)]
    require(len(cases) == 24 and [key(r) for r in rows] == expected, "Invalid paired trial schedule")
    require(manifest['run_id'] == RUN and manifest['trials'] == 10, "Wrong run identity")
    require(manifest['models'] == {'bge_google': 'gemini-3.8-flash', 'bge_omneum': 'Omneum',
                                    'generator': MODEL}, "Wrong model configuration")
    require(manifest['sole_request_change'] == {'thinking_config': {'thinking_level': 'low'}},
            "Wrong Gemini configuration")
    for recorded, expected_hash in manifest['inputs'].items():
        parts = Path(recorded).parts
        relative = Path(*parts[parts.index('cases') + 1:])
        require(file_hash(Path(cases_dir) / relative) == expected_hash, f"Frozen input drift: {relative}")
    require(summarize(rows) == read_json(source / "summary.json"), "Source summary mismatch")
    original = original_rows()
    require([r for r in rows if r['method'] == 'bge_omneum'] ==
            [r for r in original if r['method'] == 'bge_omneum'], "Historical Omneum baseline changed")
    requests = {}
    for row in rows:
        case = read_json(Path(cases_dir) / row['case_id'] / 'case.json')
        selection = row['selection']
        require(row['selected'] == [d['source'] for d in selection['selected']], "Selected order drift")
        texts = {c['source_id']: c['text'] for c in case['candidates']}
        require(all(texts[d['source']] == d['text'] for d in selection['selected']), "Selected text drift")
        require(len(row['selected']) == len(set(row['selected'])) == case['context_budget'], "Budget drift")
        require(score_selection(row['selected'], truth_for(row['case_id'], cases_dir)) ==
                row['selection_score'], "Selection score drift")
        request = request_for(row, case)
        recorded_hash = row.get('generation_request_hash') or (row.get('generation') or {}).get('request_hash')
        require(recorded_hash == digest(request), f"Generator prompt/configuration mismatch: {key(row)}")
        if row['method'] == 'bge_google' and row['answer_score'] == 'generation_failure':
            require(row.get('generation') is None and row.get('failure_type') == 'provider_error',
                    "Unexpected failure; do not replace measured/refused generations")
            requests[key(row)] = request
    require(len(requests) == 139, "Unexpected recovery target count")
    return manifest, rows, requests


def prepare(source, work, cases_dir=BASE / "cases"):
    manifest, rows, requests = verify_source(source, cases_dir)
    work = Path(work)
    require(not work.exists(), "Recovery workspace already exists; use --resume")
    # Workspace is staging, never an active publication or an in-place edit of source.
    require(not work.resolve().is_relative_to(BASE / 'results') and
            not work.resolve().is_relative_to(BASE / 'analysis'), "Stage outside active results/analysis")
    work.mkdir(parents=True)
    for name in SOURCE_HASHES:
        atomic(work / ('source_' + name), (Path(source) / name).read_bytes())
    package = version('anthropic')
    require(package == SDK, f"Use the original anthropic SDK {SDK}; found {package}")
    rates = manifest['pricing']['usd_per_million']
    outputs = [r['generation']['output_tokens'] for r in rows
               if r['method'] == 'bge_google' and r.get('generation')]
    inputs = [r['generation']['input_tokens'] for r in rows
              if r['method'] == 'bge_google' and r.get('generation')]
    # Exact request matches inform input accounting only; historical answers are never substituted.
    original = original_rows()
    known = {(r.get('generation') or {}).get('request_hash'): r['generation']['input_tokens']
             for r in original if r.get('generation')}
    input_known = sum(known[digest(r)] for r in requests.values() if digest(r) in known)
    covered = sum(digest(r) in known for r in requests.values())
    plan = {'run_id': RUN, 'prepared_at_utc': now(), 'source_artifact_sha256': SOURCE_HASHES,
            'original_manifest': manifest, 'generator_request': {'provider': 'anthropic', 'model': MODEL,
                'max_tokens': 1024, 'response_schema': None, 'sampling_seed_thinking_overrides': None},
            'transport': {'anthropic_sdk': SDK, 'max_retries': 0},
            'implementation_sha256': {str(Path(__file__).name): file_hash(__file__),
                                      'scoring.py': file_hash(BASE / 'scoring.py'),
                                      'aggregate.py': file_hash(BASE / 'aggregate.py')},
            'cases_dir': str(Path(cases_dir).resolve()), 'targets': [],
            'cost_estimate': {'pricing': rates, 'basis': 'saved benchmark accounting rates; not a current invoice quote',
                'calls': len(requests), 'exact_request_input_coverage': covered,
                'known_input_tokens': input_known, 'observed_output_median': median(outputs),
                'observed_input_median': median(inputs),
                'observed_medians_estimate_usd': len(requests) * (median(inputs) * rates['sonnet_input'] +
                    median(outputs) * rates['sonnet_output']) / 1e6,
                'known_input_plus_median_output_usd': (input_known * rates['sonnet_input'] +
                    len(requests) * median(outputs) * rates['sonnet_output']) / 1e6,
                'output_cap_usd': len(requests) * 1024 * rates['sonnet_output'] / 1e6,
                'note': 'Input usage for unmatched requests is unavailable; output cap excludes input and is not a total ceiling.'},
            'timing_limitations': 'Recovered E2E is original saved selection duration plus later measured generation duration; not contemporaneous wall-clock latency.'}
    for row in rows:
        if key(row) in requests:
            plan['targets'].append({'identity': key(row), 'source_record_sha256': digest(row),
                'selection_sha256': digest(row['selection']), 'request_sha256': digest(requests[key(row)]),
                'request': requests[key(row)]})
    plan['contract_sha256'] = digest(plan)
    write_json(work / 'manifest.json', plan)
    write_json(work / 'journal.json', {'contract_sha256': plan['contract_sha256'], 'attempts': {}})
    atomic(work / 'results.jsonl', (work / 'source_results.jsonl').read_bytes())
    return plan


def load_workspace(work):
    work = Path(work)
    plan = read_json(work / 'manifest.json')
    contract = {k: v for k, v in plan.items() if k != 'contract_sha256'}
    require(digest(contract) == plan['contract_sha256'], "Recovery manifest changed")
    for name, expected in plan['source_artifact_sha256'].items():
        require(file_hash(work / ('source_' + name)) == expected, "Recovery source snapshot changed")
    for name, expected in plan['implementation_sha256'].items():
        require(file_hash(BASE / name) == expected, f"Recovery implementation changed: {name}")
    # Recheck original fixture hashes on every continuation.
    for recorded, expected in plan['original_manifest']['inputs'].items():
        parts = Path(recorded).parts
        require(file_hash(Path(plan['cases_dir']) / Path(*parts[parts.index('cases') + 1:])) == expected,
                "Recovery fixture changed")
    journal = read_json(work / 'journal.json')
    require(journal['contract_sha256'] == plan['contract_sha256'], "Recovery journal contract mismatch")
    rows = [json.loads(l) for l in (work / 'source_results.jsonl').read_text().splitlines()]
    targets = {t['identity']: t for t in plan['targets']}
    require(set(journal['attempts']) <= set(targets), "Unexpected recovery trial")
    for identity, attempts in journal['attempts'].items():
        require(bool(attempts), 'Empty recovery attempt history')
        for number, attempt in enumerate(attempts, 1):
            require(attempt.get('identity') == identity and attempt.get('attempt') == number and
                    attempt.get('request_sha256') == targets[identity]['request_sha256'],
                    'Recovery receipt belongs to another trial/request')
            require(attempt.get('state') in {'in_flight', 'definite_failure', 'completed'},
                    'Unknown recovery state')
            if attempt['state'] == 'completed':
                validate_generation(attempt['generation'])
        require(all(a['state'] == 'definite_failure' for a in attempts[:-1]),
                'A completed/uncertain call was repeated')
    for row in rows:
        if key(row) in targets:
            target = targets[key(row)]
            require(digest(row) == target['source_record_sha256'] and
                    digest(row['selection']) == target['selection_sha256'] and
                    digest(target['request']) == target['request_sha256'], "Recovery identity drift")
    return plan, rows, journal


def validate_generation(value):
    require(value.get('provider') == 'anthropic' and value.get('model') == MODEL, "Wrong recovered generator")
    require(isinstance(value.get('text'), str), "Missing generator text")
    for name in ('input_tokens', 'output_tokens'):
        require(type(value.get(name)) is int and value[name] >= 0, f"Missing/invalid {name}")
    elapsed = value.get('latency_seconds')
    require(type(elapsed) in (float, int) and math.isfinite(elapsed) and elapsed >= 0, "Missing generation timing")
    require(value.get('response_diagnostics', {}).get('stop_reason') in
            ('end_turn', 'max_tokens', 'stop_sequence', 'refusal'), "Unexpected completion status")


def materialize(work, plan, source, journal, *, persist=True):
    rows = deepcopy(source)
    for row in rows:
        attempts = journal['attempts'].get(key(row), [])
        if not attempts or attempts[-1]['state'] != 'completed':
            continue
        attempt = attempts[-1]
        generation = deepcopy(attempt['generation'])
        validate_generation(generation)
        generation['request_hash'] = attempt['request_sha256']
        generation['timing_provenance'] = 'Anthropic SDK duration at recovery; original selection measurement reused'
        for field in ('failure_type', 'error', 'response_diagnostics', 'provider', 'model',
                      'generation_request_hash', 'inference_cost'):
            row.pop(field, None)
        row.update(answer=generation['text'], generation=generation)
        stop = generation['response_diagnostics']['stop_reason']
        failure = 'refusal' if stop == 'refusal' else 'empty_output' if not generation['text'].strip() else None
        row['answer_score'] = ('generation_failure' if failure else
                              score_answer(generation['text'], truth_for(row['case_id'], plan['cases_dir'])))
        if failure:
            row.update(failure_type=failure, response_diagnostics=generation['response_diagnostics'])
        row['end_to_end_latency_seconds'] = row['selection']['latency_seconds'] + generation['latency_seconds']
        rates = plan['cost_estimate']['pricing']
        row['recovery'] = {k: deepcopy(v) for k, v in attempt.items() if k != 'generation'}
        row['recovery'].update(source_run_id=RUN, source_results_sha256=SOURCE_HASHES['results.jsonl'],
            source_record_sha256=digest(next(r for r in source if key(r) == key(row))),
            original_selection_sha256=digest(row['selection']),
            generator_cost_usd=(generation['input_tokens'] * rates['sonnet_input'] +
                                generation['output_tokens'] * rates['sonnet_output']) / 1e6,
            timing_basis=plan['timing_limitations'])
    data = b''.join(encoded(r) + b'\n' for r in rows)
    if persist:
        atomic(Path(work) / 'results.jsonl', data)
        write_json(Path(work) / 'summary.json', summarize(rows))
    return rows


async def anthropic_generation(request):
    # Import only on the explicitly paid path. No selector/client module is imported.
    from anthropic import AsyncAnthropic
    from dotenv import load_dotenv
    load_dotenv(BASE.parents[2] / '.env')
    require(version('anthropic') == SDK, "Original Anthropic SDK version required")
    require(bool(os.environ.get('ANTHROPIC_API_KEY')), "ANTHROPIC_API_KEY is required")
    started = time.perf_counter()
    async with AsyncAnthropic(max_retries=0) as client:
        response = await client.messages.create(model=request['model'], max_tokens=request['max_tokens'],
            messages=[{'role': 'user', 'content': request['prompt']}])
    return {'provider': 'anthropic', 'model': request['model'], 'returned_model': response.model,
            'provider_message_id': response.id,
            'text': ''.join(b.text for b in response.content if b.type == 'text'),
            'input_tokens': response.usage.input_tokens, 'output_tokens': response.usage.output_tokens,
            'latency_seconds': time.perf_counter() - started,
            'response_diagnostics': {'stop_reason': response.stop_reason,
                'content_block_types': [b.type for b in response.content],
                'usage_metadata': response.usage.model_dump(mode='json')}}


async def execute(work, *, generate=anthropic_generation, retry_failed=False):
    work = Path(work)
    with (work / '.recovery.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan, source, journal = load_workspace(work)
        materialize(work, plan, source, journal)
        # Stop before any new calls if any earlier outcome is unresolved.
        for identity, attempts in journal['attempts'].items():
            require(attempts[-1]['state'] != 'in_flight',
                    f"Uncertain provider outcome: {identity}; reconcile its response before continuing")
            require(attempts[-1]['state'] != 'definite_failure' or retry_failed,
                    f"Recorded provider rejection: {identity}; explicit --retry-failed required")
        for target in plan['targets']:
            identity = target['identity']
            attempts = journal['attempts'].setdefault(identity, [])
            if attempts and attempts[-1]['state'] == 'completed':
                continue
            attempt = {'identity': identity, 'attempt': len(attempts) + 1, 'state': 'in_flight',
                       'started_at_utc': now(), 'request_sha256': target['request_sha256'],
                       'anthropic_sdk': SDK, 'transport_max_retries': 0}
            attempts.append(attempt)
            write_json(work / 'journal.json', journal)
            try:
                generation = await generate(deepcopy(target['request']))
            except Exception as error:
                # Network errors/timeouts/5xx may have consumed a call: never auto-retry.
                status = getattr(error, 'status_code', None)
                if status in (400, 401, 403, 404, 422, 429):
                    attempt['state'] = 'definite_failure'
                attempt.update(error_type=type(error).__name__, http_status=status, ended_at_utc=now())
                write_json(work / 'journal.json', journal)
                raise RuntimeError(f"Recovery stopped at {identity}; status {attempt['state']}") from None
            # Persist the returned output before validation or rebuilding aggregate files.
            attempt.update(state='completed', ended_at_utc=now(), generation=generation)
            write_json(work / 'journal.json', journal)
            validate_generation(generation)
            materialize(work, plan, source, journal)
        return materialize(work, plan, source, journal)


def review_template(work):
    plan, source, journal = load_workspace(work)
    rows = materialize(work, plan, source, journal)
    require(all(a and a[-1]['state'] == 'completed' for a in
                (journal['attempts'].get(t['identity']) for t in plan['targets'])), "Recovery not completed")
    original_audit = read_json(BASE / 'analysis' / RUN / 'answer_audit.json')
    historical = {key(r): r for r in original_audit if r['method'] == 'bge_omneum'}
    entries = []
    for row in rows:
        truth = read_json(Path(plan['cases_dir']) / row['case_id'] / 'ground_truth.json')
        old = historical.get(key(row))
        entries.append({'identity': key(row), 'record_sha256': digest(row), 'answer': row['answer'],
            'reference_answer': truth['answer'], 'evidence': row['selection']['selected'],
            'expected_supporting_sources': truth['supporting_sources'], 'recorded_score': row['answer_score'],
            'manual_status': old['manual_status'] if old else None, 'reason': old['reason'] if old else None,
            'adjudication_provenance': 'unchanged historical Omneum audit' if old else 'pending manual review'})
    value = {'run_id': RUN, 'results_sha256': file_hash(Path(work) / 'results.jsonl'), 'entries': entries}
    path = Path(work) / 'answer_audit.template.json'
    require(not path.exists(), "Review template exists; never overwrite manual work")
    write_json(path, value)
    return value


def import_response(work, receipt_path):
    """Reconcile a separately retained response without issuing a provider call.

    The operator supplies the response's exact run/trial/request provenance;
    outputs from other runs or prompts are rejected. Ambiguous calls stay blocked
    until such a response is available. Import never overwrites a completed call.
    """
    work = Path(work)
    with (work / '.recovery.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan, source, journal = load_workspace(work)
        receipt = read_json(receipt_path)
        target = next((t for t in plan['targets'] if t['identity'] == receipt.get('identity')), None)
        require(target is not None and receipt.get('source_run_id') == RUN and
                receipt.get('source_results_sha256') == SOURCE_HASHES['results.jsonl'] and
                receipt.get('source_record_sha256') == target['source_record_sha256'] and
                receipt.get('request_sha256') == target['request_sha256'],
                'Imported response is not tied to this source run/trial/request')
        require(receipt.get('request') == target['request'], 'Imported generator configuration mismatch')
        generation = receipt['generation']
        validate_generation(generation)
        require(bool(generation.get('provider_message_id')) and bool(receipt.get('started_at_utc')) and
                bool(receipt.get('ended_at_utc')), 'Response identity/timestamps required')
        attempts = journal['attempts'].setdefault(target['identity'], [])
        require(not attempts or attempts[-1]['state'] == 'in_flight',
                'Only a missing/uncertain response can be imported')
        if not attempts:
            attempts.append({'identity': target['identity'], 'attempt': 1,
                             'request_sha256': target['request_sha256']})
        attempts[-1].update(state='completed', started_at_utc=receipt['started_at_utc'],
            ended_at_utc=receipt['ended_at_utc'], generation=generation,
            imported_receipt_sha256=file_hash(receipt_path), imported_at_utc=now(),
            provenance='operator-reconciled separately saved response; no new provider call')
        write_json(work / 'journal.json', journal)
        return materialize(work, plan, source, journal)


def validate(work, adjudication):
    plan, source, journal = load_workspace(work)
    expected = materialize(work, plan, source, journal, persist=False)
    saved = [json.loads(l) for l in (Path(work) / 'results.jsonl').read_text().splitlines()]
    require(saved == expected, 'Raw recovered records differ from source/journal')
    require(read_json(Path(work) / 'summary.json') == summarize(expected), 'Recovered summary mismatch')
    require(all(journal['attempts'].get(t['identity'], [{}])[-1].get('state') == 'completed'
                for t in plan['targets']), "Unresolved recovery calls")
    audit = read_json(adjudication)
    require(audit.get('run_id') == RUN and audit.get('results_sha256') == file_hash(Path(work) / 'results.jsonl'),
            "Adjudication belongs to different results")
    entries = {r['identity']: r for r in audit['entries']}
    historical = {key(r): r for r in read_json(
        BASE / 'analysis' / RUN / 'answer_audit.json') if r['method'] == 'bge_omneum'}
    require(len(entries) == len(audit['entries']) == 480 and set(entries) == {key(r) for r in source},
            "Incomplete/duplicate adjudication schedule")
    for original, row in zip(source, expected):
        require(row['selection'] == original['selection'] and row['selection_score'] == original['selection_score']
                and row['selected'] == original['selected'], "Selection measurement changed")
        if key(original) not in {t['identity'] for t in plan['targets']}:
            require(row == original, "Previously successful/historical record changed")
        review = entries[key(row)]
        if row['method'] == 'bge_omneum':
            require(review.get('manual_status') == historical[key(row)]['manual_status'],
                    'Historical Omneum adjudication changed')
        require(review['record_sha256'] == digest(row), "Adjudication record hash mismatch")
        require(review.get('manual_status') in STATUSES and bool(review.get('reason')), "Incomplete manual review")
        if row['answer_score'] == 'generation_failure':
            require(review['manual_status'] in {'generator_refusal', 'provider_failure', 'empty_output'},
                    "Generation failure cannot be adjudicated correct")
        else:
            require(review['manual_status'] in {'correct', 'incomplete', 'substantively_incorrect'},
                    "Generated answer has invalid adjudication category")
    summary = summarize(expected)
    rates = plan['cost_estimate']['pricing']
    metrics = {}
    for method in ('bge_google', 'bge_omneum'):
        selected = [r for r in expected if r['method'] == method]
        require(summary[method]['generator_usage']['total_tokens']['n'] == 240, "Incomplete generator usage")
        metrics[method] = {'precision': summary[method]['selection_precision'],
            'recall': summary[method]['selection_recall'],
            'accuracy': sum(entries[key(r)]['manual_status'] == 'correct' for r in selected) / 240,
            'selection_p50_seconds': summary[method]['latency']['selection_seconds']['p50'],
            'end_to_end_p50_seconds': summary[method]['latency']['end_to_end_seconds']['p50'],
            'generator_tokens': summary[method]['generator_usage']['total_tokens']['sum'],
            'generator_cost_usd': sum((r['generation']['input_tokens'] * rates['sonnet_input'] +
                                     r['generation']['output_tokens'] * rates['sonnet_output']) / 1e6 for r in selected),
            'generation_failures': summary[method]['generation_failures']}
    value = {'run_id': RUN, 'results_sha256': audit['results_sha256'],
             'adjudication_sha256': file_hash(adjudication), 'metrics': metrics,
             'timing_limitations': plan['timing_limitations'],
             'selection_speedup': metrics['bge_google']['selection_p50_seconds'] /
                                  metrics['bge_omneum']['selection_p50_seconds']}
    write_json(Path(work) / 'comparison.json', value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare', action='store_true')
    action.add_argument('--execute-paid', action='store_true')
    action.add_argument('--review-template', action='store_true')
    action.add_argument('--validate', action='store_true')
    action.add_argument('--import-response', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--adjudication', type=Path)
    args = parser.parse_args()
    if args.prepare:
        parser.error('--source is required for preparation') if args.source is None else None
        result = prepare(args.source, args.work_dir)
        print(json.dumps({'run_id': RUN, 'remaining_calls': len(result['targets']),
                          'cost_estimate': result['cost_estimate']}, indent=2))
    elif args.execute_paid:
        require(args.resume, 'Use --resume to execute the prepared, reviewed recovery plan')
        rows = asyncio.run(execute(args.work_dir, retry_failed=args.retry_failed))
        print(json.dumps(summarize(rows), indent=2))
    elif args.review_template:
        review_template(args.work_dir)
        print('Review template written; complete manual adjudication before validation/publication.')
    elif args.import_response:
        import_response(args.work_dir, args.import_response)
        print('Response reconciled offline; no provider calls made.')
    else:
        require(args.adjudication is not None, '--adjudication is required')
        print(json.dumps(validate(args.work_dir, args.adjudication), indent=2))


if __name__ == '__main__':
    main()
