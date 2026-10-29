"""Small filesystem guards shared by benchmark execution and offline analysis."""
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
TRACE_SHA256 = 'd19860c5b0a22c3bc762e1f72a42ffe6537b71e8de9400ced90f686994f7b4c3'
DEFAULT_TRACE = BASE / 'contracts/execution-v1' / (TRACE_SHA256 + '.jsonl')


def refuse_completed_output(directory):
    directory = Path(directory)
    for name in ('selections.json', 'summary.json', 'validation.json', 'analysis_validation.json',
                 'offline_validation.json', 'manifest.json', 'alternatives.json', 'timings.csv'):
        if (directory / name).exists():
            raise FileExistsError(f'Existing benchmark output must remain immutable: {directory / name}')


def require_new_output(directory, *, protected=()):
    if Path(directory).exists():
        raise FileExistsError(f'Analysis requires a new output directory: {directory}')
    if any(Path(directory).resolve().is_relative_to(Path(source).resolve()) for source in protected):
        raise ValueError(f'Analysis output cannot be inside frozen inputs: {directory}')


def pinned_file(recorded, digest):
    """Resolve original bytes without weakening a recorded hash contract."""
    from ..paths import resolve_artifact
    path = resolve_artifact(recorded)
    for candidate in (path, BASE / 'contracts/execution-v1' / (digest + '.txt'),
                      BASE / 'contracts/publication-v1' / (digest + '.txt')):
        if candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == digest:
            return candidate
    raise ValueError(f'Preserved artifact digest mismatch: {recorded}')


def verify_hashes(entries, *, allow_source_snapshots=False):
    from ..paths import resolve_artifact
    for path, digest in entries.items():
        # Only source contracts may resolve to historical bytes. Dataset/result
        # paths must match the actual input that the analysis will read.
        if allow_source_snapshots and Path(path).suffix == '.py':
            pinned_file(path, digest)
        else:
            current = resolve_artifact(path)
            if not current.is_file() or hashlib.sha256(current.read_bytes()).hexdigest() != digest:
                raise ValueError(f'Protected input digest mismatch: {path}')


def read_trace(path=DEFAULT_TRACE):
    path = Path(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != TRACE_SHA256:
        raise ValueError(f'Frozen trace digest mismatch: {path}')
    return [json.loads(line) for line in path.read_text().splitlines()]


def recovery_analysis_preflight(source, output, trace=DEFAULT_TRACE):
    source, output = Path(source), Path(output)
    require_new_output(output, protected=(source,))
    required = ('selections.json', 'timings.csv', 'manifest.json', 'validation.json',
                'analysis_validation.json', 'protected_inputs.json', 'alternatives.json',
                'positive-only-alternatives.json', 'source_reliability_validation.json',
                'production-change.patch', 'selection-tests-verified.log')
    for name in required:
        if not (source / name).is_file():
            raise FileNotFoundError(source / name)
    validation = json.loads((source / 'analysis_validation.json').read_text())
    for name, digest in validation['analysis_inputs_sha256'].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Analysis input digest mismatch: {name}')
    verify_hashes(json.loads((source / 'protected_inputs.json').read_text()),
                  allow_source_snapshots=True)
    verify_hashes(json.loads((source / 'manifest.json').read_text())['code_sha256'],
                  allow_source_snapshots=True)
    read_trace(trace)
