"""Exercise the actual macOS installer parent guard without installation or sudo."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == 'darwin', 'BSD stat behavior requires macOS')
class MacOSParentBoundaryTests(unittest.TestCase):
    def guard(self, path, prelude=''):
        source = (Path(__file__).resolve().parents[1] / 'deploy/install-macos.sh').read_text()
        body = source.split('trusted_parent() {', 1)[1].split('\n}\n', 1)[0]
        script = prelude + 'fail() { exit 17; }\ntrusted_parent() {' + body + '\n}\ntrusted_parent "$1"\n'
        return subprocess.run(['/bin/sh', '-c', script, 'guard', str(path)], capture_output=True).returncode

    def test_root_owned_library_allowed(self):
        self.assertEqual(self.guard(Path('/Library')), 0)

    def test_login_owned_parent_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(self.guard(root), 17)
            link = root / 'link';link.symlink_to('/Library', target_is_directory=True)
            self.assertEqual(self.guard(link), 17)

    def test_launchd_uses_protected_library_binary(self):
        root = Path(__file__).resolve().parents[1]
        plist = (root / 'deploy/launchd/ai.omneum.omneumd.plist').read_text()
        self.assertIn('/Library/Omneum/omneumd', plist)
        self.assertNotIn('/usr/local/libexec/omneumd', plist)

    def test_extended_acl(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # Model root ownership without changing a system path or using sudo;
            # ls inspects a real ACL attached only to this disposable directory.
            owner = 'stat() { case "$2" in %u) printf 0;; %Lp) printf 755;; esac; }\n'
            self.assertEqual(self.guard(root, owner), 0)
            subprocess.run(['/bin/chmod', '+a', 'everyone allow add_file', str(root)], check=True)
            self.assertEqual(self.guard(root, owner), 17)


if __name__ == '__main__':
    unittest.main()
