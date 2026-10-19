# Historical BRAID contract

These fixtures, tests, adapters and package metadata retain BRAID's older research
contract. They target the old reference algorithm,
not Omneum's production semantics, and are not part of the current test suite.
Do not add the old engine to the production package or use its scores as
production expectations.

See [the migration record](../migration-map.md) for original paths.
The active adapter regressions are `tests/test_braid_research.py` at the Omneum root.
