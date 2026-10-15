"""Publication boundaries: reused versions, partial uploads, and byte integrity."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import release_publication
from release_publication import check_new, verify_document


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.expected = {'version': '1.0.4', 'distributions': {'a.whl': {'sha256': 'a' * 64, 'size': 123}}}
        self.document = {'info': {'version': '1.0.4', 'description': '<!-- mcp-name: ai.omneum/omneum -->'},
                         'urls': [{'filename': 'a.whl', 'digests': {'sha256': 'a' * 64}, 'size': 123, 'yanked': False}]}

    def test_new_version_and_existing_version(self):
        check_new('1.0.4', lambda _: None)
        with self.assertRaises(ValueError):
            check_new('1.0.4', lambda _: self.document)

    def test_exact_public_release(self):
        self.assertEqual(set(verify_document(self.document, self.expected)), {'a.whl'})

    def test_absent_or_wrong_version(self):
        for document in [None, {**self.document, 'info': {**self.document['info'], 'version': '1.0.3'}}]:
            with self.assertRaises(ValueError):
                verify_document(document, self.expected)

    def test_partial_unexpected_or_duplicate_public_files(self):
        for urls in [[], self.document['urls'] * 2, [{**self.document['urls'][0], 'filename': 'other.whl'}]]:
            with self.assertRaises(ValueError):
                verify_document({**self.document, 'urls': urls}, self.expected)

    def test_wrong_hash_size_or_yanked(self):
        for key, value in [('digests', {'sha256': 'b' * 64}), ('size', 124), ('yanked', True)]:
            document = copy.deepcopy(self.document)
            document['urls'][0][key] = value
            with self.assertRaises(ValueError):
                verify_document(document, self.expected)

    def test_missing_identity(self):
        self.document['info']['description'] = 'Omneum'
        with self.assertRaises(ValueError):
            verify_document(self.document, self.expected)

    def test_manifest_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            with patch.object(release_publication, 'manifest', return_value=self.expected), patch(
                'sys.argv', ['release_publication.py', 'manifest', '--version', '1.0.4', '--manifest', str(path)]
            ):
                release_publication.main()
            self.assertEqual(json.loads(path.read_text()), self.expected)
            self.assertTrue(path.read_bytes().endswith(bytes([10])))


if __name__ == '__main__':
    unittest.main()
