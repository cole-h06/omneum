# Canonical multi-claim compatibility

The original `cases/` files and frozen results remain unchanged. The corrected
canonical dataset has one `claims` array per candidate. Source ID, raw passage,
source reference, original provenance, question, budgets and labels are retained.

The existing inference contract already accepts multiple observations per source
(`AssertionTriple(source_id, attribute_id, claim_id)`); no inference/selection
change is required. Each fact becomes an existing SDK `Observation`. The first
fact retains the original observation ID; added facts have deterministic IDs.
Parent references to original IDs therefore remain valid.

The smallest benchmark boundary change is an optional tuple of structured claims
on `CandidateSpec`, support for the alternative JSON shape in `load_case`, and
flattening in the existing SDK adapter. Legacy single-claim candidates retain
exactly their prior fields and observations. A candidate must use either the four
legacy claim fields or `claims`, never both. Multi-claim candidates do not expose
a misleading legacy primary-claim projection.

`prepare_benchmark.mapped_chunks` and `query_benchmark.inputs` must group flattened
observations by their explicit candidate/occurrence association, not zip one
observation with each passage. This preserves one retrieval candidate/chunk per
original passage. Claim text relevance, when requested by a future benchmark,
uses each fact's own existing fields; no relevance formula is changed.

Historical analysis scripts which assume one observation per candidate are not
being broadly rewritten. They remain compatible with the original frozen cases;
they are not a supported entry point for the corrected canonical format. No full
benchmark is being run or relabeled by this change.

Dataset `claim_id` values are semantic SHA-256 catalog IDs. SDK claim tokens are
computed by the existing namespace-preserving adapter, exactly as for legacy
cases. Catalog IDs and evidence are metadata, not inference inputs or extra
independent observations. Duplicate source/claim occurrences are rejected in this
canonical dataset, rather than inventing independent support.

The copied retrieval JSON files are immutable score/rank caches. Their embedded
legacy claim annotations are historical; `cases/*/case.json` is authoritative for
canonical claims. Do not interpret cached claim IDs as corrected annotations.

Release hardening added multi-claim joins to active selection/report helpers,
including `controlled_chunks`, `evidence_metrics`, query diagnostics and saved
record readers. Saved legacy `_value_bytes` records remain readable. Historical
single-claim inputs and archived scoring policies remain separate controls.
The canonical SDK smoke exercises seven arms and multiple claims without calling
extraction/normalization; it does not measure their semantic quality or downstream
answer accuracy. See `../../release_readiness/2026-10-25/report.md` for validation.
