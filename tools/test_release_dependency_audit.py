"""The audit must cover runtime edges, not hide dependencies by package name."""
from types import SimpleNamespace
import unittest

from check_release_dependencies import runtime_packages


class DependencyAuditTests(unittest.TestCase):
    def graph(self, requirements):
        data = {name: SimpleNamespace(metadata={"Name": name}, version="1.0", requires=deps)
                for name, deps in requirements.items()}
        return lambda name: data[name]

    def test_bootstrap_package_outside_runtime(self):
        lookup = self.graph({"omneum": ["library>=1"], "library": [], "setuptools": []})
        self.assertEqual(runtime_packages(lookup), {("library", "1.0")})

    def test_setuptools_is_audited_if_runtime_requires_it(self):
        lookup = self.graph({"omneum": ["library"], "library": ["setuptools"], "setuptools": []})
        self.assertIn(("setuptools", "1.0"), runtime_packages(lookup))

    def test_transitive_selected_extra_is_included(self):
        lookup = self.graph({"omneum": ["library[secure]", "unused; extra == 'operator'"],
                            "library": ["backend; extra == 'secure'"], "backend": [], "unused": []})
        self.assertEqual(runtime_packages(lookup), {("library", "1.0"), ("backend", "1.0")})

    def test_unsatisfied_runtime_dependency_fails(self):
        lookup = self.graph({"omneum": ["library>=2"], "library": []})
        with self.assertRaisesRegex(RuntimeError, "not satisfied"):
            runtime_packages(lookup)


if __name__ == "__main__":
    unittest.main()
