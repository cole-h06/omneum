"""Fail release acceptance on current public advisories in runtime dependencies.

Run with the installed wheel's fresh venv Python. The candidate itself is local;
pip and Python 3.11's bootstrap setuptools are installer tooling. Audit the
entire declared runtime graph and the bundled SDK's upstream version explicitly,
since it has no separate dist-info. Report unrelated/bootstrap findings too.
The check does not install audit tooling or alter dependency resolution.
"""
import concurrent.futures
from importlib import metadata, resources
import json
from urllib.parse import quote
from urllib.request import urlopen

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def runtime_packages(distribution=metadata.distribution):
    """Follow every active Requires-Dist edge, including transitive extras."""
    pending = [("omneum", frozenset({""}))]
    visited = set()
    packages = set()
    while pending:
        name, extras = pending.pop()
        key = (canonicalize_name(name), extras)
        if key in visited:
            continue
        visited.add(key)
        item = distribution(name)
        if key[0] != "omneum":
            packages.add((item.metadata["Name"], item.version))
        for raw in item.requires or []:
            requirement = Requirement(raw)
            if requirement.marker and not any(requirement.marker.evaluate({"extra": extra}) for extra in extras):
                continue
            dependency = distribution(requirement.name)
            if not requirement.specifier.contains(dependency.version, prereleases=True):
                raise RuntimeError("installed runtime requirement is not satisfied: " + raw)
            pending.append((requirement.name, frozenset({""} | requirement.extras)))
    return packages


def audit(name, version):
    url = f"https://pypi.org/pypi/{quote(name, safe='')}/{quote(version, safe='')}/json"
    with urlopen(url, timeout=30) as response:
        document = json.load(response)
    advisories = [item["id"] for item in document.get("vulnerabilities", []) if not item.get("withdrawn")]
    return {"name": name, "version": version, "advisories": advisories}


def main():
    packages = runtime_packages()
    runtime_names = {canonicalize_name(name) for name, _ in packages} | {"omneum"}
    tooling = {(item.metadata["Name"], item.version) for item in metadata.distributions()
               if canonicalize_name(item.metadata["Name"]) not in runtime_names}
    upstream = json.loads(resources.files("omneum.mcp").joinpath("UPSTREAM.json").read_text())
    packages.add(("mcp", upstream["version"]))
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda item: audit(*item), sorted(packages)))
        bootstrap_results = list(pool.map(lambda item: audit(*item), sorted(tooling)))
    print(json.dumps({"source": "public PyPI advisory metadata", "runtime_and_sdk": results,
                      "outside_runtime_graph": bootstrap_results}, indent=2))
    findings = [item for item in results if item["advisories"]]
    if findings:
        raise SystemExit("Runtime or bundled SDK has reported security advisories")
    print(f"PASS: no published advisories for {len(results)} runtime/SDK versions")


if __name__ == "__main__":
    main()
