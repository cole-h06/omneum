# Contributing to Omneum

Thank you for your interest in contributing to Omneum!

Bug reports, fixes, tests, documentation changes, and new integrations are
welcome.

## Getting Started

### Prerequisites

You will need:

- Python 3.11, 3.12, 3.13, or 3.14
- `uv` 0.12.10
- Rust/Cargo

### Install

Fork the repository, then clone your fork:

```bash
git clone https://github.com/YOUR_USERNAME/omneum.git
cd omneum
```

Add the main repository as `upstream`:

```bash
git remote add upstream https://github.com/cole-h06/omneum.git
```

Install the locked environment:

```bash
uv sync --locked
```

Build the Rust extension:

```bash
uv run maturin develop
```

Check the install:

```bash
uv run python -c "import omneum; import omneum_oprf"
```

## Repository Layout

```text
omneum/
├── client.py              Python client
├── server.py              MCP server
├── proxy.py               omneum-server entrypoint
├── mapping.py             application data -> observations
├── dependency.py          source-dependency estimation
├── engine_graph.py        evaluation graph
├── inference.py           evaluation inference
├── information.py         information models
├── linkage.py             linkage inputs
├── oprf.py                Python VOPRF interface
├── serialization.py       wire serialization
├── installation.py        installer
├── runtime_bundle.py      managed runtime
├── tools/
│   ├── evaluate_context.py
│   ├── evaluate_voprf.py
│   └── ping.py
└── transport/
    ├── mcp.py
    └── stdio.py

src/
├── lib.rs                 Python extension
├── voprf_core.rs          VOPRF implementation
├── daemon/                daemon
└── bin/
    ├── omneumd.rs
    └── omneum-server.rs

tests/                     Python and integration tests
tests/security/            security and install tests
tests/vectors/             compatibility vectors
tools/                     release tooling
examples/                  integrations
benchmarks/                benchmark suites
docs/                      documentation
```

If you're changing evaluation behavior, start in `omneum/`, not the MCP
transport. `server.py`, `tools/`, and `transport/` should not contain a second
implementation of the evaluator.

## Running Omneum

Run the MCP server directly from the checkout:

```bash
uv run python -m omneum.server
```

The server registers three tools:

```text
ping
evaluate_voprf
evaluate_context
```

Their implementations are under `omneum/tools/`.

The Python client exposes `evaluate_context()` and `evaluate_mapped()`.
`evaluate_mapped()` maps application records before using the same evaluation
path. Don't implement a separate evaluator for it.

## Mapping

Application data enters Omneum as:

```text
Source
Claim
Observation
```

Mapping code lives in `omneum/mapping.py`.

A `Source` identifies where information came from. A retrieval is not a source.

`observed_at` is when the observation was made. `source_modified_at` is when the
source itself was modified. If the source modification time is unknown, leave it
unknown. Don't copy `observed_at` into `source_modified_at`.

Mapping is deterministic. Don't add an LLM call, embedding lookup, fuzzy match,
or entity-resolution pass to guess missing source or claim identity.

## Dependency Estimation

Source-dependency estimation lives in `omneum/dependency.py`.

Missing dependency evidence does not mean two sources are independent. Keep
unobserved signals unobserved rather than turning missing metadata into a zero
dependency result.

For dependency changes, run:

```bash
uv run --locked pytest tests/test_dependency.py
```

## VOPRF and Daemon

The native VOPRF implementation is in:

```text
src/voprf_core.rs
```

The daemon is under:

```text
src/daemon/
src/bin/omneumd.rs
```

The daemon owns the VOPRF private key. The MCP process communicates with it over
local IPC; it does not load the daemon's private key.

For Rust changes, run:

```bash
cargo test --locked
cargo test --locked --no-default-features --features daemon
```

Rebuild the Python extension after changing the native module:

```bash
uv run maturin develop
```

Don't move private-key loading into the Python server or client.

## MCP and stdio

MCP handling is in `omneum/transport/mcp.py`. The stdio transport is in
`omneum/transport/stdio.py`.

For MCP or stdio changes, run the relevant tests:

```bash
uv run --locked pytest \
  tests/test_mcp.py \
  tests/test_client_stdio.py \
  tests/test_evaluate_context_stdio.py \
  tests/test_stdio_bounds.py
```

Keep input limits at the transport boundary. Don't add an unbounded read before
the request has been bounded and validated.

## Installer and Runtime

Installer and managed-runtime code is split across:

```text
omneum/installation.py
omneum/provision.py
omneum/runtime_bundle.py
omneum/daemon.py
omneum/proxy.py
```

Installer changes can affect OS users, file permissions, daemon configuration,
runtime verification, and the boundary between `omneum-server` and `omneumd`.

General installer tests include:

```bash
uv run --locked pytest \
  tests/test_install.py \
  tests/test_install_server.py \
  tests/test_runtime_builder.py
```

Platform-specific security tests are under `tests/security/`.

Don't weaken file ownership, key permissions, or process isolation to make an
install test pass.

## Tests

Run the Python test suite:

```bash
uv run --locked pytest
```

Run the Rust tests:

```bash
cargo test --locked
cargo test --locked --no-default-features --features daemon
```

Release tooling also has its own tests:

```bash
python -m unittest discover -s tools -p 'test_release_*.py' -v
```

While working, run the smallest test that covers the code you're changing.
Before opening a PR, run the full applicable suite.

Don't change an expected value just to make a behavior change pass. If the
behavior is supposed to change, include that change in the PR.

## Security Tests

Security tests live under:

```text
tests/security/
```

They cover installed runtimes, process isolation, input handling, installation,
and adversarial cases.

Some tests are platform-specific. Run the ones that apply to the code and
platform you're changing.

Changes to the installer, daemon, IPC boundary, VOPRF handling, or input
framing should include the relevant security tests.

## Integrations

Examples and integrations live under `examples/`.

Integration-specific dependencies should stay out of the base install. If an
integration needs another package, use the corresponding dependency group in
`pyproject.toml`.

Keep integration code at the integration boundary. Don't add framework-specific
behavior to the evaluator to support one example.

## Before Changing a Public Contract

Open an issue before changing:

- `Source`, `Claim`, or `Observation`
- `evaluate_context`
- MCP tool names or request/response shapes
- canonicalization or linkage encoding
- dependency signal definitions
- VOPRF key or proof handling
- daemon privilege boundaries

Include the current behavior, the proposed behavior, and anything existing
callers would need to change.

## Pull Requests

Sync your fork before starting:

```bash
git fetch upstream
git checkout main
git merge --ff-only upstream/main
git checkout -b <branch>
```

Before opening the PR:

```bash
git status --short
git diff --check
```

Then run the tests for the code you changed.

In the PR, include:

- what changed
- where it changed
- how to reproduce the old behavior, for a bug
- the commands you ran
- any wire-format, installer, compatibility, or security change

Keep unrelated cleanup out of the same PR.

## Reporting Bugs

Include:

- Omneum version or commit
- OS
- Python version
- how Omneum was run: Python API, `omneum-server`, or another MCP client
- minimal input that reproduces the problem
- expected result
- actual result or traceback

For installer or daemon bugs, include the relevant install or daemon logs.

Remove credentials, API keys, private context, deployment secrets, and VOPRF
private keys before posting logs.

## Security

Don't open a public issue for a security vulnerability. See
[SECURITY.md](SECURITY.md).