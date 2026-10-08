# Source contracts

`../dataset_manifest.json` remains the unchanged historical contract. Its 56
entries are verified with SHA-256 over file bytes. The superseded `methods.py`
and `runner.py` entries refer to `v1/methods.py.txt` and `v1/runner.py.txt` here;
all other entries retain their original paths. The text snapshots are not
imported or executed.

Both snapshots were recovered without modification from Git commit
`09fed729d4079abe77e3956376622dd127c679f1`. Their byte hashes exactly match the
historical manifest. This preserves the historical source contract without
maintaining a second runtime implementation.

`../source_manifest_v2.json` separately pins the two active files, `methods.py`
and `runner.py`, after the Omneum naming cleanup. It does not claim to pin the
entire SDK or benchmark implementation. `test_current_sources` verifies these
files directly; neither integrity test transforms bytes before hashing.

## Pre-existing runner mismatch

The historical runner hash is
`e019c66539d9e367415a6cca4dec24b827abc4a4197e58d72b789ea95c2360fc`.
Before the naming cleanup, the working runner hash was
`4a6c64be88e848a116cfd24fa9cfce725180a0325f9bdbe1a1b0234570f96b7b`.

The difference added the `bge_omneum` route and its reliability-filter import,
and supplied the missing `case.question` argument to the existing reranking
selector. These changes predate the naming cleanup. The v2 runner retains the missing
query-argument fix and the Omneum method name. The additive `bge_omneum` route
and reliability filter are separate working-tree changes outside this staged
contract. The historical hash is not overwritten or represented as matching
the active runner.
