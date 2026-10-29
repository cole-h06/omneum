
# Benchmark Evidence

Six experiments supporting 12 published configurations. Each run retains its trial records and summaries.

| Run | Configurations | Additional evidence |
|---|---|---|
| [bge-omneum-tied-maxima-20261007](results/bge-omneum-tied-maxima-20261007/) | `bge`, `bge_omneum` | [Tied-maxima diagnostic](results/diagnostic-tied-maxima-selection-only-20261007/selection_only_diagnostic.public-v1.json) |
| [20261008T014713Z](results/20261008T014713Z/) | `cohere`, `cohere_omneum` | [Shared responses](results/20261008T014713Z/cohere_responses.jsonl) |
| [bge-claude-vs-bge-omneum-20261008](results/bge-claude-vs-bge-omneum-20261008/) | `bge_anthropic`, `bge_omneum` | [Semantic review](results/bge-claude-vs-bge-omneum-20261008/comparison.json) |
| [bge-openai-vs-bge-omneum-20261008](results/bge-openai-vs-bge-omneum-20261008/) | `bge_openai`, `bge_omneum` | [Answer audit](analysis/bge-openai-vs-bge-omneum-20261008/) |
| [bge-google-low-vs-bge-omneum-20261008](results/bge-google-low-vs-bge-omneum-20261008/) | `bge_google`, `bge_omneum` | [Answer audit](analysis/bge-google-low-vs-bge-omneum-20261008/) |
| [cohere-claude-vs-cohere-omneum-20261008](results/cohere-claude-vs-cohere-omneum-20261008/) | `cohere_anthropic`, `cohere_omneum` | [Semantic review](results/cohere-claude-vs-cohere-omneum-20261008/comparison.json) |

## Verification

[`publication_manifest_v1.json`](../publication_manifest_v1.json) records artifact hashes and published metrics.

BGE/Cohere baseline comparisons use recorded substring accuracy. LLM judge comparisons use their recorded semantic reviews. Missing labels and telemetry remain unavailable.

The tied-maxima diagnostic records 24 selected-source sets and their agreement with later BGE judge runs.

## References

- [Methodology](../../README.md)
- [Latency analysis](LATENCY_ANALYSIS.md)
- [Publication manifest](../publication_manifest_v1.json)

Historical run commands and paths are preserved in the result artifacts. Use the current methodology for reproduction.