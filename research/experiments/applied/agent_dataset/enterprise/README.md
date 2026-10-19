# Enterprise retrieval and context selection

The LangGraph workflow retrieves return-policy facts from two local documents,
an in-memory SQLite database, and a captured vendor API response. A research
agent derives further observations from document and vendor results. Simulated
relationship labels are retained for analysis; retrieval and evaluation do not
use them.

Three timestamps remain distinct: `retrieved_at` records resource access,
`observed_at` records the assertion observation, and `source_modified_at` records
publication or update time. Only `source_modified_at` informs temporal dependency.

Run from the repository root:

```sh
uv run --locked --group langgraph python -m research.experiments.applied.agent_dataset.enterprise
uv run --locked --group langgraph python -m research.experiments.applied.agent_dataset.enterprise.context_selection --token-budget 100
```

Context selection maps retrieved chunks to normalized claim identities and uses
the production evaluation with `reconstruct_context()`. The four strategies are
retrieval order, maximum support, mean support, and coverage-aware support. They
share the same token counter and budget, including rendered chunk headers.
Duplicate chunks do not create new source-to-claim observations.

Output records selected chunks, scores, reconstructed text, coverage, token usage,
dependency telemetry, configuration, and code/fixture hashes. `--output PATH`
writes a new file and refuses to overwrite an existing one. The saved
`results/context-selection-v1.json` is an immutable historical baseline; regression
tests account for its original reconstruction ordering. Selection alone does not
establish an improvement in generated-answer accuracy.

The [consuming-agent experiment](AGENT_EXPERIMENT.md) adds two real local LLM
requests and an eligibility tool after retrieval, comparing baseline context,
Omneum selection, and the same selection ranked by utility.
