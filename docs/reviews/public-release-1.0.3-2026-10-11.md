# Omneum 1.0.3 public release readiness

Status: preparation in progress; publication forbidden until explicit approval.
The public PyPI project endpoint returns 404, GitHub has no release tags, and
this GitHub account has repository administration permission. The repository
is private. Neither `github-release` nor `pypi` environments exist; PyPI owner
and pending Trusted Publisher setup have not been verified. Version 1.0.3 is a
candidate, not a reserved package name or published version.

## Confirmed blockers and fixes

- **High — Intel macOS installation:** fresh Intel Python 3.11–3.14 environments
  fail installing cryptography 50.0.2 from the candidate wheel because upstream
  removed Intel binary wheels in 49. pip tries a Rust/OpenSSL source build.
  Reproduction: run `tools/release_wheels.py smoke` with Intel Python against
  each `macosx_10_12_x86_64` wheel. This violates the installation objective.
  Constraining Intel to the latest 48.0.1 binary release was evaluated and
  rejected: three distinct PYSEC-2026-3552/3553/3554 advisories are fixed only in
  49/50. Those vulnerable certificate-verification and PKCS7 operations are
  not demonstrated reachable from Omneum. The dependency advisories and absent
  wheels are confirmed; an Omneum exploit has not been demonstrated. No
  vulnerable cap remains in pyproject.toml or uv.lock. Launch needs maintained,
  patched Intel wheels upstream or an explicitly approved platform/packaging
  design change. Do not quietly narrow the promised platform matrix.
  [Upstream changelog](https://cryptography.io/en/49.0.0/changelog/).

- **High — macOS executable ancestry:** `deploy/install-macos.sh` formerly
  placed the daemon at `/usr/local/libexec/omneumd` without checking writable
  ancestors. On a machine where a login user can replace that parent hierarchy,
  a replacement executable can run as the cryptographic service identity after
  restart and access its private key. The insecure installer condition is
  confirmed in code; no private key was accessed and no system path was changed
  during this review. Fix: use `/Library/Omneum/omneumd`, validate root-owned,
  non-writable, non-symlinked ancestors before mutation, and update the launchd
  template. The actual guard passed bounded root-parent, login-owned-parent,
  and symlink rejection checks in `tools/test_macos_install_boundary.py`.
  Full protected launchd acceptance remains a required fresh-host check.

- **Medium — distribution privacy:** the first sdist contained untracked
  `tools/provenance_explorer/` and the separate production audit report; native
  wheels contained developer home paths in Rust strings and Cargo SBOMs.
  Fix: packaging excludes unrelated tools/private audit artifacts, compiler
  path remapping removes native home paths, and `release_wheels.sanitize`
  normalizes SBOM references and recomputes RECORD. Reproduction: unpack wheel
  members and search `/Users/`; enumerate initial sdist members. Current
  candidates are checked for those paths, private-key PEM markers and common
  credential patterns. Pattern scanning is not a proof that every possible
  secret is absent. Review the exact candidate commit before making it public.

- **Medium — release completeness/provenance:** source archives were not built
  or included in the publishing workflow, Rust package version was 0.1.0, and
  Rust builds were not toolchain-pinned. Fix: align Cargo package/lock to 1.0.3,
  pin Rust 1.97.1 and maturin 1.15.0, validate and publish the sdist alongside
  all sixteen existing wheel targets, reject fixture evaluator binaries, and
  attest GitHub daemon assets. PyJWT 2.15.0 is locked and required as the public
  package's minimum. The installed runtime uses the existing locked environment.

## Verification completed so far

- Python 3.11–3.14: four native arm64 macOS wheels each installed with public
  dependencies in a new disposable venv, outside the checkout; imports,
  console entry points, resources and `pip check` passed.
- All four Intel Python smoke attempts under Rosetta failed at the confirmed
  missing cryptography wheel. Both daemon architectures execute their
  `capabilities` command as protected evaluators; this is not launchd acceptance.
- Installed arm64 wheel regression: 215 installer/MCP/VOPRF/SQLite/local
  persistence tests passed; 11 database-backed tests skipped without a test DSN.
  One missing copied contract fixture was corrected and its test passed.
- Independent Braid conformance: 8 propagation, 8 fusion, 3 cluster and 18 record
  cases passed at commit bce69eba0fae26091b75f9ee715c604b34e5a996; 19 pin/conformance
  regression tests passed.
- Forty release contract tests and three actual macOS parent-guard tests passed.
  Rust protected-daemon regression: 15 passed; cargo-audit: zero advisories in
  85 dependencies. Public installed environment audit: zero reported advisories
  in 44 dependencies, Omneum skipped because not yet on PyPI. The rejected Intel
  fallback has three distinct advisories (six duplicated audit entries).
- Eight macOS wheels' complete RECORD hashes/sizes verified. No developer-home
  paths or private-key PEM markers were found in current wheel members or sdist.
- GitHub workflow passed official actionlint, including fresh three-platform
  installed-wheel acceptance and publication ordering. No hosted run of the
  uncommitted candidate has been started.

Fresh macOS machine/launchd acceptance is unavailable here; this development
machine was not repurposed. Fresh Ubuntu x86_64 QEMU build/acceptance is being
run using verified official Ubuntu 22.04.5 cloud image SHA-256
`012d81fade7e8ff4428fc35dfeee711d66d1f47d5ea9c5c8ced96a85b959835c`.
Docker x86_64 execution failed with exec-format errors and was not counted as
acceptance. Windows SDK wheels remain a hosted CI build requirement.

## Required publication configuration

Configure protected GitHub environments `github-release` and `pypi` with actual
required reviewers; YAML names alone do not create protections. Verify PyPI
ownership and its pending Trusted Publisher: project `omneum`, owner `cole-h06`,
repository `omneum`, workflow `CI.yml`, environment `pypi`. PyPI account/project
owner identity is a separate matter from the GitHub owner string. A pending
publisher does not reserve the name. Repository visibility/history publication
requires approval before anonymous downloads can work.

See [release commands](../guides/releasing.md). No commits, pushes, tags, GitHub
Releases, PyPI uploads, production key provisioning, database changes, or public
contribution enablement were performed. The Network production VM is separate:
Nginx remains active, Omneum units inactive, and the privileged audit batch is
still waiting for operator output. Its existing runtime and configuration were
not rebuilt, reinstalled or overwritten.
