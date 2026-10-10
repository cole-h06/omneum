
# Dashboard Summary

Generated results for 12 configurations across six benchmark experiments.

| File | Purpose |
|---|---|
| [`dashboard_summary.json`](dashboard_summary.json) | Published metrics and configuration metadata |
| [`dashboard_summary.schema.json`](dashboard_summary.schema.json) | JSON schema (v2.0.0) |
| [`publication_manifest_v1.json`](../publication_manifest_v1.json) | Artifact hashes and publication provenance |

## Regenerate

```bash
python -m benchmarks.context_evaluation.heldout.build_dashboard_summary
```

Verify the committed export without modifying files:

```bash
python -m benchmarks.context_evaluation.heldout.build_dashboard_summary --check
```

Regeneration uses recorded artifacts and makes no model API calls.

See [`EVIDENCE.md`](EVIDENCE.md) for supporting run artifacts.