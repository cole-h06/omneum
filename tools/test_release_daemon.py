"""Offline release contract checks; no daemon build or GitHub access required."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import release_daemon as release


ROOT = Path(__file__).resolve().parents[1]


class ReleaseContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "pyproject.toml"
        self.project.write_text('[project]\nversion = "1.0.3"\n')
        self.staging = self.root / "staged"
        self.output = self.root / "release"
        # Exercise the actual deployment assets, with stand-in native binaries.
        for platform in release.PLATFORMS:
            source = self.staging / f"daemon-{platform}"
            source.mkdir(parents=True)
            names = (
                ["install.sh", "install-foreground.sh", "systemd/omneumd.service", "sysusers.d/omneum.conf"]
                if platform.startswith("linux-")
                else ["install-macos.sh", "launchd/ai.omneum.omneumd.plist"]
            )
            (source / "omneumd").write_bytes(f"daemon for {platform}".encode())
            for name in names:
                target = source / name
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(ROOT / "deploy" / name, target)

    def prepare(self):
        release.prepare(self.staging, self.output, "1.0.3")

    def test_exact_version_and_rejected_tags(self):
        self.assertEqual(release.version_for_tag(self.project, "v1.0.3"), "1.0.3")
        for tag in ("1.0.3", "v1.0.2", "v1.0.30", "v1.0.3-rc1", "v1.0.3\n", "v1.0.3/evil"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release.version_for_tag(self.project, tag)
        self.project.write_text('[project]\nversion = "../bad"\n')
        with self.assertRaises(ValueError):
            release.version_for_tag(self.project, "v../bad")

    def test_contract_contents_permissions_and_checksums(self):
        self.prepare()
        self.assertEqual({p.name for p in self.output.iterdir()}, {
            "omneum-daemon-1.0.3-linux-x86_64.tar.gz",
            "omneum-daemon-1.0.3-macos-aarch64.tar.gz",
            "omneum-daemon-1.0.3-macos-x86_64.tar.gz",
            "SHA256SUMS",
        })
        lines = (self.output / "SHA256SUMS").read_text().splitlines()
        self.assertEqual(len(lines), 3)
        for line in lines:
            digest, name = line.split("  ")
            self.assertEqual(digest, hashlib.sha256((self.output / name).read_bytes()).hexdigest())
        for platform in release.PLATFORMS:
            with tarfile.open(self.output / release.archive_name("1.0.3", platform)) as archive:
                for member in archive.getmembers():
                    if member.isfile():
                        expected = self.staging / f"daemon-{platform}" / member.name
                        self.assertEqual(archive.extractfile(member).read(), expected.read_bytes())
                        self.assertEqual(member.mode, 0o755 if member.name == "omneumd" or member.name.endswith(".sh") else 0o644)
        release.verify(self.output, "1.0.3")

    def test_deterministic_despite_source_metadata_and_output_path(self):
        self.prepare()
        for path in self.staging.rglob("*"):
            os.utime(path, (123456789, 123456789))
            path.chmod(0o755 if path.is_dir() else 0o600)
        second = self.root / "other-output"
        release.prepare(self.staging, second, "1.0.3")
        for path in self.output.iterdir():
            self.assertEqual(path.read_bytes(), (second / path.name).read_bytes())

    def test_missing_platform_or_asset_fails_without_output(self):
        for platform in release.PLATFORMS:
            source = self.staging / f"daemon-{platform}"
            moved = self.root / "saved"
            source.rename(moved)
            with self.subTest(platform=platform), self.assertRaises(ValueError):
                self.prepare()
            self.assertFalse(self.output.exists())
            moved.rename(source)
        for path in list(self.staging.rglob("*")):
            if path.is_file():
                contents = path.read_bytes()
                path.unlink()
                with self.subTest(asset=path), self.assertRaises(ValueError):
                    self.prepare()
                self.assertFalse(self.output.exists())
                path.write_bytes(contents)

    def test_invalid_staged_contents(self):
        binary = self.staging / "daemon-linux-x86_64/omneumd"
        for kind in ("empty", "symlink", "directory"):
            binary.unlink(missing_ok=True)
            if kind == "empty":
                binary.touch()
            elif kind == "symlink":
                binary.symlink_to(self.project)
            else:
                binary.mkdir()
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.prepare()
            self.assertFalse(self.output.exists())

    def test_unexpected_staged_file_is_rejected(self):
        (self.staging / "daemon-linux-x86_64/unexpected").touch()
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_duplicate_or_malformed_manifest_is_rejected(self):
        self.prepare()
        manifest = self.output / "SHA256SUMS"
        original = manifest.read_text()
        for contents in (original + original.splitlines()[0] + "\n", original.replace("  ", " ")):
            manifest.write_text(contents)
            with self.assertRaises(ValueError):
                release.verify(self.output, "1.0.3")

    def test_checksum_failure_is_atomic(self):
        with patch.object(release.hashlib, "file_digest", side_effect=OSError("checksum failure")):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertFalse(self.output.exists())

    def test_verify_rejects_incomplete_extra_and_corrupt_assets(self):
        self.prepare()
        for path in list(self.output.iterdir()):
            original = path.read_bytes()
            path.unlink()
            with self.subTest(missing=path.name), self.assertRaises(ValueError):
                release.verify(self.output, "1.0.3")
            path.write_bytes(original + b"corrupt")
            with self.subTest(corrupt=path.name), self.assertRaises(ValueError):
                release.verify(self.output, "1.0.3")
            path.write_bytes(original)
        (self.output / "extra").touch()
        with self.assertRaises(ValueError):
            release.verify(self.output, "1.0.3")

    def test_existing_output_is_not_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "existing"
        sentinel.write_text("preserve")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(sentinel.read_text(), "preserve")

    def test_cli_prepare_verify_and_tag_rejection(self):
        command = [sys.executable, str(ROOT / "tools/release_daemon.py")]
        options = ["--project", str(self.project), "--staging", str(self.staging), "--output", str(self.output)]
        for operation in ("prepare", "verify"):
            result = subprocess.run(command + [operation, "--tag", "v1.0.3"] + options, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "1.0.3")
        result = subprocess.run(command + ["verify", "--tag", "v1.0.4"] + options, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
