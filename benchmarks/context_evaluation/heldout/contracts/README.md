# Source and checkpoint contracts

The unchanged `../dataset_manifest.json` pins 56 original artifacts. Five
superseded entries use `v1/{README.md,methods.py,runner.py,loader.py,schema.py}.txt`;
all other entries retain their dataset-relative location. These files are inert
snapshots, never a second runtime implementation.

`../source_manifest_v2.json` pins pre-migration methods/runner bytes in `v2/`.
Versions 3 and 4 record the renamed runtime sources; v4 pins methods, runner,
loader and schema. Version 5 additionally pins current public execution and
verification tooling. Historical manifests are unchanged.

The current v5 source and v1 publication contracts retain a `revision_history`
for reviewed release edits. Each entry preserves the previous contract hash and
the previous/current hash and reason for each changed file. Original dataset,
source v2–v4 and checkpoint contracts remain unchanged.

The original loader was recovered from Git blob
`f7f0af6f37f653dea3990cd611e28d3a24422c8b`, without an attributed reachable
commit. The schema was recovered from commit `320ec4c1d340`.
`../source_recovery_manifest_v1.json` records the objects and exact hashes.
Fresh checkouts verify the snapshot bytes without requiring those Git objects.

`checkpoints/v1/checkpoint.py.txt` and `checkpoints/v2/checkpoint.py.txt` retain
previous fingerprint definitions. New execution uses checkpoint v3 and the
`context-evaluation-v3` scope: public benchmark runtime Python, SDK Python,
Rust, and dependency locks, framed by repository-relative name/NUL/bytes/NUL.
Changing code or the execution contract rejects resume; it never updates a saved
run's fingerprint. Public manifest projections are verification evidence, not
resumable checkpoints.

The three retained content-addressed historical snapshots document the original
Google/OpenAI analysis scripts and selector. Other development snapshots and
experimental contracts remain in the private archive. Historical paid runs had
dirty checkouts, so these snapshots do not establish a complete executed-source
snapshot for every run.
