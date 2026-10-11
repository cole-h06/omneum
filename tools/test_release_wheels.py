"""Offline checks for the complete wheel/daemon release contract."""

from pathlib import Path
import subprocess
import csv
import io
import hashlib
import base64
import json
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import zipfile

import release_daemon
import release_wheels as release
from test_release_daemon import runtime_fixture


TAGS = {
    "linux-x86_64": "manylinux_2_17_x86_64.manylinux2014_x86_64",
    "macos-aarch64": "macosx_11_0_arm64",
    "macos-x86_64": "macosx_10_12_x86_64",
    "windows-x64": "win_amd64",
}


class WheelReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.wheels = self.root / "wheels"
        self.wheels.mkdir()
        self.project = self.root / "pyproject.toml"
        self.project.write_text('[project]\nversion = "1.0.3"\n')
        for python in release.PYTHONS:
            for platform in release.PLATFORMS:
                self.wheel(python, platform)
        staging = self.root / "staged"
        self.assets = self.root / "assets"
        for platform in release_daemon.PLATFORMS:
            for name in release_daemon.layout(platform):
                path = staging / f"daemon-{platform}" / name
                if name in {"systemd", "sysusers.d", "launchd"}:
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(runtime_fixture() if name == "runtime.tar.gz" else b"protected-voprf-v1 fixture")
        release_daemon.prepare(staging, self.assets, "1.0.3")

    def wheel(self, python="cp311", platform="linux-x86_64", version="1.0.3",
              metadata_version=None, metadata_tags=None, entries=None, omit=None):
        tags = TAGS[platform]
        path = self.wheels / f"omneum-{version}-{python}-{python}-{tags}.whl"
        info = f"omneum-{version}.dist-info"
        members = {
            f"{info}/METADATA": f"Metadata-Version: 2.1\nName: omneum\nVersion: {metadata_version or version}\n",
            f"{info}/WHEEL": "Wheel-Version: 1.0\n" + (metadata_tags if metadata_tags is not None else
                "".join(f"Tag: {python}-{python}-{tag}\n" for tag in tags.split("."))),
            f"{info}/entry_points.txt": entries if entries is not None else
                "[console_scripts]\nomneum = omneum.cli:app\nomneum-server = omneum.proxy:main\n"
                "omneum-contributor = omneum.contributor:main\n",
            **{f"omneum/{resource}": "{}" for resource in release.RESOURCES},
        }
        with zipfile.ZipFile(path, "w") as wheel:
            for name, content in members.items():
                if name != omit:
                    wheel.writestr(name, content)
        return path

    def verify(self, tag="v1.0.3"):
        return release.verify(self.wheels, self.assets, self.project, tag)

    def test_complete_matrix_including_compressed_linux_tags(self):
        self.assertEqual(self.verify(), "1.0.3")

    def test_entry_points_match_project_contract(self):
        project = Path(__file__).resolve().parents[1] / "pyproject.toml"
        with project.open("rb") as source:
            self.assertEqual(release.ENTRY_POINTS, tomllib.load(source)["project"]["scripts"])

    def test_prepare_flattens_artifacts_and_preserves_only_wheel_bytes(self):
        expected = {path.name: path.read_bytes() for path in self.wheels.glob("*.whl")}
        for path in list(self.wheels.glob("*.whl")):
            artifact = self.wheels / path.stem
            artifact.mkdir()
            path.rename(artifact / path.name)
        (self.wheels / "unrelated.tar.gz").write_bytes(b"not a release distribution")
        output = self.root / "pypi-dist"
        self.assertEqual(release.prepare(self.wheels, self.assets, self.project, "v1.0.3", output), "1.0.3")
        self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, expected)
        self.assertEqual(release.verify(output, self.assets, self.project, "v1.0.3"), "1.0.3")

    def test_prepare_rejects_invalid_release_before_staging(self):
        output = self.root / "pypi-dist"
        next(self.wheels.glob("*.whl")).unlink()
        with self.assertRaisesRegex(ValueError, "missing wheel"):
            release.prepare(self.wheels, self.assets, self.project, "v1.0.3", output)
        self.assertFalse(output.exists())

    def test_prepare_does_not_overwrite_existing_output(self):
        output = self.root / "pypi-dist"
        output.mkdir()
        sentinel = output / "existing.whl"
        sentinel.write_bytes(b"preserve")
        with self.assertRaisesRegex(ValueError, "must not already exist"):
            release.prepare(self.wheels, self.assets, self.project, "v1.0.3", output)
        self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_prepare_copy_failure_leaves_no_publishable_output(self):
        output = self.root / "pypi-dist"
        with patch.object(release.shutil, "copyfile", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                release.prepare(self.wheels, self.assets, self.project, "v1.0.3", output)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob(".wheel-release-*")), [])

    def test_every_matrix_target_is_required(self):
        for path in self.wheels.glob("*.whl"):
            data = path.read_bytes()
            path.unlink()
            with self.subTest(wheel=path.name), self.assertRaisesRegex(ValueError, "missing wheel"):
                self.verify()
            path.write_bytes(data)

    def test_duplicate_target(self):
        path = self.wheel()
        duplicate = self.wheels / "duplicate"
        duplicate.mkdir()
        (duplicate / path.name).write_bytes(path.read_bytes())
        with self.assertRaisesRegex(ValueError, "duplicate wheel target"):
            self.verify()

    def test_wrong_filename_version(self):
        self.wheel(version="1.0.4")
        with self.assertRaisesRegex(ValueError, "name/version"):
            self.verify()

    def test_wrong_metadata_version(self):
        self.wheel(metadata_version="1.0.4")
        with self.assertRaisesRegex(ValueError, "metadata name/version"):
            self.verify()

    def test_wrong_metadata_tags(self):
        self.wheel(metadata_tags="Tag: cp312-cp312-win_amd64\n")
        with self.assertRaisesRegex(ValueError, "metadata tags"):
            self.verify()

    def test_wrong_entry_points(self):
        self.wheel(entries="[console_scripts]\nomneum = omneum.cli:app\n")
        with self.assertRaisesRegex(ValueError, "entry points"):
            self.verify()

    def test_stale_or_incorrect_contributor_entry_point_is_rejected(self):
        base = "[console_scripts]\nomneum = omneum.cli:app\nomneum-server = omneum.proxy:main\n"
        for entries in (base, base + "omneum-contributor = omneum.proxy:main\n",
                        base + "omneum-contributor = omneum.contributor:main\nextra = omneum.cli:app\n"):
            with self.subTest(entries=entries):
                self.wheel(entries=entries)
                with self.assertRaisesRegex(ValueError, "entry points"):
                    self.verify()

    def test_missing_resource(self):
        self.wheel(omit="omneum/schemas/research-event-v1.schema.json")
        with self.assertRaises(KeyError):
            self.verify()

    def test_unsupported_python_abi_and_platform(self):
        path = self.wheel()
        for replacement in ("cp315-cp315-manylinux_2_17_x86_64", "cp311-abi3-manylinux_2_17_x86_64",
                            "cp311-cp311-linux_x86_64", "cp311-cp311-manylinux_2_17_aarch64"):
            other = self.wheels / f"omneum-1.0.3-{replacement}.whl"
            other.write_bytes(path.read_bytes())
            with self.subTest(tag=replacement), self.assertRaises(ValueError):
                self.verify()
            other.unlink()

    def test_exact_project_tag(self):
        with self.assertRaisesRegex(ValueError, "release tag"):
            self.verify("v1.0.4")

    def test_missing_and_corrupt_daemon_assets(self):
        for path in self.assets.iterdir():
            data = path.read_bytes()
            path.unlink()
            with self.subTest(missing=path.name), self.assertRaises(ValueError):
                self.verify()
            path.write_bytes(data + b"corrupt")
            with self.subTest(corrupt=path.name), self.assertRaises(ValueError):
                self.verify()
            path.write_bytes(data)

    def test_wrong_daemon_version(self):
        path = self.assets / release_daemon.archive_name("1.0.3", "macos-aarch64")
        path.rename(path.with_name(release_daemon.archive_name("1.0.4", "macos-aarch64")))
        with self.assertRaises(ValueError):
            self.verify()

    def test_cli_verifies_complete_release(self):
        result = subprocess.run([
            sys.executable, str(Path(release.__file__)), "verify", "--tag", "v1.0.3",
            "--project", str(self.project), "--wheels", str(self.wheels),
            "--daemon-assets", str(self.assets),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Wheel verify passed: 1.0.3", result.stdout)

    def test_cli_prepares_publishable_wheels(self):
        output = self.root / "pypi-dist"
        result = subprocess.run([
            sys.executable, str(Path(release.__file__)), "prepare", "--tag", "v1.0.3",
            "--project", str(self.project), "--wheels", str(self.wheels),
            "--daemon-assets", str(self.assets), "--output", str(output),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list(output.glob("*.whl"))), 16)

    def test_sanitize_updates_sbom_references_and_record(self):
        path = self.wheel()
        info = 'omneum-1.0.3.dist-info'
        with zipfile.ZipFile(path, 'a') as archive:
            archive.writestr(f'{info}/sboms/cargo.json', json.dumps({'ref': 'path+file:///Users/developer/checkout#omneum_oprf@1.0.3'}))
            archive.writestr(f'{info}/RECORD', '')
        directory = self.wheels / "single"
        directory.mkdir()
        path = path.rename(directory / path.name)
        release.sanitize(directory)
        with zipfile.ZipFile(path) as archive:
            data = archive.read(f'{info}/sboms/cargo.json')
            self.assertEqual(json.loads(data), {'ref': 'pkg:cargo/omneum_oprf@1.0.3'})
            rows = list(csv.reader(io.StringIO(archive.read(f'{info}/RECORD').decode())))
            for name, digest, size in rows:
                if name.endswith('/RECORD'):
                    self.assertEqual((digest, size), ('', ''))
                    continue
                content = archive.read(name)
                expected = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b'=').decode()
                self.assertEqual(digest, expected)
                self.assertEqual(int(size), len(content))

    def test_sanitize_refuses_native_developer_paths(self):
        path = self.wheel()
        with zipfile.ZipFile(path, 'a') as archive:
            archive.writestr('omneum_oprf/native.so', b'binary /Users/developer/.cargo/source')
            archive.writestr('omneum-1.0.3.dist-info/RECORD', '')
        directory = self.wheels / 'single'
        directory.mkdir()
        path.rename(directory / path.name)
        with self.assertRaisesRegex(ValueError, 'unremapped developer path'):
            release.sanitize(directory)

    def test_sanitize_refreshes_readme_without_changing_dependency_headers(self):
        directory = self.root / 'description-wheel'
        directory.mkdir()
        path = directory / 'omneum-1.0.3-cp311-cp311-macosx_11_0_arm64.whl'
        info = 'omneum-1.0.3.dist-info'
        headers = b'Metadata-Version: 2.4\nName: omneum\nVersion: 1.0.3\nRequires-Dist: cryptography>=50.0.1'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr(f'{info}/METADATA', headers + b'\n\nOld description\n')
            archive.writestr(f'{info}/RECORD', '')
        self.project.write_text('[project]\nversion = "1.0.3"\nreadme = "README.md"\n')
        (self.root / 'README.md').write_text('Current release description\n')
        release.sanitize(directory, self.project)
        with zipfile.ZipFile(path) as archive:
            metadata = archive.read(f'{info}/METADATA')
            self.assertEqual(metadata, headers + b'\n\nCurrent release description\n')
            row = next(csv.reader(io.StringIO(archive.read(f'{info}/RECORD').decode())))
            expected = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(metadata).digest()).rstrip(b'=').decode()
            self.assertEqual(row, [f'{info}/METADATA', expected, str(len(metadata))])

    def test_smoke_refuses_ambiguous_wheel_selection(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            release.smoke(self.wheels, self.project)


if __name__ == "__main__":
    unittest.main()
