# Gemini comparison reproducibility

The sole active result directory is `../../results/bge-google-low-vs-bge-omneum-20261008/`. Its manifest retains the original run identity, low-thinking selection configuration, original checkpoint contract, exact source artifact hashes, and the separate recovery contract. `results.jsonl` contains exactly 24 cases × 10 trials × 2 configurations.

Offline verification makes no provider calls:

```sh
.venv/bin/python -m benchmarks.context_evaluation.heldout.verify_gemini_recovery
.venv/bin/python -m benchmarks.context_evaluation.heldout.build_dashboard_summary --check
.venv/bin/python tools/run_context_evaluation_tests.py -q
```

The verifier checks final artifact hashes, frozen inputs, schedule uniqueness, all original selection projections, unchanged historical Omneum records, unchanged 101 successful Gemini-arm records, original prompt/model/cap request hashes, recovered response provenance, full generation usage, timing sums, raw/summary agreement, complete review coverage, and published metrics.

The source failed replay has SHA-256 `863f4ee76dbe1e557941c96f77e0676e4888a6ac58059ca5728a18b99f8d04dc`; final recovered results have SHA-256 `111b1abbcb7ef0f9cc6e567babe901bbe777e524fbdbfb93af4a2bb3c46130d0`. Source artifacts and exact recovery code/journal bytes are preserved in the existing `omneum-private-archives` collection. The manifest records their hashes; the private archive is not required to recompute final public metrics.

Paid execution used the separately tested `recover_gemini_generations` path with `--execute-paid --resume --retry-failed`. SDK retries were disabled, completed outputs were skipped, and uncertain outcomes blocked continuation. No selectors were imported by the generator path. The immutable execution code is archived under its recorded hash. Do not recreate the paid experiment to reproduce published metrics: use the saved authoritative records.

E2E medians combine original selection and later generation measurements. Historical Omneum timings remain historical. Refusals are measured and adjudicated explicitly; missing original judge reasoning telemetry remains unavailable. Generator cost uses the frozen benchmark rates and is not a provider invoice.
