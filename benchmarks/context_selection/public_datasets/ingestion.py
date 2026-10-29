"""Validate pinned downloads and freeze deterministic public candidate pools."""

import argparse
import hashlib
import json
from pathlib import Path

from benchmarks.context_selection.synthetic.artifacts import write_json, write_jsonl
from benchmarks.context_selection.reproducibility import sha256_file
from . import hotpotqa, scifact


ROOT = Path(__file__).resolve().parent


def sample_ids(identifiers, count, seed=42):
    identifiers = list(identifiers)
    if len(identifiers) != len(set(identifiers)) or not 0 < count <= len(identifiers):
        raise ValueError('sampling requires unique IDs and a valid positive count')
    return sorted(identifiers, key=lambda k: (hashlib.sha256(f'{seed}:{k}'.encode()).hexdigest(), k))[:count]


def prepare(cache, output, *, hotpot_count=100, scifact_count=50, seed=42):
    references = json.loads((ROOT / 'dataset_references.json').read_text())
    files = {}
    for name, reference in references.items():
        path = cache / reference['filename']
        if sha256_file(path) != reference['sha256']:
            raise ValueError(f'dataset checksum mismatch: {path}')
        files[name] = path
    hotpot = hotpotqa.load(files['hotpotqa'])
    chosen = sample_ids((v['case_id'] for v in hotpot), hotpot_count, seed)
    by_id = {v['case_id']: v for v in hotpot}
    cases = [by_id[k] for k in chosen]
    cases += scifact.load(files['scifact'], sample_ids(scifact.query_ids(files['scifact']), scifact_count, seed))
    retrieval_seconds = {f"{c['dataset']}:{c['case_id']}": c.pop('retrieval_seconds') for c in cases}
    output.mkdir(parents=True, exist_ok=False)
    write_jsonl(output / 'cases.jsonl', cases)
    # Timing measurements are excluded from the immutable pool fingerprint.
    inventory = [dict(dataset=c['dataset'], case_id=c['case_id'],
                      documents=[dict(chunk_id=v['chunk_id'], document_id=v['document_id'],
                                      text_sha256=hashlib.sha256(v['raw_text'].encode()).hexdigest())
                                 for v in c['chunks']]) for c in cases]
    write_json(output / 'manifest.json', dict(
        schema_version=1, track='authentic', datasets=references, seed=seed,
        sampling='ascending SHA256(UTF-8(seed + colon + question ID)), tie by ID',
        candidate_pool=dict(hotpotqa='official distractor paragraphs in release order',
                            scifact='top 10 full-corpus production BM25 on abstract text; ties by document ID; no qrel injection'),
        missing_provenance=['source URL', 'source revision', 'publication and modification timestamps',
                            'upstream sources', 'citations', 'ownership', 'dependency relationships'],
        inventory=inventory, retrieval_seconds=retrieval_seconds,
        cases_sha256=sha256_file(output / 'cases.jsonl')))
    return cases


def read_prepared(directory):
    metadata = json.loads((directory / 'manifest.json').read_text())
    if sha256_file(directory / 'cases.jsonl') != metadata['cases_sha256']:
        raise ValueError('prepared cases checksum mismatch')
    cases = [json.loads(line) for line in (directory / 'cases.jsonl').read_text().splitlines()]
    identities = [(c['dataset'], c['case_id']) for c in cases]
    if len(set(identities)) != len(identities):
        raise ValueError('duplicate prepared question')
    for case in cases:
        ids = [v['chunk_id'] for v in case['chunks']]
        if len(set(ids)) != len(ids) or not ids:
            raise ValueError('invalid candidate pool')
        if case['dataset'] == 'scifact' and case['answer'] is not None:
            raise ValueError('BEIR retrieval queries cannot have invented answer labels')
        case['retrieval_seconds'] = metadata['retrieval_seconds'][f"{case['dataset']}:{case['case_id']}"]
    return cases, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hotpot-count', type=int, default=100)
    parser.add_argument('--scifact-count', type=int, default=50)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    prepare(args.cache, args.output, hotpot_count=args.hotpot_count,
            scifact_count=args.scifact_count, seed=args.seed)


if __name__ == '__main__':
    main()
