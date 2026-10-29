"""Run benchmark tests offline, skipping live evaluations and uncached models.

Provider serialization tests still run through their mocked transports. Socket
connections over TCP/IP are blocked as a second guard against paid requests.
Local Unix-socket daemon tests run and may require host permissions.
"""
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  PYTHONDONTWRITEBYTECODE="1")

import pytest


# Explicit file allowlist: no public-dataset pipeline or experimental model runs.
UNIT_FILES = (
    'benchmarks/context_selection/test_publication_docs.py',
    'benchmarks/context_selection/test_provenance.py',
    *(f'benchmarks/context_selection/synthetic/{name}.py' for name in (
        'test_execution_safety', 'test_dataset', 'test_loader', 'test_tier1',
        'test_tier1_competitors', 'test_scoring', 'test_scoring_polarity',
        'test_aggregate', 'test_artifacts', 'test_latency_analysis',
        'test_verified_gemini_recovery', 'test_dashboard_summary')),
    'tests/test_context_packing.py',
    'tests/test_context_density.py',
    'tests/test_context_discovery_recovery.py',
)


class OfflineOnly:
    def __init__(self, unit_only=False):
        self.unit_only = unit_only

    def pytest_collection_modifyitems(self, items):
        for item in items:
            path = str(item.path)
            if (self.unit_only and item.originalname == 'test_sdk_expanded_recovers_but_explicit_top_k_remains_a_hard_restriction'
                    or path.endswith("prompt_injection/test_prompt_injection.py")
                    or path.endswith("test_semantic_reranker.py")
                    or item.originalname in {"test_vector_selection", "test_bge_selection",
                                             "test_smoke_real_llm_envelope_and_failure_continuation"}):
                item.add_marker(pytest.mark.skip(reason="Live evaluation or local model integration; offline benchmark verification"))

    @pytest.fixture(autouse=True)
    def block_provider_network(self, monkeypatch):
        connect = socket.socket.connect
        connect_ex = socket.socket.connect_ex

        def guarded(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                raise AssertionError("Provider network disabled during offline tests")
            return connect(sock, address)

        def guarded_ex(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                raise AssertionError("Provider network disabled during offline tests")
            return connect_ex(sock, address)

        monkeypatch.setattr(socket.socket, "connect", guarded)
        monkeypatch.setattr(socket.socket, "connect_ex", guarded_ex)


if __name__ == "__main__":
    arguments = sys.argv[1:]
    unit_only = '--unit-only' in arguments
    if unit_only:
        arguments.remove('--unit-only')
    targets = [str(ROOT / p) for p in UNIT_FILES] if unit_only else [str(ROOT / 'benchmarks/context_selection')]
    # Bypass autouse daemon/persistence fixtures only for this explicit pure suite.
    options = ['--noconftest', '-p', 'no:cacheprovider'] if unit_only else []
    raise SystemExit(pytest.main([*targets, *options, *arguments],
                                plugins=[OfflineOnly(unit_only)]))
