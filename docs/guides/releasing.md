# Public release procedure

The public package and protected daemon bundle use the same exact version;
1.0.3 maps to tag `v1.0.3`. Rust crate version, source metadata, wheel metadata,
and the Linux offline runtime must agree. Release validation rejects fixture-only
evaluator builds; CI also checks the actual `capabilities` output. Windows wheels are SDK-only.

## Preparation and approval gates

Review the candidate commit without staging unrelated worktree changes. Run
`uv lock --check` using uv 0.12.10 and the release contract tests. CI pins Rust
1.97.1 and maturin 1.15.0. Native builds remap compiler paths; wheel preparation
normalizes local Cargo SBOM identifiers and recalculates RECORD before smoke tests.

The repository must be public for anonymous installer downloads. Changing its
visibility exposes repository history and requires explicit owner approval.
Configure GitHub environments `github-release` and `pypi` with required human
reviewers before pushing a release tag. Merely naming an environment in YAML
does not configure its approval protection.

The PyPI owner must register a pending Trusted Publisher for project `omneum`,
GitHub owner `cole-h06`, repository `omneum`, workflow filename `CI.yml`, and
environment `pypi`. A missing public PyPI project does not establish ownership
or reserve its name. Use the owner's account, with no uploaded API token.
See [PyPI's pending publisher instructions](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

After the reviewed candidate exists on an authorized GitHub branch, a manual
CI run prepares artifacts and exercises fresh installations without publishing:

```sh
gh workflow run CI.yml --repo cole-h06/omneum --ref REVIEWED_BRANCH
gh run list --repo cole-h06/omneum --workflow CI.yml --limit 5
gh run watch RUN_ID --repo cole-h06/omneum --exit-status
gh run download RUN_ID --repo cole-h06/omneum --name daemon-release-assets --dir release-assets
gh run download RUN_ID --repo cole-h06/omneum --name python-release-wheels --dir pypi-dist
python tools/release_daemon.py verify --tag v1.0.3
python tools/release_wheels.py verify --tag v1.0.3 --wheels pypi-dist --daemon-assets release-assets
python tools/release_sdist.py --sdist pypi-dist/omneum-1.0.3.tar.gz --version 1.0.3
```

Expect sixteen wheels (four Python versions across macOS arm64/Intel, Linux
x86_64 and Windows SDK-only), one sdist, three daemon archives and their exact
three-entry SHA256SUMS. CI fresh-host acceptance on Ubuntu and both macOS
architectures uses the installed wheel and unpublished candidate assets. It
replaces only the download boundary; checksum validation, administrator
installation, key provisioning, services, MCP, SQLite and restart are real.
This is followed by an anonymous public-download check before PyPI publication.

## Publication checkpoint

Do not run these commands until explicit publication authorization has been
received, all CI gates have passed, and project ownership and environments have
been verified. Recheck name/version availability immediately before publishing.

```sh
git tag -a v1.0.3 APPROVED_COMMIT_SHA -m 'Omneum 1.0.3'
git push origin refs/tags/v1.0.3
```

The tag starts a new complete build and acceptance run. Approve `github-release`
only after reviewing that run's artifacts; approve `pypi` after the GitHub Release
has verified uploaded bytes and anonymous access. The workflow publishes the
validated wheel bytes and sdist using OIDC Trusted Publishing. GitHub daemon
assets receive build-provenance attestations; PyPI's publishing action produces
publication attestations. The installer checks SHA256SUMS, not attestations;
GitHub release permissions remain part of the download trust boundary.

Finally, use genuinely clean supported machines to run:

```sh
python3.11 -m venv .venv
. .venv/bin/activate
pip install omneum==1.0.3
omneum install
```

Connect an MCP client to `omneum-server`, call `ping`, and run the README's
SDK evaluation example. Verify a second evaluation after restarting the daemon
preserves local SQLite history. Network enrollment/contribution is a separate
explicit opt-in and is never required for local installation. Announce readiness
only after these published-package and anonymous-download checks pass.
