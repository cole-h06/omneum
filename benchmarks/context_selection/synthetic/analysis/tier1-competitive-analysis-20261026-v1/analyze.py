"""Offline analysis of frozen context-selection artifacts. No services, inference, or benchmark runs."""
from pathlib import Path
from types import SimpleNamespace
from collections import defaultdict, Counter
import csv
import hashlib
import json
import sys
import math
import numpy as np

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
from benchmarks.context_selection.synthetic.tier1_metrics import measure, origins
from benchmarks.context_selection.synthetic.execution_safety import require_new_output

BASE = ROOT / 'benchmarks/context_selection/synthetic'
OUT = Path(__file__).resolve().parent
PRIMARY = BASE / 'results/tier1-competitors-20261025-v1'
PRIOR = BASE / 'results/tier1-production-20261025-v1'
PROVIDERS = BASE / 'results/question-aware-release-v1'
METRICS = ['source_precision','source_recall','evidence_retention',
           'supporting_passage_claim_coverage','independent_evidence_coverage',
           'actual_context_tokens','context_reduction','tokenizer_tokens']
RATIOS = set(METRICS) - {'actual_context_tokens','tokenizer_tokens'}
LABEL = dict(raw_budget='Standard RAG (original-order first-fit)',raw_full='Raw full (unbudgeted)',
    bm25='BM25',embedding='MiniLM embeddings',bge='BGE Reranker v2-m3',cohere='Cohere Rerank v4.0 Pro',
    claude='Claude Sonnet 5.5',gpt='GPT-6 Astra',gemini='Gemini 3.8 Flash',omneum='Omneum standalone',
    bm25_omneum='BM25 + Omneum',embedding_omneum='MiniLM + Omneum',
    bge_omneum='BGE Reranker + Omneum',cohere_omneum='Cohere + Omneum')
SHORT = dict(source_precision='Precision',source_recall='Recall',evidence_retention='Evidence',
    supporting_passage_claim_coverage='Claims',independent_evidence_coverage='Origins',
    actual_context_tokens='Context footprint',context_reduction='Reduction',tokenizer_tokens='Qwen tokens')
OM = ['omneum','bm25_omneum','embedding_omneum','bge_omneum','cohere_omneum']
STAND = ['raw_budget','bm25','embedding','bge','cohere','claude','gpt','gemini']
BUDGETS = [64,96,128,160,192,256]
SEED, REPS = 20261026, 50000

def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name, data): (OUT/name).write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
def csvsave(name, rows):
    rows=list(rows)
    with (OUT/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,r))+' |' for r in rows])
def fmt(v,n=3): return 'NA' if v is None else f'{v:.{n}f}'

def main(output):
    global OUT
    OUT = Path(output)
    require_new_output(OUT, protected=(PRIMARY, PRIOR, PROVIDERS, BASE / "canonical", Path(__file__).parent))
    # Hash every input used, including implementation, before calculations.
    paths=set()
    for directory in (PRIMARY,PRIOR,BASE/'canonical',PROVIDERS):
        paths.update(p for p in directory.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.update(BASE/p for p in ['tier1_metrics.py','tier1_benchmark.py','tier1_competitors.py',
        'scoring.py','prepare_benchmark.py','release_benchmark.py','sdk_adapter.py','spending.py'])
    before={str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)}
    summary=read(PRIMARY/'summary.json');manifest=read(PRIMARY/'manifest.json')
    records=read(PRIMARY/'selections.json')
    timings=list(csv.DictReader((PRIMARY/'timings.csv').open()))
    provider=[json.loads(l) for l in (PROVIDERS/'provider_results.jsonl').open()]
    cases={p.parent.name:read(p) for p in (BASE/'canonical/cases').glob('*/case.json')}
    truth={c:SimpleNamespace(**read(BASE/'canonical/cases'/c/'ground_truth.json')) for c in cases}
    ids=sorted(cases); methods=sorted({r['method'] for r in records if r['budget'] is not None})
    domains=sorted({c['domain'] for c in cases.values()})
    assert len(ids)==24 and len(domains)==6 and len(methods)==13
    assert sha(PROVIDERS/'provider_results.jsonl')==manifest['provider_sha256']
    assert len(records)==2328 and len(timings)==11640
    lookup={}
    for r in records:
        key=(r['case_id'],r['method'],r['budget'],r.get('trial',0));assert key not in lookup;lookup[key]=r
        computed=measure(cases[r['case_id']],truth[r['case_id']],r['selected'],r['context'])
        for metric,value in computed.items():
            assert r[metric]==value,(key,metric,r[metric],value)
        if r['budget'] is not None: assert 0<=r['tokenizer_tokens']<=r['budget']
        assert set(r['selected'])<=set('chunk-'+c['source_id'] for c in cases[r['case_id']]['candidates'])
    for m in methods:
        trialset={1,2} if m in ('claude','gpt','gemini') else {0}
        assert {(c,bu,t) for c,me,bu,t in lookup if me==m}=={(c,bu,t) for c in ids for bu in BUDGETS for t in trialset}
    timing_counts=Counter()
    for r in timings:
        key=(r['case_id'],r['method'],int(r['budget']) if r['budget'] else None,int(r['trial']) if r.get('trial') else 0)
        ref=lookup[key];timing_counts[key]+=1
        assert json.loads(r['selected'])==ref['selected'] and int(r['tokenizer_tokens'])==ref['tokenizer_tokens']
    assert set(timing_counts.values())=={5}
    for r in read(PRIOR/'selections.json'):
        assert r==lookup[(r['case_id'],r['method'],r['budget'],r.get('trial',0))]
    for r in provider:
        c=cases[r['case_id']]
        old=read(PROVIDERS/(r['case_id']+'-inputs.json'))
        pool=[('chunk-'+v['source_id'],v['text']) for v in c['candidates']]
        assert c['question']==old['case']['question']
        assert pool==[(v['chunk_id'],v['raw_text']) for v in old['chunks']]
        order=[v['source'] for v in r['selected']] if r['method']=='cohere' else r['ranking']
        assert len(order)==len(pool) and set(order)=={k for k,_ in pool}
        if r['method']!='cohere':
            assert r['prompt'].endswith('Question:\n'+c['question']+'\n\nPassages:\n'+'\n\n'.join('['+k+']\n'+v for k,v in pool))
        for bu in BUDGETS:
            selected=lookup[(r['case_id'],r['method'],bu,r['trial'])]['selected']
            assert selected==[k for k in order if k in selected]

    # Average trials first; quality, not timing repeats, defines the estimand.
    cell=defaultdict(list)
    for r in records:
        if r['budget'] is not None: cell[(r['method'],r['case_id'],r['budget'])].append(r)
    values={k:np.array([np.mean([r[f] for r in rows]) for f in METRICS]) for k,rows in cell.items()}
    cube={m:np.array([[values[m,c,b] for b in BUDGETS] for c in ids]) for m in methods}
    means={m:cube[m].mean(axis=(0,1)) for m in methods}
    for m in methods:
        for j,f in enumerate(METRICS):
            assert math.isclose(means[m][j],summary['aggregate'][m][f],abs_tol=1e-12)
    for b in BUDGETS:
        for m in methods:
            for j,f in enumerate(METRICS): assert math.isclose(cube[m][:,BUDGETS.index(b),j].mean(),summary['per_budget'][str(b)][m][f],abs_tol=1e-12)
    for m in LABEL:
        runs=[float(r['selection_ms']) for r in timings if r['method']==m]
        for q,name in [(.5,'p50'),(.95,'p95')]:
            assert math.isclose(float(np.quantile(runs,q)),summary['aggregate'][m]['selection_ms'][name],abs_tol=1e-10)

    # Resample whole cases, retaining all budgets and the trial mean of each cell.
    rng=np.random.default_rng(SEED)
    weights=rng.multinomial(24,np.full(24,1/24),size=REPS)/24
    strat=np.zeros((REPS,24))
    for d in domains:
        pos=[i for i,c in enumerate(ids) if cases[c]['domain']==d]
        strat[:,pos]=rng.multinomial(4,np.full(4,.25),size=REPS)/24
    pairs=sorted(set([(b,b+'_omneum') for b in ('bm25','embedding','bge','cohere')]+
                     [(b,o) for o in OM for b in STAND]))
    pairrows=[];casepair=[];cellpair=[];group_pair=[]
    for left,right in pairs:
        diff=cube[right]-cube[left];case_diff=diff.mean(axis=1)
        boot=weights@case_diff;sb=strat@case_diff
        for j,f in enumerate(METRICS):
            lo,hi=np.quantile(boot[:,j],[.025,.975]);sl,sh=np.quantile(sb[:,j],[.025,.975])
            a,b=means[left][j],means[right][j];v=float(b-a)
            row=dict(baseline=left,comparison=right,metric=f,baseline_mean=float(a),comparison_mean=float(b),
                delta=v,delta_pp=v*100 if f in RATIOS else None,relative_change_pct=(v/a*100 if a else None),
                ci95_low=float(lo),ci95_high=float(hi),stratified_ci95_low=float(sl),stratified_ci95_high=float(sh),
                case_wins=int((case_diff[:,j]>1e-12).sum()),case_ties=int((abs(case_diff[:,j])<=1e-12).sum()),case_losses=int((case_diff[:,j]<-1e-12).sum()),
                cell_wins=int((diff[:,:,j]>1e-12).sum()),cell_ties=int((abs(diff[:,:,j])<=1e-12).sum()),cell_losses=int((diff[:,:,j]<-1e-12).sum()))
            pairrows.append(row)
            for i,c in enumerate(ids):
                casepair.append(dict(baseline=left,comparison=right,case_id=c,domain=cases[c]['domain'],metric=f,delta=float(case_diff[i,j])))
                for k,bu in enumerate(BUDGETS):cellpair.append(dict(baseline=left,comparison=right,case_id=c,budget=bu,metric=f,delta=float(diff[i,k,j])))
            for d in domains:
                ix=[i for i,c in enumerate(ids) if cases[c]['domain']==d]
                group_pair.append(dict(baseline=left,comparison=right,group_type='domain',group=d,metric=f,delta=float(diff[ix,:,j].mean())))
            for k,bu in enumerate(BUDGETS):group_pair.append(dict(baseline=left,comparison=right,group_type='budget',group=bu,metric=f,delta=float(diff[:,k,j].mean())))
    OUT.mkdir(parents=True, exist_ok=False)
    csvsave('paired_comparisons.csv',pairrows);csvsave('paired_case_deltas.csv',casepair)
    csvsave('paired_case_budget_deltas.csv',cellpair);csvsave('paired_domain_budget_deltas.csv',group_pair)
    pairmap={(r['baseline'],r['comparison'],r['metric']):r for r in pairrows}
    def p(left,right,f):return pairmap[left,right,f]

    def aggregates(kind, groups):
        rows=[]
        for group,ix,bix in groups:
            for m in methods:
                a=cube[m][ix][:,bix].mean(axis=(0,1))
                rows.append({kind:group,'method':m,**dict(zip(METRICS,map(float,a)))})
        return rows
    domainrows=aggregates('domain',[(d,[i for i,c in enumerate(ids) if cases[c]['domain']==d],list(range(6))) for d in domains])
    budgetrows=aggregates('budget',[(b,list(range(24)),[k]) for k,b in enumerate(BUDGETS)])
    caserows=aggregates('case_id',[(c,[i],list(range(6))) for i,c in enumerate(ids)])
    csvsave('by_domain.csv',domainrows);csvsave('by_budget.csv',budgetrows);csvsave('by_case.csv',caserows)
    csvsave('trial_level_metrics.csv',[{k:r.get(k,0 if k=='trial' else None) for k in ['case_id','method','budget','trial',*METRICS]} for r in records])
    csvsave('case_budget_trial_means.csv',[dict(method=m,case_id=c,budget=b,**dict(zip(METRICS,map(float,a)))) for (m,c,b),a in values.items()])

    # Costs use only saved rate assumptions, not a live price lookup or an invoice.
    rates={'claude':(2,10),'gpt':(10,50),'gemini':(.75,3.75)}
    usage=[]
    for m in ('claude','gpt','gemini','cohere'):
        rr=[r for r in provider if r['method']==m]
        if m=='cohere':
            usage.append(dict(method=m,requests=len(rr),input_tokens=None,output_tokens=None,reported_reasoning_tokens=None,
                reasoning_unknown_requests=len(rr),estimated_saved_rate_usd=None,input_rate_per_million=None,output_rate_per_million=None));continue
        inp=sum(r['input_tokens'] for r in rr)
        out=sum((r['usage_metadata']['total_token_count']-r['input_tokens']) if m=='gemini' else r['output_tokens'] for r in rr)
        reasoning=[r['usage_metadata'].get('reasoning_tokens') for r in rr]
        usage.append(dict(method=m,requests=len(rr),input_tokens=inp,output_tokens=out,
            reported_reasoning_tokens=sum(reasoning) if all(v is not None for v in reasoning) else None,
            reasoning_unknown_requests=sum(v is None for v in reasoning),estimated_saved_rate_usd=(inp*rates[m][0]+out*rates[m][1])/1e6,
            input_rate_per_million=rates[m][0],output_rate_per_million=rates[m][1]))
    csvsave('provider_usage.csv',usage)
    leader=sorted(methods,key=lambda m:(-means[m][2],m))
    leaderrows=[]
    for rank,m in enumerate(leader,1):
        a=summary['aggregate'][m]
        leaderrows.append(dict(rank_by_evidence=rank,method=m,label=LABEL[m],**dict(zip(METRICS,map(float,means[m]))),
            local_selection_p50_ms=a['selection_ms']['p50'],local_selection_p95_ms=a['selection_ms']['p95'],
            historical_remote_p50_s=a['historical_provider_seconds']['p50'],historical_remote_p95_s=a['historical_provider_seconds']['p95'],
            quality_trial_cells=a['cells'],paired_case_budget_cells=144,local_timing_samples=a['executions']))
    csvsave('leaderboard.csv',leaderrows)
    csvsave('metric_rankings.csv',[dict(metric=f,rank=rank,method=m,value=float(means[m][j]))
        for j,f in enumerate(METRICS) for rank,m in enumerate(sorted(methods,key=lambda m:means[m][j],reverse=f not in ('actual_context_tokens','tokenizer_tokens')),1)])

    # Descriptive dependency strata, derived from saved annotations (not causal labels).
    features=[]
    for c in ids:
        cc=cases[c]['candidates'];oo=origins(cc)
        cyclic=any(len(root)>1 for roots in oo.values() for root in roots)
        linked=any(v['provenance'].get(k) for v in cc for k in ('upstream_sources','cited_sources','parent_assertion_ids'))
        features.append(dict(case_id=c,domain=cases[c]['domain'],candidates=len(cc),has_declared_dependency=linked,
            has_root_cycle=cyclic,gold_root_units=len(set().union(*(oo[s] for s in truth[c].supporting_sources)))))
    csvsave('case_dependency_features.csv',features)
    eligibility=[]
    for m in OM:
        rr=[r for r in records if r['method']==m]
        eligibility.append(dict(method=m,cells=len(rr),cells_with_exclusions=sum(bool(r['excluded']) for r in rr),
            mean_eligible=float(np.mean([len(r['eligible']) for r in rr])),
            mean_excluded=float(np.mean([len(r['excluded']) for r in rr]))))
    csvsave('eligibility.csv',eligibility)
    # Focused budget confidence intervals use 24 whole-case clusters at each budget.
    focused=[]
    for left,right in [(l,l+'_omneum') for l in ('bm25','embedding','bge','cohere')]:
        diff=cube[right]-cube[left]
        boot=(weights@diff.reshape(24,-1)).reshape(REPS,6,len(METRICS))
        low,high=np.quantile(boot,[.025,.975],axis=0)
        for k,bu in enumerate(BUDGETS):
            for j,f in enumerate(METRICS):
                focused.append(dict(baseline=left,comparison=right,budget=bu,metric=f,
                    delta=float(diff[:,k,j].mean()),ci95_low=float(low[k,j]),ci95_high=float(high[k,j])))
    csvsave('hybrid_budget_confidence_intervals.csv',focused)
    dep=[]
    for field in ('has_declared_dependency','has_root_cycle'):
        for val in (False,True):
            ix=[i for i,c in enumerate(ids) if features[i][field]==val]
            if ix:
                for left in ('bm25','embedding','bge','cohere'):
                    for j,f in enumerate(METRICS):dep.append(dict(feature=field,value=val,cases=len(ix),baseline=left,comparison=left+'_omneum',metric=f,delta=float((cube[left+'_omneum']-cube[left])[ix,:,j].mean())))
    csvsave('dependency_strata.csv',dep)

    # Audit historical hashes, including the recorded pre-rename canonical paths.
    historical=[]
    for name,digest in read(PRIOR/'manifest.json')['source_artifact_paths'].items():
        remapped=name.replace('benchmarks/context_evaluation/heldout/','benchmarks/context_selection/synthetic/')
        path=ROOT/remapped
        historical.append(dict(recorded_path=name,current_path=remapped,exists=path.is_file(),matches=sha(path)==digest if path.is_file() else None))
    audit=dict(primary=str(PRIMARY.relative_to(ROOT)),quality_records=len(records),budgeted_configurations=len(methods),
        unbudgeted_configurations=1,cases=24,domains=Counter(c['domain'] for c in cases.values()),budgets=BUDGETS,
        metrics_recomputed=len(records),summary_aggregate_and_budget_matches=True,timing_percentiles_match=True,
        timing_records=len(timings),five_repeats_per_trial_cell=True,original_864_selections_preserved=True,
        provider_prompt_and_pool_checks=True,provider_sha256=sha(PROVIDERS/'provider_results.jsonl'),
        tokenizer_validation='Recorded counts and execution assertions checked; no tokenizer service launched or independent retokenization.',
        packing_validation='Implementation and saved ranking/subsequence checked; skipped packing proposals cannot all be retokenized offline from these files.',
        historical_hash_checks=historical,bootstrap=dict(seed=SEED,replicates=REPS,unit='case',cases=24,
            method='percentile paired cluster bootstrap; sensitivity: stratified by six domains, four cases each',multiplicity_adjustment=False),
        input_sha256=before)
    save('audit.json',audit)

    lines=[]
    def add(s=''):lines.append(s)
    add('# Cross-Domain Context Curation Benchmark — competitive analysis — frozen 2026-10-25 results')
    add('\nEvidence-ranked leaderboard and paired analysis; generated from saved artifacts only. No benchmark reruns, inference, network calls, or production changes.')
    add('\n## Main conclusion\n')
    add('The saved benchmark does not support a blanket claim that Omneum improves established rerankers. Hybrids generally increase precision and reduce context size, but every hybrid loses aggregate source recall and evidence retention. BGE + Omneum has small positive aggregate claim/origin changes whose case-bootstrap intervals include zero. Standalone Omneum improves several metrics over original-order RAG and is competitive on claim/origin coverage against traditional selectors, but loses evidence retention to BM25, MiniLM, BGE, Cohere and all frontier judges. All frontier judges exceed every Omneum configuration on the five aggregate quality metrics. These are selection results conditional on enriched, supplied structured observations.')
    add('\n## Validation and configuration inventory\n')
    add(table(['Requested configuration','Saved arm','Status'],[
        ['Standard RAG','raw_budget','Present: original input order plus first-fit packing; no new retrieval run'],
        ['BM25','bm25','Present: frozen complete-pool scores'],['MiniLM embeddings','embedding','Present: all-MiniLM-L6-v2 bi-encoder'],
        ['BGE embeddings','—','Missing; BGE reranker is not an embedding substitute'],['MiniLM Cross-Encoder','—','Missing'],
        ['BGE Reranker v2-m3','bge','Present: BAAI/bge-reranker-v2-m3 cross-encoder'],
        ['Cohere Rerank v4.0 Pro','cohere','Present: rerank-v4.0-pro'],
        *[[LABEL[m],m,'Present: two saved ranking trials/case'] for m in ('claude','gpt','gemini')],
        *[[LABEL[m],m,'Present: production prepare_context'] for m in OM],
        ['Additional reference','raw_full','Unbudgeted; excluded from competitive ranks']]))
    add('\n13 of the requested 15 configurations are present, plus one unbudgeted reference. “BGE + Omneum” means BGE reranker + Omneum. The case.json context_budget field is a legacy passage-count field; the actual Tier 1 budgets are the six token ceilings in the manifests.')
    add('\nRecomputed all 2,328 selection records with the existing tier1_metrics.measure function and canonical ground truth; every metric matches. All aggregate and per-budget quality means and local timing percentiles reproduce the primary summary. Verified 11,640 timing records, five timing repeats per quality record, complete factorial coverage, canonical selected passage text, candidate membership, saved frontier/Cohere ranking pools, and exact preservation of the 864 original production selections. See audit.json for input hashes and historical source hash checks.')
    add('\nPool and annotation identity holds at the full input level. Selector eligibility is not identical: hybrid candidate discovery/expansion may shortlist or exclude chunks. Rankers use whole-passage first-fit; Omneum uses its production graph-aware packing/discovery. Thus this compares complete selection systems under the same ceilings, not the same packing algorithm. Structured Omneum input includes supplied claims, timestamps, provenance links and evidence metadata; text rankers/judges see question and passages. Gold supporting-source labels are used only for evaluation. Equal passage pools do not establish equal information access or account for extraction/annotation cost.')
    add('\nHybrids use coverage_support_density, complementary_evidence=True, token_cost_exponent=1, expanded candidate discovery with candidate_count=3 (plus score ties), expansion_depth=2 and full query evaluation. BGE uses reranker_score relevance semantics; BM25/MiniLM use similarity, and the saved Cohere hybrid also passes similarity. Standalone uses question=... on the full graph with default lexical passage relevance. All use conflict_aware=False. These exact configurations, rather than a generic Omneum algorithm, are the experimental treatments.')
    add('\nRecorded Qwen2.5 7B tokenizer counts satisfy every budget. No tokenizer or daemon was started; this audit did not independently retokenize or re-execute skipped packing proposals. Historical validation records describe exhaustive warmed tokenizer counts and execution equality. Source hashes in audit.json distinguish saved implementation provenance from the present working tree.')
    add('\nOf 130 historical source-path hash checks, 124 match after resolving the repository directory rename. Five current files differ and omneum/demo.py is absent (details in audit.json). These working-tree differences do not change the frozen metrics, but the current tree should not be presented as byte-identical to the recorded execution. The analysis performs no inference with the changed files.')
    add('\n## Metric and statistical definitions\n')
    add('- Precision/recall: selected source IDs against all annotated supporting sources; an empty selection has precision zero.\n- Evidence retention: retained gold passage evidence-span word/punctuation footprint divided by all gold evidence footprint, after overlapping spans are merged. This weights evidence length.\n- Claims: union of canonical claim IDs present in selected passages intersected with the union in gold passages. Claims in non-gold passages can earn this coverage; incidental facts are included. This is not minimal answer completeness or strict gold-claim coverage.\n- Origins: annotated root-origin units represented by retained gold passages divided by those represented by all gold passages. Root cycles count as one unresolved origin unit; absent edges do not prove real independence.\n- Actual context tokens: regex word/punctuation footprint, including chunk headers. This is not the Qwen tokenizer count. Reduction uses the same footprint on raw and retained context.\n- Macro estimator: mean of trials within each case-budget cell, then equal mean across six budgets and 24 cases. Four cases per domain makes equal-domain and equal-case means identical. Raw full is averaged over 24 cases only.\n- Paired differences compare identical case-budget cells. Bootstrap: 50,000 paired whole-case resamples (seed 20261026), retaining budgets and both judge trials, percentile 95% intervals. A domain-stratified sensitivity resamples four cases within each domain. No multiplicity correction or population-representativeness claim; intervals are descriptive, not confirmatory significance tests. Timing repeats never increase the 24-case sample size.')
    add('\n## Complete leaderboard\n')
    add('Ranked by evidence retention, with no invented composite score. All quality columns are percentages. Footprint and Qwen columns are mean counts. Per-metric ranks are in metric_rankings.csv.')
    add('\n'+table(['Rank','Configuration','Precision','Recall','Evidence','Claims','Origins','Footprint','Reduction','Qwen'],[
        [r['rank_by_evidence'],r['label'],*[fmt(r[f]*100) for f in METRICS[:5]],fmt(r['actual_context_tokens']),fmt(r['context_reduction']*100),fmt(r['tokenizer_tokens'])] for r in leaderrows]))
    raw=summary['aggregate']['raw_full']
    add('\nUnbudgeted raw full: precision '+fmt(raw['source_precision']*100)+'%; recall/evidence/claims/origins 100%; footprint '+fmt(raw['actual_context_tokens'])+'; Qwen '+fmt(raw['tokenizer_tokens'])+'. Its complete retention is not a fair budgeted win.')
    add('\n'+table(['Metric','Strongest Omneum arm','Value'],[[SHORT[f],LABEL[max(OM,key=lambda m:means[m][j])],fmt(max(means[m][j] for m in OM)*(100 if f in RATIOS else 1))] for j,f in enumerate(METRICS) if f in RATIOS]))
    add('\nReduction alone rewards discarding context; it is not an evidence-quality win. MiniLM + Omneum has the smallest mean context footprint and Qwen usage among Omneum arms.')
    add('\n## Five strongest quantitative findings\n')
    def finding(left,right,f):
        r=p(left,right,f)
        return (f"{r['baseline_mean']*100:.6f}% → {r['comparison_mean']*100:.6f}%; "
                f"Δ {r['delta_pp']:+.6f} pp ({r['relative_change_pct']:+.6f}% relative); "
                f"95% CI [{r['ci95_low']*100:+.6f}, {r['ci95_high']*100:+.6f}] pp")
    add('1. **Largest hybrid precision improvement:** BGE → BGE + Omneum: '+finding('bge','bge_omneum','source_precision')+
        '. It improves precision in 17 cases, ties in 3, and loses in 4. Evidence nevertheless changes: '+finding('bge','bge_omneum','evidence_retention')+'.')
    add('2. **Standalone beats original-order RAG:** evidence: '+finding('raw_budget','omneum','evidence_retention')+
        '; claims: '+finding('raw_budget','omneum','supporting_passage_claim_coverage')+
        '; origins: '+finding('raw_budget','omneum','independent_evidence_coverage')+'. This is original-order packing, not a semantic reranker.')
    add('3. **Tight-budget BGE gains reverse:** '+ '; '.join(
        f"budget {bu}, {SHORT[f]} Δ {r['delta']*100:+.6f} pp, 95% CI [{r['ci95_low']*100:+.6f}, {r['ci95_high']*100:+.6f}] pp"
        for bu in (64,256) for f in ('evidence_retention','independent_evidence_coverage')
        for r in focused if r['baseline']=='bge' and r['budget']==bu and r['metric']==f)+'. Budget slices are exploratory.')
    add('4. **Compression has a completeness cost:** MiniLM → MiniLM + Omneum: '+ '; '.join(
        f"{SHORT[f]} {p('embedding','embedding_omneum',f)['baseline_mean']:.6f} → {p('embedding','embedding_omneum',f)['comparison_mean']:.6f} ({p('embedding','embedding_omneum',f)['relative_change_pct']:+.6f}%)"
        for f in ('tokenizer_tokens','actual_context_tokens'))+'; evidence: '+finding('embedding','embedding_omneum','evidence_retention')+
        '; origins: '+finding('embedding','embedding_omneum','independent_evidence_coverage')+'.')
    add('5. **Frontier lead persists against the best Omneum evidence arm:** '+ '; '.join(
        LABEL[l]+' → Cohere + Omneum evidence: '+finding(l,'cohere_omneum','evidence_retention') for l in ('claude','gpt','gemini'))+
        '. All three judges also exceed every Omneum arm on aggregate precision, recall, claim coverage and origin coverage.')
    add('\nExact machine-readable values are authoritative; the assertions and tables below are generated from full precision. Narrative quantities are rounded displays, not additional estimates.')
    add('\n## Paired baseline → hybrid changes\n')
    add('Deltas and confidence intervals are percentage points. Relative changes use (hybrid mean / baseline mean − 1); full results and both bootstrap schemes are in paired_comparisons.csv.')
    add('\n'+table(['Pair','Metric','Baseline %','Hybrid %','Δ pp','Relative %','95% CI pp','Case W/T/L'],[
        [LABEL[l]+' → '+LABEL[l+'_omneum'],SHORT[f],fmt(p(l,l+'_omneum',f)['baseline_mean']*100),fmt(p(l,l+'_omneum',f)['comparison_mean']*100),fmt(p(l,l+'_omneum',f)['delta_pp']),fmt(p(l,l+'_omneum',f)['relative_change_pct']),
         '['+fmt(p(l,l+'_omneum',f)['ci95_low']*100)+', '+fmt(p(l,l+'_omneum',f)['ci95_high']*100)+']',
         '/'.join(str(p(l,l+'_omneum',f)[k]) for k in ('case_wins','case_ties','case_losses'))]
        for l in ('bm25','embedding','bge','cohere') for f in METRICS[:5]]))
    add('\n'+table(['Pair','Δ footprint','Δ Qwen tokens','Footprint relative %','Δ reduction pp'],[
        [LABEL[l]+' → hybrid',fmt(p(l,l+'_omneum','actual_context_tokens')['delta']),fmt(p(l,l+'_omneum','tokenizer_tokens')['delta']),fmt(p(l,l+'_omneum','actual_context_tokens')['relative_change_pct']),fmt(p(l,l+'_omneum','context_reduction')['delta_pp'])] for l in ('bm25','embedding','bge','cohere')]))
    add('\n## Frontier judges versus every Omneum arm\n')
    add('Each entry is Omneum minus judge, in percentage points; both judge trials are averaged before pairing. Every aggregate quality delta below is negative. Detailed case-bootstrap intervals for every entry are in paired_comparisons.csv.')
    add('\n'+table(['Judge','Omneum arm','Δ precision','Δ recall','Δ evidence','Δ claims','Δ origins','Evidence 95% CI'],[
        [LABEL[l],LABEL[r],*[fmt(p(l,r,f)['delta_pp']) for f in METRICS[:5]],'['+fmt(p(l,r,'evidence_retention')['ci95_low']*100)+', '+fmt(p(l,r,'evidence_retention')['ci95_high']*100)+']'] for l in ('claude','gpt','gemini') for r in OM]))
    add('\n## Standalone Omneum versus standalone selectors\n')
    add('\n'+table(['Baseline','Δ precision','Δ recall','Δ evidence','Δ claims','Δ origins'],[[LABEL[l],*[fmt(p(l,'omneum',f)['delta_pp']) for f in METRICS[:5]]] for l in STAND]))
    add('\n## Domain findings\n')
    add('Each domain has four cases. Entries are paired hybrid-minus-baseline percentage points, averaged over six budgets. Domain comparisons are exploratory and have very small case counts; do not infer causal effects of dependency type.')
    add('\n'+table(['Domain','Pair','Δ precision','Δ evidence','Δ claims','Δ origins'],[
        [d,LABEL[l],*[fmt(next(r['delta'] for r in group_pair if r['baseline']==l and r['comparison']==l+'_omneum' and r['group_type']=='domain' and r['group']==d and r['metric']==f)*100) for f in ('source_precision','evidence_retention','supporting_passage_claim_coverage','independent_evidence_coverage')]] for d in domains for l in ('bm25','embedding','bge','cohere')]))
    add('\n## Budget findings\n')
    add('\n'+table(['Budget','Pair','Δ precision','Δ evidence','Δ claims','Δ origins'],[
        [bu,LABEL[l],*[fmt(next(r['delta'] for r in group_pair if r['baseline']==l and r['comparison']==l+'_omneum' and r['group_type']=='budget' and r['group']==bu and r['metric']==f)*100) for f in ('source_precision','evidence_retention','supporting_passage_claim_coverage','independent_evidence_coverage')]] for bu in BUDGETS for l in ('bm25','embedding','bge','cohere')]))
    add('\nComplete metric levels for all 13 configurations by domain, budget, and individual case are in by_domain.csv, by_budget.csv, and by_case.csv. paired_domain_budget_deltas.csv covers all 40 specified baseline/Omneum comparisons, not just hybrids.')
    add('\nBGE hybrid evidence changes by domain: '+ '; '.join(
        f"{r['group']}: {r['delta']*100:+.6f} pp" for r in group_pair if r['baseline']=='bge' and r['comparison']=='bge_omneum' and r['group_type']=='domain' and r['metric']=='evidence_retention')+
        '. Its origin changes are positive in four domains and negative in coding (−17.222 pp) and support (−4.861 pp). This is not a domain-uniform improvement. BGE hybrid precision improves at all six budgets; its evidence improves only at 64 and 96. BM25, MiniLM and Cohere hybrid precision each regresses at 96 tokens. At 256 tokens all four hybrids lose evidence, claims and origin coverage. No hybrid demonstrates all-metric gains that persist across every domain and budget.')
    add('\n## Individual cases, regressions and ties\n')
    for l in ('bm25','embedding','bge','cohere'):
        add('\n'+LABEL[l]+' → hybrid: case-average deltas across all six budgets (pp).')
        add('\n'+table(['Case','Δ precision','Δ evidence','Δ claims','Δ origins'],[[c,*[fmt(float((cube[l+'_omneum']-cube[l])[i,:,METRICS.index(f)].mean())*100) for f in ('source_precision','evidence_retention','supporting_passage_claim_coverage','independent_evidence_coverage')]] for i,c in enumerate(ids)]))
    add('\nEvery case-budget delta, including ties, remains available in paired_case_budget_deltas.csv; trial_level_metrics.csv preserves both judge trials. A positive precision change with negative evidence/recall means cleaner but less complete selection, not more retained evidence. Origin coverage is not interchangeable with claim coverage or amount of evidence.')
    add('\nThe largest recurring evidence regression is coding_package_fix_lineage: case-average loss **44.618 pp** for BM25, **46.181 pp** for MiniLM, **46.528 pp** for BGE, and **45.833 pp** for Cohere hybrids. At budget 256, both BGE and Cohere baselines retain all eight passages using 176 Qwen tokens; their hybrids retain only issue_origin, issue_comment, and release_notes using 62 tokens. Five chunks, including repository_code and test_output, are explicitly excluded as outside_expansion. This directly documents a shortlist-induced completeness ceiling even when the full pool fits the budget; it does not isolate every contribution of graph scoring versus discovery.')
    add('\n'+table(['Arm','Cells with exclusions / 144','Mean eligible passages','Mean excluded passages'],[[LABEL[r['method']],str(r['cells_with_exclusions'])+'/144',fmt(r['mean_eligible']),fmt(r['mean_excluded'])] for r in eligibility]))
    add('\n## Statistical strength and sensitivity\n')
    add('The paired case intervals support substantial precision gains for BM25, BGE and Cohere hybrids under this synthetic-case resampling scheme; MiniLM precision spans zero. Every hybrid evidence-retention interval and source-recall interval lies below zero. BGE aggregate claim gain **+1.712579 pp** has CI **[−6.6712, +9.2533] pp**, and origin gain **+0.949074 pp** has CI **[−5.9491, +7.4074] pp**: neither supports a strong population improvement claim. MiniLM origin regression has CI **[−14.0744, −0.7523] pp**. Most BGE origin cell comparisons tie: **24 wins, 98 ties, 22 losses** out of 144; the aggregate origin gain is small and uneven. All 40 comparisons and eight metrics were examined without multiplicity adjustment.')
    add('\nDomain-stratified sensitivity does not reverse any point estimate. Some marginal intervals change whether they cross zero: MiniLM claim loss crosses zero with ordinary case resampling but not with domain-stratified resampling; standalone Omneum claim differences versus Claude/Gemini and origin differences versus Gemini are similarly sensitive. These must not be promoted as robust superiority/inferiority results. Strong frontier evidence gaps and the major hybrid completeness losses persist under both resampling schemes. Only four cases/domain limits domain inference; synthetic case design limits any population interpretation.')
    add('\n## Dependency structure\n')
    add('Saved provenance defines the exploratory strata below. Root-cycle presence refers to a terminal strongly connected origin unit, not every possible internal cycle. Groups overlap with domain/scenario composition, are not randomized, and cannot isolate the mechanism responsible for changes. Case names and texts describe syndication/copy chains, feedback loops, stale sources, conflicting values and missing lineage; individual-case tables supply the direct evidence without treating these scenario names as new gold labels.')
    add('\n'+table(['Feature','Value','Cases','Pair','Δ evidence pp','Δ origins pp'],[
        [field,val,next(r['cases'] for r in dep if r['feature']==field and r['value']==val),LABEL[l],*[fmt(next(r['delta'] for r in dep if r['feature']==field and r['value']==val and r['baseline']==l and r['metric']==f)*100) for f in ('evidence_retention','independent_evidence_coverage')]]
        for field in ('has_declared_dependency','has_root_cycle') for val in (False,True) if any(r['feature']==field and r['value']==val for r in dep) for l in ('bm25','embedding','bge','cohere')]))
    add('\n## Latency, tokens and cost\n')
    add('\n'+table(['Configuration','Local p50 ms','Local p95 ms','Historical API p50 s','Historical API p95 s'],[[LABEL[m],fmt(summary['aggregate'][m]['selection_ms']['p50'],6),fmt(summary['aggregate'][m]['selection_ms']['p95'],6),fmt(summary['aggregate'][m]['historical_provider_seconds']['p50'],6),fmt(summary['aggregate'][m]['historical_provider_seconds']['p95'],6)] for m in leader+['raw_full']]))
    add('\nLocal ranker times measure sorting/packing/rendering after supplied scores, not relevance inference. Omneum times include graph requests, discovery, packing and client verification, after observations are supplied. Model initialization, dataset loading, daemon startup, upstream structured extraction and relevance scoring are excluded. Token counts were prewarmed. Original six arms and added arms were timed in separate saved executions; avoid attributing tiny local timing differences to model quality. Historical API samples are 24 Cohere requests and 48 per judge, not five fresh remote repeats. Shared ranking cost/latency must not be charged six times for six budgets. No end-to-end latency is available. Stage times overlap and must not be summed.')
    add('\n'+table(['Provider','Saved requests','Input tokens','Output tokens','Reported reasoning','Cost at saved rates USD'],[[LABEL[r['method']],r['requests'],r['input_tokens'],r['output_tokens'],r['reported_reasoning_tokens'] if r['reasoning_unknown_requests']==0 else 'Unknown',fmt(r['estimated_saved_rate_usd'],8)] for r in usage]))
    add('\nCost estimates use only the saved spending.py assumptions: Claude $2/$10, GPT $10/$50, Gemini $0.75/$3.75 per million input/output tokens. These are repriced saved usage, not verified invoices or a new live pricing verification. Gemini output uses total_token_count minus prompt tokens; no additional thinking remainder appears in these records. GPT reports zero reasoning; Claude/Gemini reasoning fields are null. Cohere token usage and verified historical cost are unavailable. Cohere + Omneum shares the same 24 Cohere scoring requests, rather than adding another 24. New API expenditure for the completed local replay and this analysis is zero; hardware/electricity, original provider spend and upstream extraction are not zero-cost claims.')
    add('\n## What the results establish\n')
    add('1. **Established rerankers:** no broad completeness improvement. BGE and Cohere hybrids increase precision, but lose evidence/recall; Cohere also loses claim/origin coverage.\n2. **Largest hybrid gains:** BGE hybrid has the largest precision gain among the four matched hybrids; it is also the only hybrid with positive aggregate claim and origin deltas, which require checking the intervals above. Cohere hybrid has the highest absolute precision among Omneum arms.\n3. **Standalone:** Omneum exceeds original-order RAG on all five quality metrics. Against traditional scored selectors it trades lower evidence/recall for higher aggregate claim/origin coverage; source precision is higher than BM25 but lower than MiniLM, BGE and Cohere.\n4. **Frontier judges:** all three beat all Omneum configurations on aggregate precision, recall, evidence, claims and origins. This does not imply every individual cell is a loss; paired files preserve exceptions.\n5. **Matched budgets:** same maximum budgets, different realized usage. No all-around evidence-quality dominance and no equal-realized-token causal comparison. Smaller contexts alone do not establish better evidence.\n6. **Latency/cost:** roughly 128–134 ms median Omneum selection versus sub-millisecond post-ranking packing; historical judge calls take roughly two seconds. This is a conditional pipeline comparison, not end-to-end retrieval/answer latency.\n7. **Persistence:** inspect domain and budget tables for sign changes; aggregate precision gains do not imply origin gains across domains or budgets.\n8. **Defensible claims:** quote the exact case set, metric, baseline, budget aggregation, confidence interval, input enrichment, and completeness tradeoff. Do not claim broad reranker superiority, frontier-model superiority, downstream answer improvement, or equal-information access.\n9. **Tier 1 limitations:** 24 designed synthetic cases, four/domain; provided structured observations/provenance; no extraction quality/cost evaluation, downstream generation, strict minimal gold claims, answer accuracy, end-to-end latency or real-world independence validation. No unseen public-corpus generalization or ablation-based attribution follows from these artifacts.')
    add('\n## Publication readiness\n')
    add('Suitable for a transparent, narrowly scoped synthetic selection report with these tables and frozen input hashes. Not sufficient for a headline claim that Omneum substantially improves rerankers or beats frontier judges. Research-paper conclusions require external held-out datasets, comparable input-information conditions, extraction accounting, downstream answer evaluation, ablations, and a preregistered primary endpoint. A README can report measured precision/context-size tradeoffs and the conditional latency scope, while showing the evidence/recall regressions alongside them.')
    add('\n## Reproduction and files\n')
    add('Run from the repository root: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B benchmarks/context_selection/synthetic/analysis/tier1-competitive-analysis-20261026-v1/analyze.py --output NEW_ANALYSIS`. This reads saved files and overwrites only derived files in this analysis folder. It launches no tokenizer, daemon, ranking model, API call, or benchmark. Primary and prior runs are combined only through the already-validated primary-run reuse, not through unrelated experiments. Provider records are used solely as the provenance and usage of the rankings already replayed in the primary run.')
    (OUT/'report.md').write_text('\n'.join(lines)+'\n')
    changed=[p for p,digest in before.items() if sha(ROOT/p)!=digest]
    assert not changed,changed
    save('integrity.json',dict(input_files=len(before),changed=changed,original_artifacts_preserved=True))
    print(json.dumps(dict(output=str(OUT),audited_records=len(records),paired_comparisons=len(pairs),bootstrap_replicates=REPS,protected_files=len(before))))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
