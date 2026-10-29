"""Keep the candidate's package, native crate, locks and container pins aligned."""
import ast
import json
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_candidate_versions_agree():
    def read(name):
        return tomllib.loads((ROOT / name).read_text())
    version = read('pyproject.toml')['project']['version']
    assert read('Cargo.toml')['package']['version'] == version
    assert next(p['version'] for p in read('Cargo.lock')['package'] if p['name'] == 'omneum_oprf') == version
    assert next(p['version'] for p in read('uv.lock')['package'] if p['name'] == 'omneum') == version
    initializer = ast.parse((ROOT / 'omneum/__init__.py').read_text())
    assert next(ast.literal_eval(node.value) for node in initializer.body
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__version__'
                                                        for t in node.targets)) == version
    steps = json.loads((ROOT / 'deploy/glama/build-steps.json').read_text())
    assert any(f'pip install --no-cache-dir omneum=={version}' in step for step in steps)
    assert any(f"version('omneum') == '{version}'" in step for step in steps)
