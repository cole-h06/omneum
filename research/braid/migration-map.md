# BRAID integration

Omneum's existing production implementation is authoritative. Its three algorithm
modules were neither moved nor changed by this import. Specification revisions,
production conformance replacement and Operator retirement are deferred.

Paths below are relative to the original BRAID root and `research/braid/`:

| Original | Consolidated |
|---|---|
| `experiments/` | `experiments/`, with production adapters and module entry points |
| `spec/` | `spec/`, unchanged historical contract |
| `research/` | `research/`, unchanged diagnostics and figures |
| `tests/` | `history/tests/`, byte-preserved fixtures and tests |
| `experiments/applied/agent_dataset/tests/` | `history/agent_dataset_tests/` |
| `experiments/applied/agent_dataset/workflow/graph.py` | `history/adapters/graph.py` |
| `experiments/applied/agent_dataset/workflow/hybrid_dependency.py` | `history/adapters/hybrid_dependency.py` |
| `pyproject.toml`, `requirements.txt` | `history/metadata/` |
| `CITATION.cff`, `LICENSE` | Original relative paths, unchanged |
| `src/braid/` | Not included; Omneum provides the mathematical implementation |

The applied adapter maps synthetic source labels to deterministic scoped UUID
identities. Claim identities retain entity namespace, entity, attribute and value;
source relationships, missingness and controlled times remain explicit. Original
retrieval metadata stays with the research observations. Raw document text is
processed by the existing research retrieval code, not by mathematical inference.

Claim-to-chunk mapping and client-side context reconstruction use
`omneum/context_selection.py`. The enterprise experiment retains retrieval IDs,
record IDs, hashes and parent observation IDs alongside the evaluated claims.
