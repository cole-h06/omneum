"""Native license artifact corruption must fail the release gate."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile
from native_licenses import ROOT, verify_artifacts


class NativeLicenseTests(unittest.TestCase):
    def artifact(self, *, source=False, tampered=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / ('omneum-1.0.3.tar.gz' if source else 'omneum.whl')
        files = {name: (ROOT / name).read_bytes() for name in
                 ('omneum/NATIVE-LICENSES.txt', 'omneum/RUST-STDLIB-LICENSES.txt')}
        files['LICENSE' if source else 'omneum-1.0.3.dist-info/licenses/LICENSE'] = (ROOT / 'LICENSE').read_bytes()
        if tampered:
            files['omneum/NATIVE-LICENSES.txt'] = b'tampered notice'
        if source:
            with tarfile.open(path, 'w:gz') as archive:
                for name, content in files.items():
                    member = tarfile.TarInfo('omneum-1.0.3/' + name)
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
        else:
            with zipfile.ZipFile(path, 'w') as archive:
                for name, content in files.items():
                    archive.writestr(name, content)
        return path

    def test_wheel_notices_match_verified_source(self):
        verify_artifacts([self.artifact()])

    def test_source_notices_match_verified_source(self):
        verify_artifacts([self.artifact(source=True)])

    def test_literal_wildcard_from_powershell_is_verified(self):
        artifact = self.artifact()
        verify_artifacts([artifact.parent / '*.whl'])

    def test_missing_wildcard_is_rejected(self):
        artifact = self.artifact()
        with self.assertRaisesRegex(ValueError, 'no matching license artifacts'):
            verify_artifacts([artifact.parent / 'missing-*.whl'])

    def test_modified_native_notices_rejected(self):
        for source in (False, True):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'native license mismatch'):
                verify_artifacts([self.artifact(source=source, tampered=True)])
