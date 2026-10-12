"""Connector packaging and failure-boundary tests; no live service or network."""
import json
import os
import base64
import shlex
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest
import zipfile

import build_discovery_bundle as bundle
from discovery_client_links import links


class DiscoveryTests(unittest.TestCase):
    def test_version_and_platforms(self):
        manifest = json.loads((bundle.ROOT / bundle.FILES['manifest.json']).read_text())
        version = tomllib.loads((bundle.ROOT / 'pyproject.toml').read_text())['project']['version']
        self.assertEqual(manifest['version'], version)
        self.assertEqual(manifest['manifest_version'], '0.3')
        self.assertEqual(manifest['compatibility']['platforms'], ['darwin', 'linux'])
        self.assertTrue(manifest['user_config']['server_path']['required'])
        self.assertTrue(manifest['tools_generated'])

    def test_reproducible_allowlisted_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            a = bundle.build(Path(temp) / 'a')
            b = bundle.build(Path(temp) / 'b')
            self.assertEqual(a.read_bytes(), b.read_bytes())
            with zipfile.ZipFile(a) as archive:
                self.assertEqual(set(archive.namelist()), set(bundle.FILES))
                for entry in archive.infolist():
                    self.assertEqual(entry.external_attr >> 16, 0o100644)
            with self.assertRaises(FileExistsError):
                bundle.build(Path(temp) / 'a')

    def test_listing_installation_contract(self):
        listing = json.loads((bundle.ROOT / 'docs/discovery/listing.json').read_text())
        self.assertEqual(listing['official_identity'], 'ai.omneum/omneum')
        self.assertEqual(listing['command'], 'omneum-server')
        self.assertEqual(listing['setup'], ['python -m pip install omneum', 'omneum install'])
        self.assertFalse(listing['one_click_installation'])
        self.assertFalse(listing['windows_local_server'])
        self.assertTrue(listing['administrator_installation'])
        self.assertEqual(listing['daemon_release_platforms'], ['macos-aarch64', 'macos-x86_64', 'linux-x86_64'])

    @unittest.skipUnless(shutil.which('node'), 'requires Node.js')
    def test_launcher_failures(self):
        launcher = bundle.ROOT / bundle.FILES['server/launch.cjs']
        for args in ([], ['relative/omneum-server'], ['/missing/omneum-server'], ['/bin/sh'], ['/missing/omneum-server', ';']):
            result = subprocess.run(['node', str(launcher), *args], capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
            self.assertIn('Omneum connector:', result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires Node.js')
    def test_launcher_uses_no_shell_and_propagates_exit(self):
        if hasattr(os, 'getuid') and os.getuid() == 0:
            self.skipTest('launcher intentionally rejects root')
        launcher = bundle.ROOT / bundle.FILES['server/launch.cjs']
        with tempfile.TemporaryDirectory(prefix='omneum space ; ') as temp:
            executable = Path(temp) / 'omneum-server'
            executable.write_text('#!/bin/sh\nprintf "fixture stdout"\nprintf "fixture stderr" >&2\nexit 7\n')
            executable.chmod(0o700)
            result = subprocess.run(['node', str(launcher), str(executable)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 7)
            self.assertEqual(result.stdout, 'fixture stdout')
            self.assertEqual(result.stderr, 'fixture stderr')

    def test_client_links_roundtrip_and_shell_quoting(self):
        path = "/a path/quote' $(echo no)/omneum-server"
        cursor, code = links(path)
        parsed = urlparse(cursor)
        self.assertEqual(parsed.scheme, 'cursor')
        self.assertEqual(parsed.netloc, 'anysphere.cursor-deeplink')
        query = parse_qs(parsed.query)
        self.assertEqual(query['name'], ['omneum'])
        self.assertEqual(json.loads(base64.b64decode(query['config'][0])), {'omneum': {'command': path, 'args': []}})
        args = shlex.split(code)
        self.assertEqual(args[:2], ['code', '--add-mcp'])
        self.assertEqual(json.loads(args[2])['command'], path)
        for invalid in ('relative/omneum-server', '/bin/sh', '/a/omneum-server\n'):
            with self.assertRaises(ValueError):
                links(invalid)

    def test_direct_host_bootstrap_is_disabled(self):
        env = dict(os.environ)
        env.pop('OMNEUM_DISCOVERY_SANDBOX', None)
        result = subprocess.run(['sh', str(bundle.ROOT / 'deploy/discovery/entrypoint.sh')],
                                env=env, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('disabled outside the discovery image', result.stderr)

    def test_sandbox_keeps_production_code_unchanged(self):
        dockerfile = (bundle.ROOT / 'deploy/discovery/Dockerfile').read_text()
        entrypoint = (bundle.ROOT / 'deploy/discovery/entrypoint.sh').read_text()
        self.assertNotIn('--features test-daemon', dockerfile)
        self.assertIn('protected-voprf-v1', entrypoint)
        self.assertIn('runuser -u omneum-crypto', entrypoint)
        self.assertIn('runuser -u omneum-mcp', entrypoint)
        self.assertNotIn('--privileged', entrypoint)


if __name__ == '__main__':
    unittest.main()
