"""Regression tests for discovery contracts and fail-closed publication checks."""
import copy
import hashlib
import io
import json
import re
from pathlib import Path
import shutil
import os
import subprocess
import tarfile
import tempfile
import unittest
import zipfile

import registry_readiness as registry
from check_registry_environment import check_environment


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for path in ('pyproject.toml', 'Cargo.toml', 'README.md', 'server.json', 'glama.json',
                     'omneum/__init__.py', 'omneum/cli.py', 'omneum/proxy.py', 'omneum/contributor.py'):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(registry.ROOT / path, target)
        self.version = registry.check_source(self.root)

    def metadata(self, marker=registry.MARKER):
        return (f'Name: omneum\nVersion: {self.version}\nDescription-Content-Type: text/markdown\n'
                f'Project-URL: Repository, {registry.REPOSITORY}\n\n<!-- {marker} -->\n')

    def artifact(self, kind):
        buffer = io.BytesIO()
        if kind == 'bdist_wheel':
            with zipfile.ZipFile(buffer, 'w') as archive:
                prefix = f'omneum-{self.version}.dist-info/'
                archive.writestr(prefix + 'METADATA', self.metadata())
                archive.writestr(prefix + 'entry_points.txt', '[console_scripts]\n' + ''.join(
                    f'{name} = {target}\n' for name, target in registry.ENTRY_POINTS.items()))
            name = f'omneum-{self.version}-py3-none-any.whl'
        else:
            with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
                for name, text in [('PKG-INFO', self.metadata()), ('README.md', self.metadata())]:
                    data = text.encode()
                    member = tarfile.TarInfo(f'omneum-{self.version}/{name}')
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
            name = f'omneum-{self.version}.tar.gz'
        return name, buffer.getvalue()

    def release(self):
        data = {}
        files = []
        for kind in ('bdist_wheel', 'sdist'):
            name, body = self.artifact(kind)
            url = f'https://files.pythonhosted.org/packages/{name}'
            data[url] = body
            files.append(dict(filename=name, url=url, packagetype=kind, yanked=False,
                              digests={'sha256': hashlib.sha256(body).hexdigest()}))
        return dict(info=dict(name='omneum', version=self.version, description=self.metadata(),
                              project_urls={'Repository': registry.REPOSITORY}), urls=files), data.__getitem__

    def test_source(self):
        self.assertEqual(self.version, registry.check_source())

    def test_manifest_mutations_fail(self):
        original = json.loads((self.root / 'server.json').read_text())
        mutations = [('name', 'io.github.cole-h06/omneum'), ('version', '1.0.2'),
                     ('repository', {'source': 'github', 'url': 'https://github.com/wrong/repo'}),
                     ('websiteUrl', 'https://example.com')]
        for field, value in mutations:
            with self.subTest(field=field):
                manifest = copy.deepcopy(original)
                manifest[field] = value
                (self.root / 'server.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    registry.check_source(self.root)

    def test_package_mutations_fail(self):
        original = json.loads((self.root / 'server.json').read_text())
        for field, value in [('identifier', 'omneum-server'), ('version', 'latest'),
                             ('registryBaseUrl', 'https://example.com'), ('runtimeArguments', [])]:
            with self.subTest(field=field):
                manifest = copy.deepcopy(original)
                manifest['packages'][0][field] = value
                (self.root / 'server.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    registry.check_source(self.root)

    def test_readme_marker_required(self):
        (self.root / 'README.md').write_text('No marker')
        with self.assertRaisesRegex(ValueError, 'ownership'):
            registry.check_source(self.root)

    def test_marker_boundary(self):
        registry.ownership(f'<!-- {registry.MARKER} -->')
        registry.ownership(registry.MARKER + '\n')
        with self.assertRaises(ValueError):
            registry.ownership(registry.MARKER + '.unrelated')

    def test_entry_point_source_required(self):
        (self.root / 'omneum/proxy.py').write_text('')
        with self.assertRaisesRegex(ValueError, 'entry point'):
            registry.check_source(self.root)

    def test_built_artifacts(self):
        for kind in ('bdist_wheel', 'sdist'):
            name, data = self.artifact(kind)
            registry.check_artifact(data, name, self.version)

    def test_built_metadata_marker_required(self):
        with self.assertRaisesRegex(ValueError, 'ownership'):
            registry.check_metadata(self.metadata('wrong-marker'), self.version)

    def test_public_release(self):
        document, downloader = self.release()
        registry.check_pypi(document, self.version, downloader)

    def test_public_release_failures(self):
        for change in ('version', 'marker', 'repository', 'yanked', 'missing-sdist', 'url', 'hash'):
            with self.subTest(change=change):
                doc, downloader = self.release()
                if change == 'version': doc['info']['version'] = '1.0.2'
                elif change == 'marker': doc['info']['description'] = ''
                elif change == 'repository': doc['info']['project_urls']['Repository'] = 'https://example.com'
                elif change == 'yanked': doc['urls'][0]['yanked'] = True
                elif change == 'missing-sdist': doc['urls'].pop()
                elif change == 'url': doc['urls'][0]['url'] = 'http://example.com/file.whl'
                elif change == 'hash': doc['urls'][0]['digests']['sha256'] = '0' * 64
                with self.assertRaises(ValueError):
                    registry.check_pypi(doc, self.version, downloader)

    def test_environment_requires_independent_review(self):
        valid = {'name': 'mcp-registry', 'protection_rules': [
            {'type': 'required_reviewers', 'reviewers': [{'type': 'User'}], 'prevent_self_review': True}]}
        check_environment(valid)
        for invalid in ({'name': 'mcp-registry'}, {'name': 'wrong'},
                        {'name': 'mcp-registry', 'protection_rules': [{'type': 'required_reviewers', 'reviewers': []}]},
                        {'name': 'mcp-registry', 'protection_rules': [
                            {'type': 'required_reviewers', 'reviewers': [{'type': 'User'}], 'prevent_self_review': False}]}):
            with self.assertRaises(ValueError):
                check_environment(invalid)

    @unittest.skipUnless(shutil.which('bash') and shutil.which('openssl'), 'requires bash and OpenSSL')
    def test_auth_material_generation(self):
        openssl = '/opt/homebrew/opt/openssl@3/bin/openssl' if Path('/opt/homebrew/opt/openssl@3/bin/openssl').exists() else shutil.which('openssl')
        output = self.root / 'private-proof'
        result = subprocess.run(['bash', str(registry.ROOT / 'tools/prepare_registry_auth.sh'), str(output)],
                                env={**os.environ, 'OPENSSL': openssl}, capture_output=True, text=True, check=True)
        proof = (output / 'mcp-registry-auth').read_text().strip()
        self.assertTrue(proof.startswith('v=MCPv1; k=ed25519; p='))
        self.assertIn(f'omneum.ai. IN TXT "{proof}"', result.stdout)
        seed = (output / 'private-key.hex').read_text().strip()
        self.assertRegex(seed, r'^[0-9a-f]{64}$')
        self.assertNotIn(seed, result.stdout + result.stderr)
        self.assertEqual((output / 'key.pem').stat().st_mode & 0o777, 0o600)
        refused = subprocess.run(['bash', str(registry.ROOT / 'tools/prepare_registry_auth.sh'), str(output)], capture_output=True)
        self.assertNotEqual(refused.returncode, 0)

    @unittest.skipUnless(shutil.which('git') and shutil.which('bash'), 'requires git and bash')
    def test_auth_rejects_other_worktrees(self):
        sibling = self.root / 'sibling-repo'
        subprocess.run(['git', 'init', '-q', str(sibling)], check=True)
        output = sibling / 'private-proof'
        refused = subprocess.run(['bash', str(registry.ROOT / 'tools/prepare_registry_auth.sh'), str(output)], capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertFalse(output.exists())
        self.assertIn('outside every Git worktree', refused.stderr)

    def test_built_wheel_rejects_wrong_entry_point(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            prefix = f'omneum-{self.version}.dist-info/'
            archive.writestr(prefix + 'METADATA', self.metadata())
            archive.writestr(prefix + 'entry_points.txt', '[console_scripts]\nomneum-server = wrong:main\n')
        with self.assertRaisesRegex(ValueError, 'entry points'):
            registry.check_artifact(buffer.getvalue(), 'fixture.whl', self.version)

    def test_source_version_mismatch(self):
        path = self.root / 'Cargo.toml'
        path.write_text(path.read_text().replace(f'version = "{self.version}"', 'version = "0.0.0"', 1))
        with self.assertRaisesRegex(ValueError, 'version mismatch'):
            registry.check_source(self.root)

    def test_all_registry_workflows_are_manual_only(self):
        for name in ('registry-publish.yml', 'registry-checks.yml'):
            workflow = (registry.ROOT / '.github/workflows' / name).read_text()
            event_block = re.search(r'^on:\n(.*?)(?=^[^ \n])', workflow, re.M | re.S).group(1)
            events = re.findall(r'^  ([a-z_]+):', event_block, re.M)
            self.assertEqual(events, ['workflow_dispatch'], name)
            self.assertNotIn('secrets.', workflow if name == 'registry-checks.yml' else '')
            if name == 'registry-checks.yml':
                self.assertNotRegex(workflow, r'mcp-publisher.*(?:login|publish) ')
                self.assertNotIn('upload-artifact', workflow)

    def test_workflow_gates(self):
        workflow = (registry.ROOT / '.github/workflows/registry-publish.yml').read_text()
        self.assertIn('workflow_dispatch:', workflow)
        self.assertIn('default: false', workflow)
        self.assertIn('inputs.publish == true', workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn('environment: mcp-registry', workflow)
        self.assertEqual(workflow.count('python tools/check_registry_environment.py'), 2)
        self.assertIn('needs: preflight', workflow)
        self.assertEqual(workflow.count('--pypi'), 2)
        self.assertNotIn('id-token: write', workflow)
        self.assertNotIn('workflow_run:', workflow)
        self.assertNotIn('\n  push:', workflow)
        self.assertNotIn('\n  release:', workflow)
        self.assertNotIn('\n  pull_request:', workflow)
        self.assertEqual(workflow.count('persist-credentials: false'), 2)
        self.assertEqual(workflow.count('ref: ${{ github.sha }}'), 2)
        self.assertEqual(workflow.count("github.event_name == 'workflow_dispatch'"), 2)
        self.assertIn('set +x', workflow)
        self.assertNotIn('upload-artifact', workflow)
        self.assertNotIn('set -x', workflow)


if __name__ == '__main__':
    unittest.main()
