"""BEIR SciFact test queries with a label-blind BM25 candidate pool."""

import csv
import io
import json
from time import perf_counter
import zipfile

from omneum.query_context import bm25_scores


def load(path, question_ids, depth=10):
    with zipfile.ZipFile(path) as archive:
        corpus = [json.loads(line) for line in archive.read('scifact/corpus.jsonl').splitlines()]
        queries = {v['_id']: v for v in map(json.loads, archive.read('scifact/queries.jsonl').splitlines())}
        labels = {}
        for row in csv.DictReader(io.StringIO(archive.read('scifact/qrels/test.tsv').decode()), delimiter='\t'):
            if int(row['score']) > 0:
                labels.setdefault(row['query-id'], []).append(row['corpus-id'])
    by_id = {v['_id']: v for v in corpus}
    texts = {v['_id']: v['text'] for v in sorted(corpus, key=lambda v: v['_id'])}
    cases = []
    for identifier in question_ids:
        query = queries[identifier]['text']
        started = perf_counter()
        scores = bm25_scores(query, texts)
        pool = sorted(texts, key=lambda k: (-scores[k], k))[:depth]
        seconds = perf_counter() - started
        chunks = [dict(chunk_id=f'd{k}', document_id=k, title=by_id[k]['title'],
                       raw_text=by_id[k]['text'], source_url=None, source_modified_at=None,
                       source_metadata=by_id[k].get('metadata', {}))
                  for k in pool]
        cases.append(dict(case_id=identifier, dataset='scifact', domain='scientific_claims',
                          question=query, answer=None, chunks=chunks,
                          evaluation_metadata=queries[identifier].get('metadata', {}),
                          relevant_document_ids=sorted(labels[identifier]),
                          retrieval_seconds=seconds))
    return cases


def query_ids(path):
    with zipfile.ZipFile(path) as archive:
        rows = csv.DictReader(io.StringIO(archive.read('scifact/qrels/test.tsv').decode()), delimiter='\t')
        return sorted({r['query-id'] for r in rows if int(r['score']) > 0})
