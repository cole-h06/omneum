"""Qualification helpers must import without optional provider/model SDKs."""
from pathlib import Path
import subprocess
import sys


def test_benchmark_helpers_use_bundled_mcp_without_optional_integrations():
    script = '''
import importlib
import importlib.abc
import sys

optional = {'mcp', 'anthropic', 'openai', 'google', 'cohere', 'numpy',
            'sentence_transformers', 'torch'}

class RejectOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in optional:
            raise AssertionError('unexpected optional import: ' + fullname)

sys.meta_path.insert(0, RejectOptional())
from omneum.mcp import StdioServerParameters
from benchmarks.context_selection import deployment
assert deployment.StdioServerParameters is StdioServerParameters
for module in (
    'benchmarks.context_selection.application_comparison',
    'benchmarks.context_selection.synthetic.prepare_benchmark',
    'benchmarks.context_selection.public_datasets.mapping',
    'benchmarks.context_selection.public_datasets.preprocessing',
):
    importlib.import_module(module)
assert not optional.intersection(sys.modules)
'''
    result = subprocess.run(
        [sys.executable, '-c', script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
