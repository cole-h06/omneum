"""Client-side semantic anchors and bounded context-graph neighborhoods."""

from collections.abc import Mapping, Sequence
from collections import Counter
from functools import lru_cache
import json
from math import fsum, isfinite, log1p, sqrt
from numbers import Integral, Real
import re
import time
from typing import Any

from .canonicalization import canonicalize_source
from .dependency import DependencyEstimatorConfig, InformationGraphError, estimate_dependencies
from .information import Observation


@lru_cache(maxsize=1)
def _embedding_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2',
                               device='cpu', local_files_only=True)


def source_key(source) -> tuple[str, str]:
    return source.kind, canonicalize_source(source.kind, source.identifier)


def bm25_scores(query: str, texts: Mapping[str, str]) -> dict[str, float]:
    """Okapi BM25, k1=1.5 and b=0.75, with positive Robertson IDF.

    Unicode word tokens are casefolded; statistics use this candidate pool.
    No stopwords, semantic model, fitted vocabulary or external service is used.
    """
    terms = Counter(re.findall(r'\w+', query.casefold()))
    documents = {}
    frequency = Counter()
    for identifier, text in texts.items():
        counts = Counter(re.findall(r'\w+', text.casefold()))
        documents[identifier] = counts
        frequency.update(counts.keys())
    average = sum(sum(counts.values()) for counts in documents.values()) / max(1, len(documents))
    result = {}
    for identifier, counts in documents.items():
        score = 0.0
        length_ratio = sum(counts.values()) / average if average else 0.0
        # Saturate term frequency and normalize document length. Robertson IDF
        # depends only on this corpus, never on gold answers or graph support.
        for term, query_count in terms.items():
            count = counts[term]
            if count:
                idf = log1p((len(documents) - frequency[term] + 0.5) / (frequency[term] + 0.5))
                score += query_count * idf * count * 2.5 / (count + 1.5 * (0.25 + 0.75 * length_ratio))
        result[identifier] = score
    return result


def local_chunk_relevance(query, chunks, method, model=None):
    texts = {chunk['chunk_id']: chunk['raw_text'] for chunk in chunks}
    if method == 'bm25':
        return bm25_scores(query, texts)
    if method == 'minilm':
        return rank_claims(query, texts, model)
    raise ValueError('local relevance must be bm25 or minilm')


def normalize_chunk_relevance(scores, chunk_ids, score_type):
    """Explicit normalized weights, or dense ranks for uncalibrated scores.

    Equal uncalibrated values tie and constant batches get one; explicit
    normalized weights preserve their absolute values, including all-zero batches.

    Scores are comparable only within this pool, not across retrievers.
    Every candidate needs an explicit finite score; missing values are errors.
    """
    if score_type not in ('similarity', 'distance', 'rank', 'reranker_score', 'normalized'):
        raise ValueError('unknown relevance score type')
    if not isinstance(scores, Mapping) or set(scores) != set(chunk_ids):
        raise ValueError('chunk relevance must cover every chunk ID exactly')
    raw = {}
    for identifier in chunk_ids:
        value = scores[identifier]
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError('chunk relevance must contain finite numbers')
        value = int(value) if isinstance(value, Integral) else float(value)
        if not isinstance(value, int) and not isfinite(value):
            raise ValueError('chunk relevance must contain finite numbers')
        if score_type == 'rank' and (value < 0 or value != int(value)):
            raise ValueError('rank scores must be nonnegative integers')
        raw[identifier] = value
    if score_type == 'normalized':
        if any(not 0 <= value <= 1 for value in raw.values()):
            raise ValueError('normalized chunk relevance must be in [0, 1]')
        return raw, dict(raw)
    # Rank distinct values rather than subtracting extremes: negative logits
    # and very large finite scores preserve their order without overflow.
    levels = sorted(set(raw.values()), reverse=score_type in ('distance', 'rank'))
    weights = {}
    for index, value in enumerate(levels):
        weights[value] = index / (len(levels) - 1) if len(levels) > 1 else 1.0
    normalized = {identifier: weights[value] for identifier, value in raw.items()}
    return raw, normalized


def discover_chunks(observations, mapping, scores, score_type, policy, count, depth, *,
                    conflict_aware=False):
    from .context_selection import claim_id
    if policy not in ('all', 'top_k', 'expanded'):
        raise ValueError('candidate discovery must be all, top_k or expanded')
    if type(count) is not int or count < 1:
        raise ValueError('candidate count must be a positive integer')
    if type(depth) is not int or depth not in (1, 2):
        raise ValueError('expansion depth must be one or two')
    order = mapping['retrieval_order']
    if scores is None:
        raw, normalized = {}, {}
    else:
        raw, normalized = normalize_chunk_relevance(scores, order, score_type)
    anchors = []
    anchor_claims = set()
    reached = {'chunk_ids': list(order), 'claim_ids': sorted(mapping['claim_chunks']),
               'traversed_edges': 0}
    started = time.perf_counter()
    if normalized and policy != 'all':
        ranked = sorted(order, key=lambda key: -normalized[key])
        boundary = normalized[ranked[min(count, len(ranked)) - 1]]
        # Keep every boundary tie. A constant batch supplies no preference and
        # cannot justify dropping an arbitrary subset of otherwise valid chunks.
        anchors = [key for key in ranked if normalized[key] >= boundary]
        for identifier in anchors:
            anchor_claims.update(mapping['chunk_claims'][identifier])
        if policy == 'expanded':
            # Chunk scores choose entry points only. Claim IDs are needed here
            # solely to traverse the existing chunk/source adjacency.
            reached = expand_claims(observations, mapping, sorted(anchor_claims), depth,
                                    conflict_aware=conflict_aware)
        else:
            reached = {'chunk_ids': [key for key in order if key in anchors],
                       'claim_ids': sorted(anchor_claims), 'traversed_edges': 0}
    eligible = set(reached['chunk_ids'])
    expanded_claims = set(reached['claim_ids'])
    sources = set()
    edges = 0
    for observation in observations:
        if claim_id(observation.claim) in expanded_claims:
            sources.add(source_key(observation.source))
            edges += 1
    return {'raw_relevance_scores': raw, 'normalized_relevance_scores': normalized,
            'score_semantics': score_type, 'candidate_discovery': policy,
            'candidate_count': count, 'anchor_chunk_ids': anchors,
            'anchor_claim_ids': sorted(anchor_claims),
            'expanded_claim_ids': reached['claim_ids'],
            'expanded_chunk_ids': reached['chunk_ids'],
            'expanded_sources': len(sources), 'expanded_claims': len(expanded_claims),
            'expanded_edges': edges,
            'eligible_chunk_ids': reached['chunk_ids'],
            'excluded_chunks': [{'chunk_id': key, 'relevance': raw[key],
                                 'reason': 'outside_expansion' if policy == 'expanded' else 'outside_top_k'}
                                for key in order if key not in eligible],
            'normalization': ('explicit [0, 1] weights' if score_type == 'normalized' else
                              'dense ranks over distinct values; best=1, worst=0, constant=1'),
            'traversed_edges': reached['traversed_edges'],
            'expansion_latency_ms': (time.perf_counter() - started) * 1000}


def rank_claims(query: str, texts: Mapping[str, str], model: Any = None) -> dict[str, float]:
    if model is None:
        model = _embedding_model()
    keys = sorted(texts)
    vectors = model.encode([query, *[texts[k] for k in keys]],
                           normalize_embeddings=True, show_progress_bar=False)
    if len(vectors) != len(keys) + 1:
        raise ValueError('semantic model returned an invalid vector count')
    rows = [tuple(float(x) for x in row) for row in vectors]
    width = len(rows[0])
    norms = []
    for row in rows:
        if not width or len(row) != width or any(not isfinite(x) for x in row):
            raise ValueError('semantic model returned invalid vectors')
        norm = sqrt(fsum(x*x for x in row))
        if norm == 0:
            raise ValueError('semantic model returned a zero vector')
        norms.append(norm)
    # Keep raw cosine scores, including negative values. They choose entry
    # points only and never multiply structural support or propagation weights.
    return {key: fsum(a*b for a, b in zip(rows[0], rows[i], strict=True))/(norms[0]*norms[i])
            for i, key in enumerate(keys, 1)}


def expand_claims(observations: Sequence[Observation], mapping: Mapping,
                  anchors: Sequence[str], depth: int, *,
                  conflict_aware: bool = False) -> dict[str, Any]:
    from .context_selection import claim_id, _query_coverage_key

    if type(depth) is not int or depth not in (1, 2):
        raise ValueError('expansion depth must be one or two')
    claim_sources, source_claims = {}, {}
    for observation in observations:
        claim = claim_id(observation.claim)
        source = source_key(observation.source)
        claim_sources.setdefault(claim, set()).add(source)
        source_claims.setdefault(source, set()).add(claim)
    if not set(anchors) <= claim_sources.keys():
        raise ValueError('unknown anchor claim')
    frontier = set(anchors)
    visited_claims, visited_sources, visited_chunks, evaluated = set(), set(), set(), set()
    traversed = 0
    for _ in range(depth):
        if not frontier:
            break
        reached = set()
        # One hop opens all chunks containing the frontier claims, then includes
        # every co-located claim. Co-occurrence gives eligibility, not implication.
        for claim in sorted(frontier - visited_claims):
            visited_claims.add(claim)
            for chunk in mapping['claim_chunks'][claim]:
                traversed += 1
                if chunk not in visited_chunks:
                    visited_chunks.add(chunk)
                    reached.update(mapping['chunk_claims'][chunk])
        evaluated.update(reached)
        next_claims = set(reached)
        # A source's other assertions become the next hop's entry points. Every
        # opened chunk is kept whole, including low-similarity qualifications.
        for claim in sorted(reached):
            for source in sorted(claim_sources[claim]):
                traversed += 1
                if source not in visited_sources:
                    visited_sources.add(source)
                    next_claims.update(source_claims[source])
        frontier = next_claims - visited_claims
    if conflict_aware:
        # Apply one eligibility closure after bounded traversal. Newly admitted
        # chunks stay whole, but neither their co-located properties nor their
        # sources open further neighborhoods. Structured values keep the existing
        # exact-claim key because their conditions need not be mutually exclusive.
        properties = {claim_id(o.claim): _query_coverage_key(o.claim) for o in observations}
        eligible_properties = {properties[claim] for claim in evaluated}
        competing = {claim for claim, key in properties.items() if key in eligible_properties}
        for claim in sorted(competing - evaluated):
            for chunk in mapping['claim_chunks'][claim]:
                traversed += 1
                visited_chunks.add(chunk)
        for chunk in visited_chunks:
            evaluated.update(mapping['chunk_claims'][chunk])
    sources = {source for claim in evaluated for source in claim_sources[claim]}
    return {'claim_ids': sorted(evaluated), 'source_keys': sorted(sources),
            'chunk_ids': [k for k in mapping['retrieval_order'] if k in visited_chunks],
            'traversed_edges': traversed, 'visited_claims': len(visited_claims)}


def plan_context(observations: Sequence[Observation], chunks: Sequence[Mapping], *,
                 estimator: DependencyEstimatorConfig, user_query: str,
                 anchor_count: int, expansion_depth: int,
                 claim_texts: Mapping[str, str] | None, semantic_model: Any = None,
                 query_anchoring: bool = True, query_weighted: bool = False,
                 claim_relevance: Mapping[str, float] | None = None,
                 relevance_threshold: float | None = None) -> dict[str, Any]:
    from .client import _snapshot_observations
    from .context_selection import claim_id, map_chunks, validate_claim_relevance

    if type(user_query) is not str:
        raise TypeError('user query must be a string')
    if type(anchor_count) is not int or anchor_count < 1:
        raise ValueError('anchor count must be a positive integer')
    if type(query_anchoring) is not bool:
        raise TypeError('query anchoring must be a bool')
    if relevance_threshold is not None:
        if type(relevance_threshold) not in (int, float) or not isfinite(relevance_threshold) or not 0 <= relevance_threshold <= 1:
            raise ValueError('relevance threshold must be finite and in [0, 1]')
    if type(expansion_depth) is not int or expansion_depth not in (1, 2):
        raise ValueError('expansion depth must be one or two')
    values = tuple(observations)
    if any(type(o) is not Observation or o.observation_type != 'assertion' for o in values):
        raise TypeError('observations must contain Observation values')
    values = _snapshot_observations(values)
    claims = {claim_id(o.claim): o.claim for o in values}
    mapping = map_chunks(chunks, claims)
    sources = {}
    for observation in values:
        key = source_key(observation.source)
        previous = sources.get(key)
        if previous is not None and previous.owner_id != observation.source.owner_id:
            raise InformationGraphError('canonical source has conflicting owners')
        sources.setdefault(key, observation.source)
    started = time.perf_counter()
    # Resolve ancestry/citations on the complete input before restricting nodes.
    # Re-estimating only the neighborhood would lose external provenance paths.
    pairs, _ = estimate_dependencies(tuple(sources.values()), values, estimator)
    dependency_ms = (time.perf_counter()-started)*1000
    diagnostics = {'anchor_claim_ids': [], 'relevance_scores': {}, 'fallback_reason': None,
                   'full_sources': len(sources), 'full_claims': len(claims),
                   'full_edges': len(values), 'dependency_context_ms': dependency_ms,
                   'semantic_latency_ms': 0.0, 'expansion_latency_ms': 0.0}
    fallback = 'empty_query' if not user_query.strip() else ('empty_chunks' if not chunks else None)
    if claim_texts is None:
        texts = {key: f'{c.entity} {c.attribute.replace("_", " ")}: '+json.dumps(c.value, ensure_ascii=False)
                 for key, c in claims.items()}
    else:
        if not isinstance(claim_texts, Mapping) or any(k not in claims for k in claim_texts):
            raise ValueError('claim texts must map known claim IDs')
        if any(type(v) is not str for v in claim_texts.values()):
            raise TypeError('claim texts must be strings')
        texts = dict(claim_texts)
        if set(texts) != set(claims) or any(not v.strip() for v in texts.values()):
            fallback = 'missing_claim_text'
    started = time.perf_counter()
    if claim_relevance is not None:
        validate_claim_relevance(claim_relevance, claims)
        diagnostics['relevance_scores'] = dict(claim_relevance)
        fallback = None
    elif fallback is None:
        try:
            scores = rank_claims(user_query, texts, semantic_model)
        except (ImportError, OSError, RuntimeError):
            fallback = 'semantic_model_unavailable'
        else:
            diagnostics['relevance_scores'] = scores
    if query_weighted:
        if fallback:
            raise ValueError(f'query coverage requires relevance: {fallback}')
        # Positive cosine is a selection weight, not a probability. Negative
        # similarity contributes zero; no relevance floor rescues missing claims.
        scores = {}
        for claim, similarity in diagnostics['relevance_scores'].items():
            scores[claim] = min(1.0, max(0.0, similarity))
        diagnostics['relevance_scores'] = scores
    if relevance_threshold is not None and fallback:
        raise ValueError(f'relevance threshold requires semantics: {fallback}')
    if not fallback and query_anchoring and relevance_threshold is None:
        scores = diagnostics['relevance_scores']
        diagnostics['anchor_claim_ids'] = sorted(scores, key=lambda k: (-scores[k], k))[:anchor_count]
    diagnostics['semantic_latency_ms'] = (time.perf_counter()-started)*1000
    started = time.perf_counter()
    chunk_relevance = {}
    if not fallback:
        for chunk, identifiers in mapping['chunk_claims'].items():
            chunk_relevance[chunk] = max(diagnostics['relevance_scores'][claim] for claim in identifiers)
    if relevance_threshold is not None:
        selected_chunks = []
        keys = set()
        # Eligibility uses the strongest claim similarity in the original chunk.
        # Equality is retained; relevance never changes structural support.
        for chunk in chunks:
            if chunk_relevance[chunk['chunk_id']] >= relevance_threshold:
                selected_chunks.append(chunk)
                keys.update(mapping['chunk_claims'][chunk['chunk_id']])
        selected_values = tuple(o for o in values if claim_id(o.claim) in keys)
        supporting_sources = {source_key(o.source) for o in selected_values}
        reached = {'claim_ids': sorted(keys), 'source_keys': sorted(supporting_sources),
                   'chunk_ids': [chunk['chunk_id'] for chunk in selected_chunks], 'traversed_edges': 0}
    elif fallback or not query_anchoring:
        selected_chunks, selected_values = list(chunks), values
        reached = {'claim_ids': sorted(claims), 'source_keys': sorted(sources),
                   'chunk_ids': list(mapping['retrieval_order']), 'traversed_edges': 0}
    else:
        reached = expand_claims(values, mapping, diagnostics['anchor_claim_ids'], expansion_depth)
        keys = set(reached['claim_ids'])
        selected_chunks = [c for c in chunks if c['chunk_id'] in set(reached['chunk_ids'])]
        selected_values = tuple(o for o in values if claim_id(o.claim) in keys)
    diagnostics.update(fallback_reason=fallback, expanded_claim_ids=reached['claim_ids'],
                       expanded_chunk_ids=reached['chunk_ids'], expanded_sources=len(reached['source_keys']),
                       expanded_claims=len(reached['claim_ids']), expanded_edges=len(selected_values),
                       traversed_edges=reached['traversed_edges'],
                       expansion_latency_ms=(time.perf_counter()-started)*1000)
    eligible = set(reached['chunk_ids'])
    diagnostics['chunk_relevance'] = chunk_relevance
    diagnostics['eligible_chunk_ids'] = reached['chunk_ids']
    diagnostics['excluded_chunks'] = [
        {'chunk_id': chunk, 'relevance': chunk_relevance.get(chunk)}
        for chunk in mapping['retrieval_order'] if chunk not in eligible
    ]
    diagnostics['relevance_threshold'] = relevance_threshold
    return {'observations': selected_values, 'chunks': selected_chunks, 'pairs': pairs,
            'full_observations': values, 'mapping': mapping, 'diagnostics': diagnostics}
