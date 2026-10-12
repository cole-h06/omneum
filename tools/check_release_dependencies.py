"""Fail release acceptance on current public advisories in runtime dependencies.

Run with the installed wheel's fresh venv Python. The candidate itself is local;
pip is installer tooling. Audit every other installed distribution and the
bundled SDK's upstream version explicitly, since it has no separate dist-info.
The check does not install audit tooling or alter dependency resolution.
"""
import concurrent.futures
from importlib import metadata, resources
import json
from urllib.parse import quote
from urllib.request import urlopen


def audit(name, version):
    url = f"https://pypi.org/pypi/{quote(name, safe='')}/{quote(version, safe='')}/json"
    with urlopen(url, timeout=30) as response:
        document = json.load(response)
    advisories = [item["id"] for item in document.get("vulnerabilities", []) if not item.get("withdrawn")]
    return {"name": name, "version": version, "advisories": advisories}


def main():
    packages = [(item.metadata["Name"], item.version) for item in metadata.distributions()
                if item.metadata["Name"].lower() not in {"omneum", "pip"}]
    upstream = json.loads(resources.files("omneum.mcp").joinpath("UPSTREAM.json").read_text())
    packages.append(("mcp", upstream["version"]))
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda item: audit(*item), sorted(set(packages))))
    print(json.dumps({"source": "public PyPI advisory metadata", "packages": results}, indent=2))
    findings = [item for item in results if item["advisories"]]
    if findings:
        raise SystemExit("Runtime or bundled SDK has reported security advisories")
    print(f"PASS: no published advisories for {len(results)} runtime/SDK versions")


if __name__ == "__main__":
    main()
