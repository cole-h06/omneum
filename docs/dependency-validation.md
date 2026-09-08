# uv migration validation

Validated on 2026-09-08, macOS ARM64, CPython 3.14.6 (core) and 3.13.15
(optional groups). Identical repeated commands are consolidated below.
`uv` denotes the checksum-verified 0.12.10 binary at
`/tmp/omneum-uv/uv-aarch64-apple-darwin/uv`.
Commands used `UV_CACHE_DIR=/tmp/omneum-uv-cache` to keep the download cache
separate. Default development commands used the repository `.venv`.

## Core and build commands

| Command | Result |
| --- | --- |
| `uv --version` | 0.12.10, commit 3c979abda; official ARM64 archive SHA-256 verified before execution |
| `uv sync --help`, `uv help build` | Confirmed `--locked`, `--no-default-groups`, build/isolation options |
| `uv lock` | 314 packages resolved; all original compatibility ranges retained; no group conflicts required |
| `uv lock --check` | Passed, including after all final configuration changes |
| `uv sync --locked` | Passed; native extension built; default environment excludes frameworks/benchmarks |
| `uv run --locked pytest` | 469 passed; repeated after final test interpreter edits, 469 passed again |
| `cargo test --locked` | 10 passed, including RFC 9497 vector; final repeat also passed |
| `uv pip check` | All installed development packages compatible |
| `uv build --wheel --out-dir /tmp/omneum-uv-dist` | Built `omneum-1.0.1-cp314-cp314-macosx_11_0_arm64.whl`; Maturin confirmed `locked` build option |
| `uv python find 3.13` | Found existing Homebrew CPython 3.13.15 |

## Production commands

These used `UV_PROJECT_ENVIRONMENT=/tmp/omneum-uv-production`, initially absent.

| Command | Result |
| --- | --- |
| `uv sync --locked --no-default-groups` | Passed; 41 installed distributions |
| `uv run --locked --no-default-groups python -` | Imported `omneum`, `omneum.server`, `omneum_oprf`; inspected distribution metadata and asserted pytest, Hypothesis, Maturin, all five frameworks, provider SDKs, NumPy and sentence-transformers were absent |
| `uv run --locked --no-default-groups python -` | Temporary deployment initialized using the installed CLI; launched installed `omneum-server`, completed MCP initialize/list_tools/ping; expected three tools present |
| `uv sync --locked --no-default-groups --no-editable` | Passed; non-editable source installation built |
| `uv run --locked --no-default-groups --no-editable python -I -c 'import omneum, omneum.server, omneum_oprf; print(omneum.__file__); print(omneum_oprf.__file__)'` | Passed; both Python package and native module resolved under production site-packages, outside the source tree |

## Optional group commands

For **each** of `langgraph`, `openai-agents`, `llamaindex`, `microsoft`, `crewai`,
and `benchmarks`, ran:

```bash
UV_PROJECT_ENVIRONMENT=/tmp/omneum-uv-GROUP uv sync --locked --python 3.13 --no-default-groups --group GROUP
UV_PROJECT_ENVIRONMENT=/tmp/omneum-uv-GROUP uv run --locked --python 3.13 --no-default-groups --group GROUP python -c 'IMPORT_CHECK'
```

All six independent synchronizations passed. Import checks all passed:

| Group | IMPORT_CHECK |
| --- | --- |
| langgraph | `import examples.langgraph.graph` |
| openai-agents | `import examples.openai_agents.agent` |
| llamaindex | `import examples.llamaindex.workflow` |
| microsoft | `from agent_framework import Agent; from agent_framework.openai import OpenAIChatClient` |
| crewai | `import examples.crewai.flow` |
| benchmarks | `import benchmarks.financial_dependency_suite.clients, benchmarks.financial_dependency_suite.naive_rag, benchmarks.financial_dependency_suite.semantic_reranker` |

Also ran the Microsoft example import (`import examples.microsoft.agent`) with
dummy `OPENAI_API_KEY` and `OPENAI_MODEL` values: passed; no provider call made.

With the same per-group environment and flags, ran `uv run ... -m MODULE` for
`examples.langgraph.run`, `examples.llamaindex.run`, and `examples.crewai.run`:
all completed their local Omneum evaluation workflows. `OTEL_SDK_DISABLED=true`
was set for these checks. CrewAI's first run was blocked by the filesystem sandbox
when its default memory storage tried to create an application-support directory.
After inspecting its storage implementation, reran with
`CREWAI_STORAGE_DIR=/tmp/omneum-uv-crewai-storage`: passed. No application code
was changed to accommodate this environmental restriction.

```bash
UV_PROJECT_ENVIRONMENT=/tmp/omneum-uv-benchmarks uv run --locked --python 3.13 --no-default-groups --group benchmarks pytest benchmarks/financial_dependency_suite/test_answer_scoring.py benchmarks/financial_dependency_suite/test_reproducibility.py benchmarks/financial_dependency_suite/test_benchmark_failures.py
```

Result: **13 passed**, without model downloads or provider calls.

`uv sync --locked --python 3.14 --group crewai --dry-run` failed as intended:
the explicit CrewAI group Python requirement rejects 3.14.

## Enforcement and repository checks

- In a disposable copy, changed pytest's metadata range to `>=8,<10`, then ran
  `uv lock --check --offline --project TEMP`: correctly failed because the lockfile
  needed updating. An earlier probe with `<9` also failed, but because older
  pytest metadata was unavailable offline; that probe alone was inconclusive.
- In another disposable copy, replaced rfc8785 artifact hashes with zeros and ran
  `uv sync --locked --no-default-groups --no-install-project --project TEMP`
  with an empty cache: correctly rejected rfc8785 with a SHA-256 mismatch.
- Parsed `uv.lock` with Python `tomllib`: all **313 registry packages** have
  SHA-256 artifact hashes. Omneum is the additional local source package.
- Parsed workflow YAML and asserted every action has a full 40-character SHA,
  permissions remain `contents: read`, no `--frozen` command exists, and uv and
  Maturin pins agree across configuration, lock, and CI: passed.
- `git diff --exit-code -- Cargo.lock Cargo.toml src omneum`: passed; no Rust,
  VOPRF, protocol, or runtime application source changes.
- `git diff --check`: passed. Reviewed dependency declaration and workflow diffs;
  the first lock is a compatible new resolution, not a copy of locally installed
  versions. Legacy requirement contents are retained.
- Official GitHub/PyPI metadata queries verified uv/backend releases and action
  commits. The original Maturin action SHA returned 404; its verified replacement
  is documented in the dependency guide. Initial sandboxed network access failed;
  authorized network access succeeded.

The hosted GitHub Actions matrix was not executed locally. Linux/Windows and
Python 3.11/3.12 execution remain for CI. Full provider-backed OpenAI/Microsoft
runs and full model-backed benchmark tests were not executed. Resolution and
imports succeeded; those checks do not establish live-provider compatibility.
