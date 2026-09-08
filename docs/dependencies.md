# Dependency environments

Use **uv 0.12.10** from the [official release](https://github.com/astral-sh/uv/releases/tag/0.12.10).
Verify the archive against its published SHA-256 checksum before installing it.
The repository requires this exact uv version. CPython 3.11–3.14 and a Rust
compiler capable of building the existing edition-2024 crate are required.
Run the commands below from the repository root.

## Development and production

```bash
uv lock --check
uv sync --locked
uv run --locked pytest
cargo test --locked
```

The default `dev` group contains pytest, Hypothesis, and Maturin. `pytest` discovers
`tests/` by default; benchmark tests are explicitly selected separately because
some load embedding/reranking models or call external providers.

For a server/runtime installation:

```bash
uv sync --locked --no-default-groups
uv run --locked --no-default-groups omneum init
uv run --locked --no-default-groups omneum-server
```

Initialize only when creating a deployment. Existing deployment configuration
and key handling are unchanged. Use `--no-default-groups` on subsequent `uv run`
commands too, or uv will restore development dependencies. Alternatively activate
`.venv/bin/activate` (PowerShell: `.venv\Scripts\Activate.ps1`) and invoke the
installed `omneum` / `omneum-server` commands directly.

`sync` installs the project editably by default. For a deployment checkout that
must not use an editable installation, add `--no-editable` to both sync and run.
Use a separate checkout or set `UV_PROJECT_ENVIRONMENT` to an absolute directory
when maintaining development and production environments concurrently. Exact
sync removes packages outside the selected dependency set.

The production environment excludes pytest, Hypothesis, Maturin as an installed
runtime package, frameworks, provider SDKs, NumPy, and sentence-transformers.
A source installation still executes Maturin in a temporary isolated build
environment and invokes Cargo. It therefore needs a build toolchain; excluding
development groups does not turn a source installation into a wheel-only install.
Installing a published Omneum wheel with pip does not apply this repository's
uv.lock or cooldown policy to its dependencies.

## Optional environments

All groups resolve together in one `uv.lock`; no conflicting-group override was
needed for this resolution. Select only the framework being exercised:

| Repository code | Group | Existing requirement retained |
| --- | --- | --- |
| `examples/enterprise` | none | Core runtime only |
| `examples/langgraph` | `langgraph` | `langgraph>=1,<2` |
| `examples/openai_agents` | `openai-agents` | `openai-agents>=0.13,<1` |
| `examples/llamaindex` | `llamaindex` | `llama-index>=0.13,<1` |
| `examples/microsoft` | `microsoft` | `agent-framework>=1,<2` |
| `examples/crewai` | `crewai` | `crewai>=1.15,<2`, Python below 3.14 |
| `benchmarks/financial_dependency_suite` | `benchmarks` | Six original benchmark requirements, plus explicit python-dotenv and pytest |

```bash
uv sync --locked --group langgraph
uv run --locked --group langgraph -m examples.langgraph.run
uv sync --locked --python 3.13 --group crewai
uv run --locked --python 3.13 --group crewai -m examples.crewai.run
uv sync --locked --group benchmarks
uv run --locked --group benchmarks pytest benchmarks/financial_dependency_suite
```

Framework groups are development groups, not published package extras. They do
not appear in Omneum's wheel runtime metadata. CrewAI's group additionally
requires Python 3.11–3.13, so selecting it with Python 3.14 fails explicitly
instead of silently installing no CrewAI. Other groups retain the project's
Python range; resolution does not guarantee every dependency has wheels on every
future Python version or platform.

Benchmarks may need provider credentials and may download models; those model
files, provider services, and benchmark data are outside the Python lockfile.
Do not treat a full benchmark run as an offline unit-test command.

## Dependency audit and migration

Core imports require MCP, Pydantic, Typer, idna, rfc3986, orjson, rfc8785, and
platformdirs. `omneum_oprf` is built locally from the Rust crate, not downloaded
as a separate Python dependency. Pydantic (`omneum/models.py`, `client.py`, tools)
and Typer (`omneum/cli.py`) were previously supplied transitively. They are now
explicit dependencies; their lower bounds follow MCP 1.x's declared requirements.
MCP itself supplies the stricter Pydantic lower bound for Python 3.14.

`mcp[cli]` is replaced by `mcp` plus explicit Typer: Omneum uses its own CLI,
not MCP's CLI extra. The existing `pydantic-settings>=2.14,<2.15` constraint is
retained: Omneum does not import it directly, but MCP requires it at runtime.
It also brings python-dotenv into the runtime transitively. The benchmarks
import `dotenv` directly in `clients.py`, so their group explicitly declares it.
The prompt-injection benchmark imports test helpers containing pytest; pytest
is therefore included even when the benchmark group is used without `dev`.

The old root runtime requirements omitted platformdirs and pydantic-settings
from project metadata. The old development requirements bundled all five
frameworks; `tests/` does not import those frameworks. The SDK documentation
also advertised a nonexistent `.[dev]` extra. The new commands use PEP 735
groups instead. The large llama-index and agent-framework umbrella requirements
are retained in their own groups to preserve the existing integration contract;
Omneum's examples only import a subset of their modules.

The three legacy requirements files are retained temporarily as migration
references, not deterministic installation interfaces. Their dependencies have
all been represented in pyproject.toml, and installation documentation now uses
uv. Keeping them avoids claiming that every model/provider-backed benchmark and
framework execution has been validated. Do not update them independently; a
future cleanup can remove them after those workflows have been exercised.

## Locking, builds, and updates

`uv.lock` records exact direct/transitive versions, Python/platform markers,
artifact URLs, and SHA-256 hashes. `uv sync --locked` checks that the lock still
matches project metadata and uses its artifact hashes. `--frozen` is deliberately
not used: it skips the freshness check. Ranges in project metadata remain
compatibility declarations; they do not cause fresh CI syncs to upgrade packages.

`exclude-newer = "7 days"` uses uv's supported relative-duration syntax and
excludes artifacts uploaded within the preceding seven days when resolving.
It is a review window, not a malware detector. Locked installations keep their
resolution as time passes. New resolution is intentional:

```bash
uv lock --upgrade-package PACKAGE
uv lock --check
uv sync --locked
uv run --locked pytest
cargo test --locked
```

Review the complete lock diff (including transitives and hashes), release notes,
and relevant group tests before committing pyproject.toml and uv.lock together.
A version-range change requires `uv lock` too. Avoid broad `--upgrade` during
unrelated work. This is the first repository lock, so its versions are a fresh
compatible resolution, not a freeze of a developer's existing environment.
Shared framework constraints can select older compatible runtime dependencies.
For example, locked CrewAI 1.15.18 requires `mcp~=1.28.1` and
`pydantic>=2.11.9,<2.13`, explaining MCP 1.28.1 and Pydantic 2.12.5 in this
resolution. These are compatible with Omneum's retained ranges, not arbitrary
version overrides.

PEP 517 build dependencies are resolved separately from the project lock.
`build-constraint-dependencies` fixes isolated Omneum builds to Maturin 1.15.0
(published 2026-08-24), while preserving `maturin>=1,<2` in the build declaration.
The development environment also locks Maturin and its wheel hashes. Maturin's
`locked = true` enforces Cargo.lock for source builds. When updating Maturin,
review and update the build constraint, uv.lock, and CI `maturin-version` together.
An isolated build's Maturin download does not get its artifact identity from
uv.lock; the constraint fixes its version, not its hash. Third-party source
build backends are likewise outside uv.lock. Prefer compatible wheels and build
in a controlled environment; this migration does not claim fully hermetic or
bit-for-bit reproducible native builds.

CI retains read-only GitHub permissions and full commit-SHA action pins. The uv
action is v10.0.1 at `20cfd1bf945f4377ade1205e4dbc17946fc9a30d`; its version and
Linux archive checksum are explicit. Tests run against locked core+dev installs
on Python 3.11–3.14, then sync/check production imports. PRs run these tests;
tag/manual builds retain the existing wheel platform matrix and artifact upload.
The previous Maturin action SHA returned HTTP 404 from GitHub; its replacement
is verified v1.51.0 at `e83996d129638aa358a18fbd1dfb82f0b0fb5d3b`, with Maturin
1.15.0 and explicit `--locked`. The other action pins are unchanged.

## Security boundary

Locking prevents silent compatible-release drift and verifies the identities of
locked registry artifacts. Smaller production/default environments reduce the
number of packages installed and imported. Neither hashes nor a release cooldown
prove that an approved artifact is benign. A malicious approved package, build
backend, action, compiler, or interpreter can still execute code with its
process's permissions. Caches and the build host remain trusted.

There is no new Python sandbox, network restriction, secret isolation, or
Python/Rust privilege boundary. A compromised Omneum process can read accessible
configuration, environment variables, credentials, and files, invoke subprocesses
and networking, and read the VOPRF private-key file if its OS identity can read
that file. Rust key validation and VOPRF blinding do not prevent this. OS-level
least privilege, separate build/runtime identities, restricted egress, and
stronger key isolation remain separate workstreams. No VOPRF or assertion
protocol behavior is changed here.

See the [migration validation record](dependency-validation.md) for executed checks
and the limits of local platform/provider coverage.
