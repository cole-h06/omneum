
# Source and Checkpoint Contracts

Source manifests, historical snapshots, and checkpoint fingerprints for the [Cross-Domain Context Curation Benchmark](../../../README.md).

## Source Manifests

| Contract | Scope |
|---|---|
| [`dataset_manifest.json`](../dataset_manifest.json) | Original 56-entry dataset and source SHA-256 contract |
| [`source_recovery_manifest_v1.json`](../source_recovery_manifest_v1.json) | Recovered loader and schema Git objects and file hashes |
| [`source_manifest_v2.json`](../source_manifest_v2.json) | Pre-migration methods and runner sources |
| `source_manifest_v3.json` | Renamed benchmark runtime sources |
| [`source_manifest_v4.json`](../source_manifest_v4.json) | Methods, runner, loader, and schema |
| `source_manifest_v5.json` | Publication-era public execution and verification tooling |
| [`source_manifest_canonical_v1.json`](../source_manifest_canonical_v1.json) | Recorded multi-claim source contract |
| `publication_manifest_v1.json` | Publication-era source contract |

The original dataset manifest retains 56 entries. Five superseded source entries resolve to archived snapshots:

```text
v1/
├── README.md.txt
├── methods.py.txt
├── runner.py.txt
├── loader.py.txt
└── schema.py.txt
```

All remaining entries retain their original dataset-relative paths. Archived `.txt` files are excluded from runtime imports.

The original dataset contract, source manifests v2–v4, and historical checkpoint contracts remain unchanged.

### Revision History

The current v5 source manifest and v1 publication manifest include `revision_history` entries for reviewed release changes.

Each entry records:

- Previous contract hash
- Previous and current SHA-256 hashes for modified files
- Reason for each modification

Historical manifest entries are retained.

## Recovered Sources

| Source | Git object | Recovery record |
|---|---|---|
| Original `loader.py` | Blob `f7f0af6f37f653dea3990cd611e28d3a24422c8b` | [`source_recovery_manifest_v1.json`](../source_recovery_manifest_v1.json) |
| Original `schema.py` | Commit `320ec4c1d340` | [`source_recovery_manifest_v1.json`](../source_recovery_manifest_v1.json) |

The recovered loader blob has no attributed reachable commit. Both recovered files are verified by recorded SHA-256 hashes, without requiring the original Git objects in a fresh checkout.

## Checkpoint Fingerprints

| Version | Location | Status |
|---|---|---|
| v1 | [`checkpoints/v1/checkpoint.py.txt`](checkpoints/v1/checkpoint.py.txt) | Historical fingerprint definition |
| v2 | [`checkpoints/v2/checkpoint.py.txt`](checkpoints/v2/checkpoint.py.txt) | Historical fingerprint definition |
| v3 | Current benchmark checkpoint implementation | Active execution contract |

Checkpoint v3 uses the `context-evaluation-v3` fingerprint scope.

The fingerprint covers public benchmark runtime Python, SDK Python, Rust sources, and dependency lockfiles. Each input is framed using its repository-relative path and file bytes:

```text
<relative-path>\0<file-bytes>\0
```

A change to the covered sources or execution contract invalidates resume compatibility. Existing run fingerprints are not rewritten.

Public manifest projections provide artifact verification and do not function as resumable checkpoints.

## Historical Execution Snapshots

Three retained content-addressed snapshots preserve the original Google/OpenAI analysis scripts and selector.

Historical paid executions used dirty working trees. The retained snapshots establish the identity of their archived files but do not constitute a complete source snapshot for every historical execution.

Other development snapshots and experimental contracts remain in the private archive.

## Publication Archive

Publication-era source files are retained at:

```text
publication-v1/<original-sha256>.txt
```

Each file was recovered from its Git blob and verified against the unchanged publication manifest. The archived files are not imported by the benchmark runtime.

Historical `scoring.py` is retained under [`v1/`](v1/).

[`source_manifest_canonical_v1.json`](../source_manifest_canonical_v1.json) records the multi-claim source contract independently of the original [`source_manifest_v4.json`](../source_manifest_v4.json). Its exact source bytes are preserved under [`canonical-v1/`](canonical-v1/), including the runner before later budget diagnostics were added. The recorded hashes are unchanged.

## Execution Snapshots

[`execution-v1/sources.json`](execution-v1/sources.json) identifies preserved execution-time source bytes. The original structural trace is retained with its original SHA-256 in [`execution-v1/trace.json`](execution-v1/trace.json). Current runners accept `--trace` and default to that preserved copy rather than a machine-local temporary path.

Analysis scripts require a new output directory and leave completed execution artifacts unchanged. The final recovery analysis accepts `--input`, `--output`, and `--trace`; it reads the saved reliability audit and patch without executing graph inference.

## References

- [Dataset](../DATASET.md)
- [Dataset Manifest](../dataset_manifest.json)
- [Source Recovery Manifest](../source_recovery_manifest_v1.json)
- [Canonical Source Manifest](../source_manifest_canonical_v1.json)


## Offline Analysis Scope

The v2 recovery experiment's original `protected_inputs.json` is an execution-time
workspace immutability inventory, not a list of analysis dependencies. All 182
entries and their original hashes remain unchanged. Saved-result analysis verifies
all 179 published entries. Three unpublished non-inputs (the old question-aware
`selections.jsonl`, `results.jsonl`, and `local/omneum.db`) are not required for
analysis: it reads saved recovery/prior selections, timings, canonical cases,
ground truth, alternatives and the saved reliability audit instead. The preserved
structural trace has its own unchanged hash and is not a replacement for either
missing log. Recreating the logs or the private database is unnecessary and would
not establish their historical hashes.

This public analysis scope is authorized only for the exact original v2 protection
manifest SHA-256 `dce8e3c32998df4122f73e7f89ea86b1b8b4437624cf9b0e9582fc59ecb4827f`.
If any of the three non-inputs is supplied, its original hash is still checked.
Unknown manifests and new experiment execution retain full verification. New
analysis validation output identifies unpublished non-inputs explicitly; historical
validation files are not rewritten. This does not claim to reproduce the complete
historical execution environment.

The historical selection-and-answer README is preserved verbatim from commit
`7e42c1d` (Git blob `2066f7f597314da86d63167e008dbfb1e1705477`) as
[`publication-v1/5af5e9b5118adf8258eef864065139fc785bb3b6d6695d1c599b6f335cc8448b.txt`](publication-v1/5af5e9b5118adf8258eef864065139fc785bb3b6d6695d1c599b6f335cc8448b.txt).
Dashboard tests verify its SHA-256 and compare published tables to frozen dashboard
and raw-run metrics, including generator-only tokens and costs. The current root
README describes a different, selection-only benchmark.
