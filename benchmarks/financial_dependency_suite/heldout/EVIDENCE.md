# Preserved benchmark evidence

This catalog records why the selected historical artifacts are retained. Run names
alone do not identify the current implementation or establish finality. Saved
manifests, summaries, scores, reports and result bytes are preserved as recorded;
historical outcomes are not rescored, merged into final trials, or relabeled.
Absolute paths and original dirty-workspace fingerprints remain provenance.

## Final judge-replacement evidence

The final paired BGE and Cohere experiments are already tracked in
`results/bge-claude-vs-bge-omneum-20261008/` and
`results/cohere-claude-vs-cohere-omneum-20261008/`. Each retains its
`results.jsonl`, `manifest.json`, `summary.json`, `comparison.json` and `report.md`.
The full-pool Claude replacement is `results/claude-omneum-replacement-20261008/`.
The earlier Claude `paired` and `final` directories use a Claude shortlist and
are preserved as historical experiments, not as the current full-pool route.
Their report's references to the then-current route are historical statements.

## Selected historical artifacts

All directory names below are relative to `results/`.

| Directory | Preservation reason |
| --- | --- |
| `20261007T204230Z` | Complete independent 10-trial BGE/Omneum measurement (480 rows); distinct implementation fingerprint and outcomes. |
| `20261008T014713Z` | Historical Cohere pairing and shared provider responses required by test_latency_analysis.py and LATENCY_ANALYSIS.md. |
| `additive-bge-omneum-10trial-20261006` | Original BGE evidence, including 60 evaluation failures; retained separately from repairs. |
| `additive-bge-omneum-10trial-clean-20261006` | Composite historical evidence used by the exact-equivalence diagnostic. Both original and repair manifests remain separate; this is not a fresh homogeneous run. |
| `additive-bge-omneum-provenance-repair-20261006` | The 60 separately executed repair rows and their original manifest; preserves attribution of the composite evidence. |
| `bge-omneum-final-smoke-20261007` | Source candidate pools and previous selections referenced by the tied-maxima diagnostic. |
| `bge-omneum-tied-maxima-20261007` | Separate provider-backed tied-maxima measurement, distinct from the selection-only diagnostic and earlier smoke. |
| `claude-omneum-final-20261008` | Historical Claude-shortlist rerun, comparison and report. The report identifies the paired run as primary and discloses this additional rerun. |
| `claude-omneum-final-20261008-diagnostic` | False-consensus input/output replay and contemporaneous protected hashes referenced by the historical Claude report. |
| `claude-omneum-paired-20261008` | Original Claude-shortlist paired evidence referenced by REPORT.md and comparison.json in claude-omneum-final-20261008. |
| `claude-omneum-replacement-20261008` | Full-candidate-pool Omneum replacement with no Claude shortlist; matches the current anthropic_omneum regression contract. |
| `clean-validation-1trial-20261004T013826Z` | Required immutable Claude baseline for test_anthropic_omneum.py and test_bge_omneum.py; also records original Google truncation/refusal evidence. |
| `clean-validation-credits-1trial-20261004T180605Z` | Complete post-credit validation with distinct implementation fingerprint and recorded usage/latency coverage. |
| `clean-validation-f1f2-1trial-20261005T001500Z` | Complete later validation with a distinct implementation fingerprint and recorded outcomes; retained as historical evidence, not pooled with final trials. |
| `clean-validation-google8192-1trial-20261004T030546Z` | First larger-output-budget validation, retaining its provider-error outcome and original manifest. |
| `clean-validation-google8192-1trial-20261004T034451Z` | Separate credit-exhaustion evidence, with widespread provider failures; not evidence of answer-quality regression. |
| `diagnostic-exact-equivalence-selection-only-20261007` | Unique offline selection replay and attribution limits using the composite BGE run. |
| `diagnostic-smoke-1trial` | Original structured-output/provider-failure evidence discussed in DIAGNOSTIC_FIXES.md and OBSERVABILITY.md. |
| `diagnostic-tied-maxima-selection-only-20261007` | Unique offline selection diagnostic with saved pools, per-case changes and protected hashes. |

## Excluded and deferred work

The incomplete runs `20261007T212522Z` (3 rows), `final-10trial-20261005`
(436 rows), and `final-10trial-definitive-20261005` (54 rows) are left on disk
and outside this preservation commit. They have no completed summary and are
superseded by completed measurements. `.run.lock`, `Untitled`, caches and
runtime temporary files are excluded. A historical protected-hash inventory
may mention a lock file; that does not make the lock itself a research artifact.

The existing edits to the repository README, uv.lock, historical dataset
manifest, active-source manifest and source-contract README remain separate.
This commit does not reconcile historical checksums or imply that all integrity
checks against today's source tree pass. Historical manifests identify their
own run inputs and implementation. BRAID, benchmark algorithms, scoring and
frozen case/ground-truth files are unchanged by this preservation work.

## Exact preserved file inventory

The following inventory covers files added or modified by this preservation
commit, excluding this catalog itself. SHA-256 values identify the reviewed
bytes; they do not replace any historical manifest.

| File (repository-relative) | SHA-256 |
| --- | --- |
| `benchmarks/financial_dependency_suite/heldout/run_benchmark.py` | `66be55f1f63caa18ece0f6e137fe8524034e356ccb826f836a07c9104e46a19c` |
| `benchmarks/financial_dependency_suite/heldout/test_bge_omneum.py` | `68462d7866ebb9deb762c243c902ee1948e181e43215e654d190107493a8beae` |
| `benchmarks/financial_dependency_suite/heldout/test_anthropic_omneum.py` | `6ccac836a86e152faf977e03e2266c453c7755f2daefc4e93c098e838ed36b60` |
| `benchmarks/financial_dependency_suite/heldout/ADAPTER.md` | `404a5a60e8cbc7cb08f54e815015b691f449c49081063d635795b8486a4506b9` |
| `benchmarks/financial_dependency_suite/heldout/DIAGNOSTIC_FIXES.md` | `f87c1846fbe16fee6cbfb234433d95535860a7370acb97379fcced746e4c27ef` |
| `benchmarks/financial_dependency_suite/heldout/GOOGLE_BUDGET_VALIDATION.md` | `b9d6129f0f149ed829dd64c8235e0b063985b86a7189a2fe4f5193750ee4285b` |
| `benchmarks/financial_dependency_suite/heldout/OBSERVABILITY.md` | `e9fd7a4ae7ae09025cfd905f5a19382c9243032ea519c429a9f277027ba13f36` |
| `benchmarks/financial_dependency_suite/heldout/RESULTS.md` | `46fcf32e480ef34fac9d99996c19eec7e3b6f2659f381322ae8621ff2217046b` |
| `benchmarks/financial_dependency_suite/test_application_comparison.py` | `e4a871b7c7909976719392a0f8e0b80421e88bddfb96fc742581cf20e28dfc39` |
| `benchmarks/financial_dependency_suite/heldout/results/20261007T204230Z/manifest.json` | `6fe640f83f7f8d115a676e74b206e496f0b248b3f84e947de57c7488d1e01e04` |
| `benchmarks/financial_dependency_suite/heldout/results/20261007T204230Z/results.jsonl` | `a55bb65353da38b54de47385bd1f67fb63c2a31c8cbb9b7d8dc2112cf88239c6` |
| `benchmarks/financial_dependency_suite/heldout/results/20261007T204230Z/summary.json` | `df1f62a54969312fbc29487d8b590cf41d1ae81d6940c0a91147f292084eb3e1` |
| `benchmarks/financial_dependency_suite/heldout/results/20261008T014713Z/cohere_responses.jsonl` | `dc62bf5ae4a2e0b3363b7baf647aa70ea5205a03d85cc9790157ec81ea6c1482` |
| `benchmarks/financial_dependency_suite/heldout/results/20261008T014713Z/manifest.json` | `6976e172872315ec226445cb07a86571fd7fd78b3a9f30e2f4bccc27a1137cba` |
| `benchmarks/financial_dependency_suite/heldout/results/20261008T014713Z/results.jsonl` | `3e2b50be74094d863e22810bf1118d66ec5221a552970d36e99a1797f07bd762` |
| `benchmarks/financial_dependency_suite/heldout/results/20261008T014713Z/summary.json` | `5807c23c4e40f22f24d8b8e9814a3f1394dbee5f3760b4cef1b8aa9e78260df6` |
| `benchmarks/financial_dependency_suite/heldout/results/additive-bge-omneum-10trial-20261006/manifest.json` | `f116b4bdd50c0dd8f847422acde5510b2abdc4eb5ae0b7ac4b866118f0e0284c` |
| `benchmarks/financial_dependency_suite/heldout/results/additive-bge-omneum-10trial-20261006/results.jsonl` | `b20d042fd1333d173a44de244435f6bf1478261898a1a572d3ba9c198ae9b10d` |
| `benchmarks/financial_dependency_suite/heldout/results/additive-bge-omneum-10trial-20261006/summary.json` | `f9a9ce4f8dfac5b6a0b07411038521b5cfd0b7f4fea301c25d5da9e095d86cf9` |
| `benchmarks/financial_dependency_suite/heldout/results/additive-bge-omneum-10trial-clean-20261006/manifest.original.json` | `f116b4bdd50c0dd8f847422acde5510b2abdc4eb5ae0b7ac4b866118f0e0284c` |
| `benchmarks/financial_dependency_suite/heldout/results/additive-bge-omneum-10trial-clean-20261006/manifest.repair.json` | `01293e505303c8effa407bc851c7500ec89741413f3565d3aeb01f84d07eff2b` |
| `benchmarks/financial_dependency_suite/heldout/results/additive-bge-omneum-10trial-clean-20261006/results.jsonl` | `9dadb3d790cde3a49d342f07e65ebac58ae9196c2051745abcf923863d1c1448` |
| `benchmarks/financial_dependency_suite/heldout/results/additive-bge-omneum-provenance-repair-20261006/manifest.json` | `01293e505303c8effa407bc851c7500ec89741413f3565d3aeb01f84d07eff2b` |
| `benchmarks/financial_dependency_suite/heldout/results/additive-bge-omneum-provenance-repair-20261006/results.jsonl` | `51fdaa6635431a07ed70d562c239b84e52bcee52c58533e884ba89ec6b39ccd6` |
| `benchmarks/financial_dependency_suite/heldout/results/additive-bge-omneum-provenance-repair-20261006/summary.json` | `575611bf2e17727f587754ca7ba15bad693e02b80aa19511f2b70a272838c856` |
| `benchmarks/financial_dependency_suite/heldout/results/bge-omneum-final-smoke-20261007/manifest.json` | `d0ebe64c5fca34b74d154a5a2e4f2c44ee1e1ae030d8fba9e11125c28ad9649e` |
| `benchmarks/financial_dependency_suite/heldout/results/bge-omneum-final-smoke-20261007/results.jsonl` | `b2b098f51e356952dc0eb1ad677fb580bbb3cdcdd98e3c9e03932de4ee426695` |
| `benchmarks/financial_dependency_suite/heldout/results/bge-omneum-final-smoke-20261007/summary.json` | `19f4672e91fc8c2b485e2788a3ca5e155b7f9112d9264b2c1189792143c561a3` |
| `benchmarks/financial_dependency_suite/heldout/results/bge-omneum-tied-maxima-20261007/manifest.json` | `c5f3a167a734faa51f9566c930a030fa6ea15e9dd21d118aaf620abd267bc435` |
| `benchmarks/financial_dependency_suite/heldout/results/bge-omneum-tied-maxima-20261007/results.jsonl` | `4bba4175ba45bd75b86283c75ee59c837bc17439fdc8bf2b6bef6ddb10063b98` |
| `benchmarks/financial_dependency_suite/heldout/results/bge-omneum-tied-maxima-20261007/summary.json` | `72ccd16c76f95143930eacaac0b553ff976b974cb0db5b3592b735f64e6f8ac6` |
| `benchmarks/financial_dependency_suite/heldout/results/claude-omneum-final-20261008/REPORT.md` | `d26de52802759b09105be9f8ac197a4c58e702dc6fd2d46a9ca6ee3d80c29151` |
| `benchmarks/financial_dependency_suite/heldout/results/claude-omneum-final-20261008/comparison.json` | `3b9626206dd6b20428a1c3dcb0d29f2d95625bb786086e08197b756337ea5734` |
| `benchmarks/financial_dependency_suite/heldout/results/claude-omneum-final-20261008/manifest.json` | `254274660b17a3d537a2af64083b5747f66324d6679343bf45ebd575d7df795f` |
| `benchmarks/financial_dependency_suite/heldout/results/claude-omneum-final-20261008/results.jsonl` | `aef3d47f9c14d75272de5df23150bbec0a56b2bee9da59c0ec466c2fceaf0d00` |
| `benchmarks/financial_dependency_suite/heldout/results/claude-omneum-final-20261008/summary.json` | `2cb09d4ed25d4ae82ebab2916f8cb9287837ff2f8548f95d9a10600f44179426` |
| `benchmarks/financial_dependency_suite/heldout/results/claude-omneum-final-20261008-diagnostic/false_consensus_trace.json` | `1b929128132dd0be7d65e2ecb6693a3d1d250586971f4e55ee3ee70e2bb6c733` |
| `benchmarks/financial_dependency_suite/heldout/results/claude-omneum-final-20261008-diagnostic/protected_hashes.json` | `72743eac072b1e93b7a21a4ccad2d19d3c7650a8745929673b5b021fe61871e7` |
| `benchmarks/financial_dependency_suite/heldout/results/claude-omneum-paired-20261008/manifest.json` | `32fc5e7adc78bb29df58481bc1ab57bb8f25dbe9cf9b86fec2aa2cae1ee5334b` |
| `benchmarks/financial_dependency_suite/heldout/results/claude-omneum-paired-20261008/results.jsonl` | `82df8d587983d14114651e304fbeb0a86b06eac7925589fb04ee92832198736f` |
| `benchmarks/financial_dependency_suite/heldout/results/claude-omneum-paired-20261008/summary.json` | `69eb1864ad9b2c9f9252beb39f6007f2837042aefa27caeb16dc6f72e7e902ed` |
| `benchmarks/financial_dependency_suite/heldout/results/claude-omneum-replacement-20261008/manifest.json` | `bc0f39546392254142e8710c7809edd366160ebca32ab173a7a64c0d72097ed2` |
| `benchmarks/financial_dependency_suite/heldout/results/claude-omneum-replacement-20261008/results.jsonl` | `5384418f238df3a337e6e06b27b65a390cb81ea510e8910867a6de37acca853a` |
| `benchmarks/financial_dependency_suite/heldout/results/claude-omneum-replacement-20261008/summary.json` | `7a9afb3234c4258d6e980ef9d2d3ca3ee973bd685b80210ba8a95566b49415f3` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-1trial-20261004T013826Z/manifest.json` | `9cbd3b1ea2ff4e11fe0b0235e86a832246346e7be71b287918198ef2a759dd28` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-1trial-20261004T013826Z/results.jsonl` | `3965eeec69b9341dcb8bf79c632a5dcdba6b4b28155248ef13994c288569ac47` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-1trial-20261004T013826Z/summary.json` | `89759357d213e7d8e227f3523ab27c1961b43b38858e9ae531c37b01160853dc` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-credits-1trial-20261004T180605Z/manifest.json` | `c859f9dd22facf8f07cfb360aaacd0478aa089a4807e5cf9f86b24496e12c578` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-credits-1trial-20261004T180605Z/results.jsonl` | `987ba29e37ee03745f3df6053ecb870538113cd8e45efbea7e3dddcf7c339621` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-credits-1trial-20261004T180605Z/summary.json` | `d407230d02d3a943feb8eb93ef72418f58039366778fe0e66fa40e3ea8cdc4d2` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-f1f2-1trial-20261005T001500Z/manifest.json` | `dffc5231b712a797bead9b1d682c529b2d6c782b34cdda30b1ef7ed95fa5daa7` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-f1f2-1trial-20261005T001500Z/results.jsonl` | `eebee8878ec6026a453ac01d7121183123c361230bc8ed86e96ea14b49c71f66` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-f1f2-1trial-20261005T001500Z/summary.json` | `d52485a4ca65a0d2c039917b137c636649739ac752ea42b32e71c14cc0dfd5a9` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-google8192-1trial-20261004T030546Z/manifest.json` | `de2d98b8527a13d66c9fb703ea309148f6cfd610352c615fbe25d92b32c2ea57` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-google8192-1trial-20261004T030546Z/results.jsonl` | `aa5d6065a242d36e22e1edbd765f8743c8d4e45ebb621c78f8ca099832718062` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-google8192-1trial-20261004T030546Z/summary.json` | `d90f195bba81e467630780c8cc92f228f6fa55d47becfea8573ee56fa449acb5` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-google8192-1trial-20261004T034451Z/manifest.json` | `1c01af257f8c9ea79d2ca0d763b689a340e366781de219f404ec4fd7e1db33b0` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-google8192-1trial-20261004T034451Z/results.jsonl` | `ca16429c6fe42315e02f82aef6b3adadd346ac953904bf58dd6e265e8503a5bb` |
| `benchmarks/financial_dependency_suite/heldout/results/clean-validation-google8192-1trial-20261004T034451Z/summary.json` | `c6117035f6a90ae212cdf5c2abeb27d96345e36d82b2217a018db3f800aacb3c` |
| `benchmarks/financial_dependency_suite/heldout/results/diagnostic-exact-equivalence-selection-only-20261007/selection_only_diagnostic.json` | `5a8bf6f8ea312b006a5f9d891e49f5707d82c93f9f8fd7a486b8dda434602cbe` |
| `benchmarks/financial_dependency_suite/heldout/results/diagnostic-smoke-1trial/manifest.json` | `f1f7a33c4d16ce6877bb34f5977e1a82febaf9270f4f15e090c840cae386bfbc` |
| `benchmarks/financial_dependency_suite/heldout/results/diagnostic-smoke-1trial/results.jsonl` | `b3035b7b7fcc9ea944f7c9ee8b9db9f4f602fd42c17c3e32341490d9ea8533b3` |
| `benchmarks/financial_dependency_suite/heldout/results/diagnostic-smoke-1trial/summary.json` | `ea1873143227886d683f3364a0860545fb993d9dd5c23a8df1b20b03a2759c32` |
| `benchmarks/financial_dependency_suite/heldout/results/diagnostic-tied-maxima-selection-only-20261007/selection_only_diagnostic.json` | `545a3fc79f838074d13dc61f9f443e126fd6b35a428958285cf17a9a38e4df31` |
