# Runner mechanics

`config.py` resolves explicit paths relative to the checkout, pins both cache
configs to VGG snapshots, verifies all 749 schedule digests, and fingerprints
native executables, relevant Python/C++ sources, table/configs, architecture
YAML and capture/next-layer/meta contents. Input hashing is content based.
Startup hashes shared input files once, then each worker verifies its own
inputs before and after computing. Numeric implementation changes fail closed;
use a new output tree rather than replacing a pinned campaign.

`run.py` is the sole driver, guarded by a nonblocking output lock. It reserves
each worker's tier limit before spawning it. The sum plus driver allowance
cannot exceed the budget. Workers at/above the serial threshold exclude all
others. Finite OOM escalation chooses the next greater configured tier;
exhausted OOMs and tiers above budget are explicit terminal failures. Allocation
failures and SIGKILL are reported, including logs. Failed cases stay terminal
on resume; interrupted cases and recorded pending OOM retries resume at their
saved tier. Estimates are conservative scheduling hints (capture size +
512 bytes per estimated record + 2 GiB), not proof that an allocation fits.
`record_estimates.json` is copied from the existing read-only shard estimates.

Every worker starts a new session. Its generator and native children inherit
that group; no nested sessions are created. Signals, timeout or driver errors
terminate only recorded worker groups, including remaining descendants after a
leader exits. The renderer also has an owned session and timeout. No process
name scanning or unowned signal is used.

`pipeline.py` adapts the sample-0 demo pipeline locally. The requested index
reaches native `--sample-start`, analytic counts, following-layer density,
exact record CSV, WCTS/NoC identity, rows and fingerprint. Capture-slice hashes
in `sample_evidence.json` independently demonstrate sample selection. Shared
counts, NoC and energy-join functions remain the numerical implementation.
NoC receives explicit architecture YAML and eventsim paths; generation reads
manifest-relative schedules without solving or writing them.

Scratch has a deterministic per-output/case/sample directory and owner
fingerprint. WCTS and the native TMPDIR live there; there is never a campaign
trace accumulation pass. A valid existing generation may be reused after
interruption. NoC traffic, native cache CSVs, counts, generation metadata and
sample evidence are fsynced before atomic result replacement and directory
fsync. Only then is the WCTS deleted. Completed results validate saved artifact
digests on resume. A crash after the durable join does not require native
recomputation. Failure scratch is retained for diagnosis/retry; inspect disk
usage and do not bypass the free-space guard. Retained NoC CSVs also require
real durable-disk capacity at full scale.

`collect.py` creates per-sample CSVs and 120 whole-model groups with nominal
layer coverage, including six infeasible Prosperity schedules. Partial sums
are separate fields; complete-total fields stay null for missing layers.
`plot.py` produces an eight-page draft and PNGs from that checkpoint. Missing
bars are hatched and subsets explicit. Null energy terms follow the shared
join's lower-bound convention. There are no variance claims from one sample.

A barrier means all selected pair **attempts** are terminal, not necessarily
successful. Checkpoints record both counts. The sample-0 renderer must succeed
before the checkpoint is committed; artifact hashes are checked before any
later sample. Later samples also require their immediate predecessor. Changing
sample range is allowed; switching to a different selected case set is not.
The sample-0 CSV lives at `<output>/demo/results.csv`; subsequent CSVs live at
`<output>/samples/sample_NNNNN/results.csv`. This avoids a million-row in-memory
collector or repeated rewrites of the whole campaign.
