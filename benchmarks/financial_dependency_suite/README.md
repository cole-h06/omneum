# Financial dependency benchmarks

From the repository root, use uv 0.12.10 and the benchmark dependency group:

```bash
uv sync --locked --group benchmarks
uv run --locked --group benchmarks -m benchmarks.financial_dependency_suite.run_suite
```

The group includes sentence-transformers, NumPy, Anthropic, OpenAI, Google GenAI,
Cohere, python-dotenv, and pytest, with their transitive dependencies in uv.lock.
It is excluded from the default development and production environments.
See [dependency workflows](../../docs/dependencies.md) for update and installation policies.
The legacy requirements.txt is retained as a migration reference.

Some tests and benchmark entry points download embedding/reranking models or
call providers configured in `clients.py`. Model downloads and provider services
are outside uv.lock and require separate review/reproducibility controls.
Configure credentials for the providers you intend to exercise before a live run.

These selected tests do not require provider calls or model downloads:

```bash
uv run --locked --group benchmarks pytest \
  benchmarks/financial_dependency_suite/test_answer_scoring.py \
  benchmarks/financial_dependency_suite/test_reproducibility.py \
  benchmarks/financial_dependency_suite/test_benchmark_failures.py
```

To explicitly select the full benchmark tests:

```bash
uv run --locked --group benchmarks pytest benchmarks/financial_dependency_suite
```
