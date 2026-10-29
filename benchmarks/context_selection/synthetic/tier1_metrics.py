"""Deterministic Tier 1 calculations from canonical annotations and selections."""
import re
from statistics import mean

from .aggregate import _percentile
from .scoring import score_selection


def footprint(text):
    return len(re.findall(r"\w+|[^\w\s]", text))


def evidence_size(candidate):
    text = candidate['text']
    spans = set()
    for claim in candidate['claims']:
        for span in claim['evidence']:
            assert span['source_id'] == candidate['source_id']
            assert text[span['start']:span['end']] == span['text']
            spans.add((span['start'], span['end']))
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return sum(footprint(text[start:end]) for start, end in merged)


def origins(candidates):
    names = {(c['source']['kind'], c['source']['identifier']): c['source_id'] for c in candidates}
    owners = {claim['observation_id']: c['source_id'] for c in candidates for claim in c['claims']}
    edges = {}
    for c in candidates:
        p = c['provenance']
        refs = p.get('upstream_sources', []) + p.get('cited_sources', [])
        edges[c['source_id']] = {names[(r['kind'], r['identifier'])] for r in refs}
        edges[c['source_id']].update(owners[parent] for parent in p.get('parent_assertion_ids', []))
    reached = {}
    for name in edges:
        seen, pending = set(), [name]
        while pending:
            node = pending.pop()
            if node not in seen:
                seen.add(node)
                pending.extend(edges[node] - seen)
        reached[name] = seen
    roots = set()
    for name in edges:
        group = frozenset(other for other in reached[name] if name in reached[other])
        if all(edges[node] <= group for node in group):
            roots.add(group)
    return {name: {tuple(sorted(root)) for root in roots if root & reached[name]} for name in edges}


def measure(case, truth, selected_ids, context):
    candidates = case['candidates']
    by_id = {'chunk-' + c['source_id']: c for c in candidates}
    assert len(selected_ids) == len(set(selected_ids))
    chosen = [by_id[k] for k in selected_ids]
    expected_context = '\n\n'.join(f"[{k}]\n{by_id[k]['text']}" for k in selected_ids)
    assert context == expected_context
    gold = set(truth.supporting_sources)
    selected = {c['source_id'] for c in chosen}
    score = score_selection(selected, truth)
    gold_claims = {a['claim_id'] for c in candidates if c['source_id'] in gold for a in c['claims']}
    claims = {a['claim_id'] for c in chosen for a in c['claims']}
    evidence = {c['source_id']: evidence_size(c) for c in candidates if c['source_id'] in gold}
    roots = origins(candidates)
    required_origins = set().union(*(roots[s] for s in gold))
    retained_origins = set().union(*(roots[s] for s in selected & gold)) if selected & gold else set()
    raw = '\n\n'.join(f"[chunk-{c['source_id']}]\n{c['text']}" for c in candidates)
    raw_tokens, selected_tokens = footprint(raw), footprint(context)
    return {
        'evidence_retention': sum(evidence[s] for s in selected & gold) / sum(evidence.values()),
        'gold_evidence_footprint': sum(evidence.values()),
        'retained_evidence_footprint': sum(evidence[s] for s in selected & gold),
        'actual_context_tokens': selected_tokens, 'raw_context_tokens': raw_tokens,
        'context_reduction': (raw_tokens - selected_tokens) / raw_tokens,
        'gold_claim_coverage': None,
        'supporting_passage_claim_coverage': len(claims & gold_claims) / len(gold_claims),
        'required_supporting_passage_claims': len(gold_claims),
        'retained_supporting_passage_claims': len(claims & gold_claims),
        'independent_evidence_coverage': len(retained_origins) / len(required_origins),
        'annotated_gold_origins': [list(r) for r in sorted(required_origins)],
        'retained_gold_origins': [list(r) for r in sorted(retained_origins)],
        'cyclic_gold_origins': [list(r) for r in sorted(required_origins) if len(r) > 1],
        'source_precision': score['precision'], 'source_recall': score['recall'],
        'estimated_api_cost_usd': 0.0,
    }


def distribution(samples):
    return {'n': len(samples), 'p50': _percentile(samples, .5), 'p95': _percentile(samples, .95)}


def summarize(selections, timings):
    result = {}
    fields = ['evidence_retention', 'actual_context_tokens', 'raw_context_tokens', 'context_reduction',
              'supporting_passage_claim_coverage', 'independent_evidence_coverage',
              'source_precision', 'source_recall', 'tokenizer_tokens', 'tokenizer_utilization',
              'dependency_cluster_coverage', 'budget_normalized_source_recall']
    for method in sorted({r['method'] for r in selections}):
        cells = [r for r in selections if r['method'] == method]
        runs = [r for r in timings if r['method'] == method]
        value = {'cells': len(cells), 'executions': len(runs)}
        value.update({key: mean(r[key] for r in cells) for key in fields})
        value.update(gold_claim_coverage=None, answer_accuracy=None, accuracy_at_matched_tokens=None,
                     end_to_end_latency=None, estimated_api_cost_usd=0.0)
        for name in ['selection_ms', 'graph_ms', 'packing_ms', 'reconstruction_ms',
                     'mcp_ms', 'verification_inference_ms', 'discovery_ms']:
            samples = [float(r[name]) for r in runs if r.get(name) not in (None, '')]
            value[name] = distribution(samples)
        result[method] = value
    return result
