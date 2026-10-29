# Historical Dashboard Summary

The dashboard export contains 12 configurations from six historical selection-and-answer experiments. It does not contain the current Cross-Domain Context Curation Benchmark results.

- [Historical export](dashboard_summary.json)
- [Historical schema](dashboard_summary.schema.json)
- [Historical publication contract](../publication_manifest_v1.json)
- [Current evaluation evidence](EVIDENCE.md)

Verify the immutable historical export without model calls or artifact writes:

```bash
python -m benchmarks.context_selection.synthetic.build_dashboard_summary --check
```

The original export and publication-era source bytes are preserved in [the contracts archive](contracts/README.md). Current selection results come from the competitor execution and final recovery evaluation identified in the evidence documentation.
