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


class OfflineOnly:
    def pytest_collection_modifyitems(self, items):
        for item in items:
            path = str(item.path)
            if (path.endswith("prompt_injection/test_prompt_injection.py")
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
    raise SystemExit(pytest.main([str(ROOT / "benchmarks/context_evaluation"),
                                 *sys.argv[1:]], plugins=[OfflineOnly()]))
