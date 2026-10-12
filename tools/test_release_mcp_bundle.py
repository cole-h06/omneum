"""Artifact corruption must not pass the bundled SDK release boundary."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from check_mcp_bundle import verify


class BundleTests(unittest.TestCase):
    def artifact(self, *, source=False, corrupt=False, missing=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / ("omneum-1.0.3.tar.gz" if source else "omneum.whl")
        payload = {"LICENSE": b"upstream MIT license", "types.py": b"original protocol source"}
        manifest = {"revision": "pinned-upstream", "files":
                    {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}}
        if corrupt:
            payload["types.py"] = b"modified protocol source"
        if missing:
            del payload["LICENSE"]
        payload["UPSTREAM.json"] = json.dumps(manifest).encode()
        if source:
            with tarfile.open(path, "w:gz") as archive:
                for name, data in payload.items():
                    member = tarfile.TarInfo("omneum-1.0.3/omneum/mcp/" + name)
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
        else:
            with zipfile.ZipFile(path, "w") as archive:
                for name, data in payload.items():
                    archive.writestr("omneum/mcp/" + name, data)
        return path

    def test_wheel_preserves_source_and_license(self):
        self.assertEqual(verify(self.artifact()), "pinned-upstream")

    def test_sdist_preserves_source_and_license(self):
        self.assertEqual(verify(self.artifact(source=True)), "pinned-upstream")

    def test_modified_sdk_rejected(self):
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify(self.artifact(corrupt=True))

    def test_missing_license_rejected(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            verify(self.artifact(missing=True))


if __name__ == "__main__":
    unittest.main()
