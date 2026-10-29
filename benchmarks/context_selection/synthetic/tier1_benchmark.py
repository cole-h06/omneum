"""Run repeated, selection-only Tier 1 measurements with recorded relevance."""
import argparse
from .execution_safety import DEFAULT_TRACE, pinned_file, read_trace
import asyncio
import csv
import hashlib
import importlib.metadata
import inspect
import itertools
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import time
from unittest.mock import patch

import httpx

from omneum import coalesce_observations, open_stdio_client
from omneum.context_selection import claim_id
from omneum.query_context import discover_chunks
from benchmarks.context_selection import deployment
from benchmarks.context_selection.config import estimator_config
from benchmarks.context_selection.paths import resolve_artifact
from .loader import load_case, load_ground_truth
from .tier1_metrics import measure, summarize

BASE = Path(__file__).resolve().parent
METHODS = ('bge', 'bge_omneum', 'embedding', 'embedding_omneum', 'bm25', 'bm25_omneum')
BUDGETS = (64, 96, 128, 160, 192, 256)


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def environment():
    packages = {}
    for name in ('omneum', 'mcp', 'httpx', 'orjson', 'numpy', 'sentence-transformers', 'transformers'):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    hardware = {}
    if sys.platform == 'darwin':
        for name in ('hw.model', 'hw.memsize', 'machdep.cpu.brand_string'):
            result = subprocess.run(['sysctl', '-n', name], capture_output=True, text=True)
            hardware[name] = result.stdout.strip() if result.returncode == 0 else None
    return dict(python=sys.version, platform=platform.platform(), cpu_count=os.cpu_count(),
                hardware=hardware, packages=packages,
                git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())


def configuration(args, meta):
    names = ['Answer Accuracy','Evidence Retention','Actual Context Tokens','Accuracy at Matched Tokens',
             'Context Reduction','Claim Coverage','Independent Evidence Coverage','Selection p50/p95 Latency',
             'End-to-End p50/p95 Latency','Estimated API Cost']
    states = ['skipped','reconstructed and execution-validated','reconstructed and execution-validated','skipped',
              'reconstructed','partial: explicit gold-claim labels absent','reconstructed from source-dependency annotations',
              'new repeated measurements','skipped','local execution: 0.00 USD']
    definitions = {
        'evidence_retention':'Retained word/punctuation footprint of unioned exact evidence spans in gold supporting passages / total footprint of those spans. Headers excluded. Distinct from unweighted source recall.',
        'actual_context_tokens':r'len(re.findall(r"\w+|[^\w\s]", rendered_context)); includes actual chunk headers.',
        'context_reduction':'(raw_context_footprint-selected_context_footprint)/raw_context_footprint; same renderer and word/punctuation counter on both sides.',
        'gold_claim_coverage':'Missing: no explicit required/gold claim-ID annotation exists. Null, never replaced silently.',
        'supporting_passage_claim_coverage':'Distinct canonical claim IDs retained / union of canonical claim IDs in gold supporting passages. Existing harness definition; includes incidental facts and is not a minimal answer-fact metric.',
        'independent_evidence_coverage':'Union of annotated root-origin units represented by retained GOLD passages / union represented by all gold supporting passages. Edges are declared upstream, citation and parent-observation references. Root cycles collapse to one unresolved origin unit. No estimator weights, temporal similarity or dependency-cluster threshold are used.',
        'dependency_cluster_coverage':'Separate reused diagnostic: distinct required-claim/estimated-cluster pairs covered. Not independent-origin coverage.',
        'source_metrics':'Existing score_selection precision and recall against all annotated supporting sources; unchanged denominators.',
        'budget':'Original Qwen2.5 7B tokenizer units, exact rendered context. Word/punctuation footprint is a separate measurement and can exceed the numeric tokenizer budget.',
        'budget_normalized_source_recall':'Reused exact rendered-subset feasibility ceiling for the recorded method-specific renderer order; never the passage-count formula.',
        'selection_ms':'Fresh wall time after supplied relevance scores and canonical observations are available. Baselines: sorting, first-fit packing, rendering. Hybrids: full prepare_context including fresh graph evaluation, discovery, packing, reconstruction and SDK validation. No evaluation receipt reuse.',
        'timing_exclusions':'Dataset loading, semantic model initialization AND model relevance inference excluded for every arm. Exact tokenizer counts prewarmed for every possible whole-chunk subset/order used by the harness. Local daemon startup excluded; its graph requests are included.',
        'graph_ms':'SDK-reported server graph execution duration. MCP roundtrip and client verification inference are separate, overlapping components; do not sum them.',
        'packing_ms':'SDK chunk_selection_latency_ms includes proposal rendering/token checks; baseline pack duration excludes sorting and final render.',
        'percentiles':'Linear interpolation at (n-1)q over all recorded execution samples; quality metrics macro-average unique case-budget cells, not repeats.',
        'cost':'Paid API cost for this local selection-only execution is 0.00 USD; excludes hardware/electricity and historical work.'}
    return dict(methods=METHODS,cases=24,budgets=BUDGETS,repeats=args.repeats,seed=42,
        expected_cells=864,expected_measured_executions=864*args.repeats,warmup_executions=6,
        conflict_aware=False,pipeline='production prepare_context; existing complementary density hybrid configuration',
        source_trace=str(args.trace),source_trace_sha256=sha(args.trace),
        source_artifact_paths=meta['source_sha256'],dataset=str(BASE/'canonical/cases'),
        environment=environment(),tokenizer_endpoint=args.tokenizer,tokenizer=meta['tokenizer'],
        daemon=str(args.daemon),daemon_sha256=sha(args.daemon),
        code_sha256={str(p):sha(p) for p in [Path(__file__),Path(__file__).with_name('tier1_metrics.py')]},
        metric_status=[dict(number=i+1,name=n,status=s) for i,(n,s) in enumerate(zip(names,states))],
        definitions=definitions,limitations=[
            'No downstream generation or answer-accuracy claim.',
            'Independent origins are annotation-relative; absent links do not prove real-world independence. Citation edges use the existing annotation contract, not new entailment judgments.',
            'Gold source labels do not specify a minimal set of answer-required atomic claims.',
            'Selection timing is post-relevance; it is not full BGE/MiniLM retrieval inference latency.',
            'SDK runs use the supported isolated local daemon without SQLite persistence.'])


def snapshot(out):
    markdown = subprocess.check_output(['rg','--files','--hidden','--no-ignore','-g','*.md','-g','!.git/**'],text=True).splitlines()
    files = set(map(Path,markdown))
    for root in (Path('omneum'),BASE):
        files.update(p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and out not in p.parents)
    write(out/'integrity_before.json',dict(markdown_files=markdown,files={str(p):sha(p) for p in sorted(files)}))


def load_trace(path):
    assert path.is_file(), path
    records = read_trace(path)
    meta = records[0]
    for name, digest in meta['source_sha256'].items():
        if name.startswith('omneum/') or '/canonical/' in name:
            pinned_file(name, digest)
    selected = [r for r in records if r['type'] == 'selection'
                and r['method'] in METHODS and not r['conflict_aware']]
    assert len(selected) == 864
    return meta, selected, {r['case_id']: r for r in records if r['type'] == 'graph'}


def quality(records):
    rows = []
    for r in records:
        directory = BASE / 'canonical/cases' / r['case_id']
        case = json.loads((directory / 'case.json').read_text())
        truth = load_ground_truth(directory / 'ground_truth.json')
        row = dict(case_id=r['case_id'], method=r['method'], budget=r['budget'],
                   selected=r['selected'], context=r['context'], origin='reused production trace',
                   tokenizer_tokens=r['selected_tokens'], tokenizer_utilization=r['selected_tokens']/r['budget'],
                   dependency_cluster_coverage=r['required_claim_dependency_cluster_coverage'],
                   budget_normalized_source_recall=r['source_budget_metrics']['budget_normalized_source_recall'],
                   eligible=r['eligible'], excluded=r['excluded'],
                   **measure(case, truth, r['selected'], r['context']))
        assert row['source_recall'] == r['selection_score']['recall']
        assert row['supporting_passage_claim_coverage'] == r['required_claim_coverage']
        rows.append(row)
    return rows


def prepare_cases(graphs):
    from .query_benchmark import inputs
    cases = {}
    for path in sorted((BASE / 'canonical/cases').glob('*/case.json')):
        case = load_case(path)
        observations, chunks, _ = inputs(case)
        graph, _ = coalesce_observations(observations)
        scores = json.loads((BASE / 'canonical/retrieval' / (case.case_id+'-retrieval.json')).read_text())
        support = {c['claim_id']: c['support'] for c in graphs[case.case_id]['claims']}
        order = sorted(chunks, key=lambda c: -sum(support[a] for a in c['claim_ids']))
        cases[case.case_id] = dict(case=case, graph=graph, chunks=chunks, scores=scores, order=order)
    assert len(cases) == 24
    return cases


def make_summary(out):
    cells = json.loads((out / 'selections.json').read_text())
    with (out / 'timings.csv').open() as stream:
        runs = list(csv.DictReader(stream))
    for r in runs:
        r['budget'] = int(r['budget'])
    manifest = json.loads((out / 'manifest.json').read_text())
    return dict(configuration=manifest,
                aggregate=summarize(cells, runs),
                per_budget={str(b): summarize([r for r in cells if r['budget']==b],
                            [r for r in runs if r['budget']==b]) for b in BUDGETS})


def integrity(out):
    before = json.loads((out / 'integrity_before.json').read_text())
    changed = [p for p, digest in before['files'].items() if not Path(p).is_file() or sha(Path(p)) != digest]
    markdown = subprocess.check_output(['rg', '--files', '--hidden', '--no-ignore', '-g', '*.md', '-g', '!.git/**'], text=True).splitlines()
    result = dict(protected_files=len(before['files']), markdown_files=len(markdown),
                  changed=changed, markdown_inventory_unchanged=set(markdown)==set(before['markdown_files']))
    write(out / 'integrity_after.json', result)
    assert not changed and result['markdown_inventory_unchanged'], result


async def run(args):
    from . import prepare_benchmark as base
    out = args.output
    assert args.repeats >= 2 and args.daemon.is_file()
    assert not (out / 'manifest.json').exists(), 'Never overwrite an existing run'
    out.mkdir(parents=True,exist_ok=True)
    if not (out/'integrity_before.json').exists():
        snapshot(out)
    assert inspect.signature(discover_chunks).parameters['conflict_aware'].default is False
    meta, recorded, graphs = load_trace(args.trace)
    write(out/'manifest.json',configuration(args,meta))
    cells = quality(recorded)
    write(out / 'selections.json', cells)
    cases = prepare_cases(graphs)
    reference = {(r['case_id'],r['method'],r['budget']):r for r in cells}
    counts = {}
    with httpx.Client(trust_env=False, timeout=60) as http:
        def count(text):
            if text not in counts:
                response = http.post(args.tokenizer+'/tokenize', json={
                    'content':text, 'add_special':False, 'parse_special':True}).raise_for_status().json()
                counts[text] = len(response['tokens'])
            return counts[text]
        for data in cases.values():
            chunks = data['chunks']
            count(base.render(chunks))
            orders = [data['order']]
            by_id = {c['chunk_id']:c for c in chunks}
            for method in ('bge','embedding','bm25'):
                scores = data['scores'][method]
                assert set(scores['raw_scores']) == set(by_id)
                ranked = sorted(chunks,key=lambda c:-scores['raw_scores'][c['chunk_id']])
                assert [c['chunk_id'] for c in ranked] == scores['ranking']
                orders.append(ranked)
            for order in orders:
                for size in range(len(order)+1):
                    for subset in itertools.combinations(order,size):
                        count(base.render(subset))
        for r in cells:
            assert count(r['context']) == r['tokenizer_tokens']
        with patch.object(deployment, '_build_daemon', return_value=args.daemon.resolve()):
            with deployment.benchmark_deployment() as (config,server):
                async with open_stdio_client(config,server,local_persistence=None) as client:
                    async def select(cid,method,budget):
                        data = cases[cid]
                        chunks, scores = data['chunks'], data['scores'][method.removesuffix('_omneum')]['raw_scores']
                        started = time.perf_counter()
                        if method.endswith('_omneum'):
                            diagnostics = {}
                            result = await client.prepare_context(data['graph'],chunks,estimator=estimator_config(),
                                token_budget=budget,count_tokens=count,token_counter_name='Qwen2.5 7B tokenizer, exact warmed counts',
                                strategy='coverage_support_density',complementary_evidence=True,token_cost_exponent=1,
                                user_query=data['case'].question,chunk_relevance=scores,
                                relevance_score_type='reranker_score' if method=='bge_omneum' else 'similarity',
                                candidate_discovery='expanded',candidate_count=3,expansion_depth=2,query_evaluation='full',
                                query_diagnostics=diagnostics,include_telemetry=True)
                            elapsed = (time.perf_counter()-started)*1000
                            t = result['telemetry']
                            stages = dict(graph_ms=t['graph_evaluation_latency_ms'],packing_ms=t['chunk_selection_latency_ms'],
                                reconstruction_ms=t['context_reconstruction_latency_ms'],mcp_ms=t['mcp_roundtrip_latency_ms'],
                                verification_inference_ms=t['local_inference_latency_ms'],
                                discovery_ms=diagnostics['candidate_discovery_latency_ms'])
                            selected, context, tokens = result['packed_chunk_ids'],result['context'],result['selection']['selected_tokens']
                        else:
                            ranked = sorted(chunks,key=lambda c:-scores[c['chunk_id']])
                            packed = time.perf_counter()
                            chosen = base.pack(ranked,budget,count)
                            packing_ms = (time.perf_counter()-packed)*1000
                            rendered = time.perf_counter()
                            context = base.render(chosen)
                            reconstruction_ms = (time.perf_counter()-rendered)*1000
                            elapsed = (time.perf_counter()-started)*1000
                            stages = dict(graph_ms=None,packing_ms=packing_ms,reconstruction_ms=reconstruction_ms,
                                          mcp_ms=None,verification_inference_ms=None,discovery_ms=None)
                            selected, tokens = [c['chunk_id'] for c in chosen],count(context)
                        expected = reference[cid,method,budget]
                        assert (selected,context,tokens) == (expected['selected'],expected['context'],expected['tokenizer_tokens'])
                        assert count(context) == tokens <= budget
                        return dict(case_id=cid,method=method,budget=budget,selection_ms=elapsed,
                                    selected=json.dumps(selected),tokenizer_tokens=tokens,**stages)
                    for method in METHODS:
                        await select(next(iter(cases)),method,128)
                    jobs = [(cid,m,b,t) for cid in cases for m in METHODS for b in BUDGETS for t in range(args.repeats)]
                    random.Random(42).shuffle(jobs)
                    with (out / 'timings.csv').open('x',newline='') as stream:
                        columns = ['case_id','method','budget','repeat','selection_ms','graph_ms','packing_ms',
                                   'reconstruction_ms','mcp_ms','verification_inference_ms','discovery_ms','selected','tokenizer_tokens']
                        writer = csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
                        for index,(cid,method,budget,repeat) in enumerate(jobs,1):
                            row = await select(cid,method,budget)
                            writer.writerow(dict(row,repeat=repeat));stream.flush()
                            if index % 144 == 0:
                                print('Completed',index,'of',len(jobs),'selection executions',flush=True)
    write(out / 'summary.json', make_summary(out))
    integrity(out)
    print('Complete:',out,flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trace',type=Path,default=DEFAULT_TRACE)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--tokenizer',default='http://127.0.0.1:57702')
    p.add_argument('--daemon',type=Path,default=Path('target/test-daemon/debug/omneumd'))
    p.add_argument('--repeats',type=int,default=5)
    p.add_argument('--verify',action='store_true')
    args = p.parse_args()
    if args.verify:
        assert make_summary(args.output) == json.loads((args.output/'summary.json').read_text())
        print('Summary reproduced exactly from selections.json and timings.csv')
        return
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
