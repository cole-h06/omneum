# Normative algorithm compatibility

The accepted upstream BRAID specification and frozen fixtures define the
algorithm implemented independently by Omneum. Conformance uses Omneum's
production modules and upstream-owned expected values; it never executes
upstream programs, configuration commands or the Python reference implementation.
Local regression vectors supplement rather than replace the normative fixtures.

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

The CI Python matrix fetches the pinned specification commit and runs
conformance before the full suite. Wheels and daemon artifacts depend on that
test job. Configure repository branch protection to require its checks;
a workflow file cannot enforce branch protection itself. The pinned upstream
commit must be reachable in CI.

## Accepted upgrades

Candidate checks can use `--pin /private/path/candidate.json` without changing
shipped metadata. To upgrade the accepted revision:

1. Review upstream specification, reference and fixture changes. Resolve unknown
   semantics before implementing the affected behavior.
2. Update Omneum, add regressions, and pass candidate conformance and applicable tests.
3. Obtain explicit human acceptance through the operator's accepted-revision process.
4. Advance the shipped pin and rerun checks.

Passing tests or using a particular branch does not constitute acceptance.
Tools never advance pins automatically.

Algorithm renames update compatibility metadata and the relevant repository or
namespace references without changing the protocol or historical event provenance.

The JSON pin and event schema ship with wheels/source distributions. A checked
out but uncommitted implementation must be labeled dirty; the algorithm pin is
not proof that arbitrary local modifications conform.
