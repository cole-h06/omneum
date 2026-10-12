"""Source distribution privacy and release metadata regression checks."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from release_sdist import verify


class SourceReleaseTests(unittest.TestCase):
    def archive(self, extra=None, cargo_version='1.0.3'):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        path = Path(root.name) / 'omneum-1.0.3.tar.gz'
        files = {
            'PKG-INFO': 'Name: omneum\nVersion: 1.0.3\n',
            'pyproject.toml': '[project]\nversion="1.0.3"\n',
            'Cargo.toml': f'[package]\nversion="{cargo_version}"\n',
            **{name: 'fixture' for name in ('omneum/mcp/LICENSE', 'omneum/mcp/UPSTREAM.json',
                'omneum/mcp/types.py', 'omneum/mcp/server/stdio.py', 'omneum/mcp/client/stdio/__init__.py',
                'Cargo.lock', 'src/lib.rs', 'omneum/cli.py',
                'omneum/installation.py', 'omneum/algorithm_compatibility.json',
                'omneum/schemas/research-event-v1.schema.json', 'LICENSE')},
        }
        files.update(extra or {})
        with tarfile.open(path, 'w:gz') as archive:
            for name, content in files.items():
                info = tarfile.TarInfo('omneum-1.0.3/' + name)
                data = content.encode();info.size=len(data)
                archive.addfile(info, io.BytesIO(data))
        return path

    def test_complete_build_source(self):
        self.assertEqual(verify(self.archive(), '1.0.3'), '1.0.3')

    def test_unrelated_and_secret_files_rejected(self):
        for name in ('tools/provenance_explorer/untracked.py', 'docs/reviews/audit.md',
                     'evaluate.py', 'examples/enterprise.zip', 'private.pem', 'voprf.key', '.env', '../escape'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                verify(self.archive({name: 'fixture'}), '1.0.3')

    def test_rust_version_must_match_python(self):
        with self.assertRaisesRegex(ValueError, 'version mismatch'):
            verify(self.archive(cargo_version='0.1.0'), '1.0.3')


if __name__ == '__main__':
    unittest.main()
