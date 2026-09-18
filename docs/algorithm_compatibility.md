# Normative algorithm compatibility

Omneum independently implements the algorithm defined by the upstream
specification/reference/frozen fixtures. It never imports the upstream Python
reference to produce scores or generate expected outputs.

`omneum/algorithm_compatibility.json` is the shipped compatibility pin:
- schema version 1;
- algorithm identity `braid`, version `braid-1.0.0`;
- accepted Git revision `92e981234070da566e9186015ace4a41cbebc644`;
- fixture revision 1;
- repository and manifest location.

The original manifest has no separate identity field, so the pin supplies that
identity explicitly. Future manifests may declare it and must then match.
Production protocol labels (`omneum-v2` and `dependency-estimator-v4`) remain
unchanged for compatibility. They are implementation labels, not normative
algorithm revision identifiers.

## Independent conformance

```sh
python -m omneum.conformance --spec-checkout ../braid
ALGORITHM_SPEC_CHECKOUT=../braid python -m pytest tests/test_algorithm_compatibility.py
```

The consumer reads regular files from the exact pinned Git commit, ignoring
dirty checkout contents. It validates manifest/fixture revisions and required
fixture groups. It compares production propagation, signal fusion, provenance
estimation, global/induced clustering, exact maxima, contributions, convergence
and expected nonconvergence. Numeric tolerances come from the committed manifest.
Missing specifications or unsupported fixture formats fail rather than skip.

The current record-fixture format uses the same explicit two-hour temporal
window as the upstream fixture adapter. It is not a universally calibrated
algorithm default. Synthetic identity mapping changes labels only.

Conformance imports only Omneum production modules. No upstream programs,
configuration commands or reference implementation are executed. Expected
values remain upstream-owned. Local downstream vectors remain regression tests,
not replacements for normative fixtures.

The CI Python matrix fetches the pinned specification commit and runs
conformance before the full suite. Wheels and daemon artifacts depend on that
test job. Configure repository branch protection to require its checks;
a workflow file cannot enforce branch protection itself. The pinned upstream
commit must be reachable in CI; this change does not push or publish it.

## Accepted upgrades

Follow the operator's explicit accepted-revision process. Candidate checks can
use `--pin /private/path/candidate.json` without changing shipped metadata.
Inspect upstream spec/reference/fixture changes, implement downstream, add
regressions, pass candidate conformance and applicable tests, then advance the
shipped pin and rerun checks. Unknown semantics stop the affected work.
Acceptance is a human decision, not inferred from successful tests or a branch
name. Tools never advance pins automatically.

Algorithm identity is data in compatibility metadata. A future rename changes
that metadata and bounded repository/namespace references, not this protocol.
Do not rewrite historical event provenance.

The JSON pin and event schema ship with wheels/source distributions. A checked
out but uncommitted implementation must be labeled dirty; the algorithm pin is
not proof that arbitrary local modifications conform.
