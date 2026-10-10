"""Run-local shared Cohere responses, with read-only reuse of verified history."""

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from benchmarks.context_evaluation.reproducibility import sha256_file
from benchmarks.context_evaluation.paths import input_digest, public_manifest, publication_contract, verify_recorded_artifact
from benchmarks.context_evaluation.semantic_reranker import COHERE_MODEL

from .artifacts import checkpoint
from .loader import application_candidates


def request_key(query, candidates, depth):
    # Order, source identity, text, model and requested depth all matter.
    request = [COHERE_MODEL, query, candidates, depth]
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()


def valid_selection(selection, candidates, depth):
    if not isinstance(selection, dict) or selection.get("model") != COHERE_MODEL:
        return False
    selected = selection.get("selected", [])
    if not isinstance(selected, list) or len(selected) < depth:
        return False
    by_source = {item["source"]: item for item in candidates}
    seen = set()
    previous = math.inf
    for item in selected:
        if not isinstance(item, dict):
            return False
        source = item.get("source")
        score = item.get("reranker_score")
        if (source not in by_source or source in seen
                or item.get("text") != by_source[source]["text"]
                or not isinstance(score, (int, float)) or isinstance(score, bool)
                or not math.isfinite(score) or score > previous):
            return False
        seen.add(source)
        previous = score
    latency = selection.get("latency_seconds")
    return isinstance(latency, (int, float)) and math.isfinite(latency) and latency >= 0


class CohereResponseCache:
    def __init__(self, path=None, *, history=(), discovered=()):
        self.path = Path(path) if path is not None else None
        self.responses = {}
        self.history = tuple(Path(directory) for directory in history)
        self.discovered = {case.case_id: (Path(case_path), case)
                           for case_path, _, case, _ in discovered}
        # Current run wins over other cached responses on resume.
        files = [directory / "cohere_responses.jsonl" for directory in self.history]
        if self.path is not None:
            files.append(self.path)
        for file in files:
            if file.is_file():
                for line in file.read_text().splitlines():
                    try:
                        record = json.loads(line)
                        self.responses[record["request_hash"]] = record["selection"]
                    except (ValueError, KeyError, TypeError):
                        continue

    def _historical(self, query, candidates, depth):
        for case_path, case in self.discovered.values():
            if case.question != query or application_candidates(case) != candidates:
                continue
            for directory in self.history:
                try:
                    manifest_path = (directory / "manifest.json").resolve()
                    if not manifest_path.is_file():
                        projection = public_manifest(directory).resolve()
                        name = str(manifest_path.relative_to(Path(__file__).resolve().parents[3]))
                        entry = publication_contract()["representations"].get(name)
                        if entry is None:
                            continue
                        manifest_path = verify_recorded_artifact(name, entry["original_sha256"])
                        if manifest_path != projection:
                            continue
                    manifest = json.loads(manifest_path.read_text())
                    if input_digest(manifest.get("inputs", {}), case_path) != sha256_file(case_path):
                        continue
                    lines = (directory / "results.jsonl").read_text().splitlines()
                except (OSError, ValueError):
                    continue
                for line in lines:
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    selection = record.get("selection")
                    if (record.get("case_id") == case.case_id and record.get("method") == "cohere"
                            and valid_selection(selection, candidates, depth)):
                        return {**selection, "selected": selection["selected"][:depth]}
        return None

    def select(self, query, candidates, *, depth, selector):
        key = request_key(query, candidates, depth)
        selection = self.responses.get(key)
        if not valid_selection(selection, candidates, depth):
            selection = self._historical(query, candidates, depth)
        hit = selection is not None and valid_selection(selection, candidates, depth)
        if not hit:
            result = selector(query, candidates, top_n=depth)
            if result["failure"] is not None:
                return result
            selection = result["selection"]
            if not valid_selection(selection, candidates, depth):
                raise ValueError("invalid Cohere response for paired comparison")
        self.responses[key] = deepcopy(selection)
        if self.path is not None:
            checkpoint(self.path, [{"request_hash": key, "selection": value}
                                   for key, value in self.responses.items()])
        return {"failure": None, "selection": {
            **deepcopy(selection), "selected": deepcopy(selection["selected"][:depth]),
            "cohere_cache_hit": hit, "cohere_request_hash": key,
            # Retain measured provider latency separately from this run's work.
            "cohere_response_latency_seconds": selection["latency_seconds"],
            "latency_seconds": 0.0 if hit else selection["latency_seconds"],
        }}
