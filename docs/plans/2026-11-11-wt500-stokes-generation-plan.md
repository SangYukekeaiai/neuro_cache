# WT500 weight-trace generation on Stokes: execution plan

Status: **plan only, awaiting review. Nothing executed.**

Scope: generate the campaign's weight traces for 5 architectures x 151
scheduled layers x 500 samples on the Stokes cluster. Step 3's five
walkthroughs (`zoo/wt500_fig3cfg/walkthroughs/`) are the input; their caveats
and cost measurements drive the ordering, the sharding and the preflight.

## 0. User directives

These are binding and shape S2, S3 and S5.

> **1. Run order: fastest combos first, slowest last** (gustavsnn C01 and
> spinalflow C01 at the very end; use the record-count ranking and per-arch
> knowledge from the walkthroughs to define "fastest" - records, not tiles).

> **2. Skip stride-2 layers.**

> **3. Schedules must come from MODE-SWEEPING solves, NOT BASE mode.**

Consequences of each, stated once here and applied throughout:

**Directive 1** is a record-count ordering, not a tile-count one. The two rank
the architectures differently, which is the whole reason the directive says
"records, not tiles": gustavsnn has the largest tile count in the campaign
(2,097,152 on C01's first layer) *and* the largest record count, while
prosperity has the second-largest tile count (589,824) and the **smallest**
heavy-layer record count (about 3.9 million). Sharding on tiles would put
prosperity near the end and gustavsnn too early.

**Directive 2 needs no flag and no filter.** The trace loader already excludes
non-3x3 and non-stride-1 convolutions, so the six stride-2 layers (classes S4
and S5 in `layer_dim_coverage.md`: B09/`loas_resnet19` L1, L8, L15 and L3, L10,
L17) never enter the scheduled set for any architecture. That is why the
campaign's layer count is 151 and not 157. The plan asserts this in S3's
verification rather than implementing it.

**Directive 3 invalidates the existing schedule cache for generation.** The
DeltaAI cache was produced by `gen_inputs.py`, which invokes
`python -m lays.scheduler solve` with no mode flag; `solve_schedule`'s
`traffic_mode` defaults to BASE and `gen_inputs.py:262` stamps `"mode": "base"`.
The sweep path is `lays.scheduler.artifact.solve_and_cache_schedule`, which
solves every traffic mode and keeps the best by the CoSA reference score. So
**all** (arch, layer) schedules are re-solved in S2, not just prosperity's and
gustavsnn's - though those two needed re-solves anyway, since their mapspace
hashes changed.

The consequence to record for whoever reads the traces: **tick ordering and
frame grouping in the final traces follow the sweep-winner schedules, not the
BASE ones.** A sweep winner can differ from BASE in its DRAM/NoC split and
therefore in how tiles group into frames - measured on prosperity's A08
classifier, where repeated solves gave 10x1, 1x10 and 5x2 for the same layer,
all 10 frames and 160 tiles. Record *coordinates* are mode-invariant; their
grouping and tick numbering are not. Any cross-run comparison must come from
the same schedule cache.

## Preflight (before S1)

- **Rebuild all five native binaries on Stokes.** `make build` covers only
  LoAS among the five generators, so the other four are built per directory.
  One `make -C` takes a single directory, so a brace expansion does **not**
  work - `make -C .../{ptb,spinalflow,...}` enters `ptb` and then treats the
  remaining paths as goals, failing with `No rule to make target`. Use a loop:

  ```
  make build   # includes loas
  for a in ptb spinalflow prosperity gustavsnn; do
      make -C src/lays/weight_trace_gen/$a || exit 1
  done
  ```

  The rule is rebuild-all, and the reason is worth stating: a timestamp
  comparison is the **wrong** test. All five generator headers were modified in
  the same commit, so mtime flags all five, while only gustavsnn's parser had
  actually gone out of step with its packer. Rebuild everything and do not
  reason about which needs it.
- **Why this is not optional.** A stale `gustavgen` does not fail loudly at the
  campaign's chunk size. It writes **empty traces**: the wire format gained a
  wave-width header field, the older parser shifts every later read by one
  integer, the first tile's output-row count receives its offset of 0, and zero
  rows gives zero records. At `SAMPLE_CHUNK_SIZE = 10` (`cli.py:70`) the
  garbage sample index lands inside the requested range and nothing raises. A
  500-sample shard of empty traces is the worst available outcome, and nothing
  in the pipeline would catch it before delivery. See S6.
- **No systemd user bus on Stokes**, so long jobs use `setsid` alone rather
  than `systemd-run --user --scope`. A job killed by the kernel OOM killer can
  take its process scope with it, which matters for the heavy shards in S5.
- Confirm the Python environment (the fig2 provenance records
  `~/.venvs/neuro_cache_wcache/bin/python`; name to re-confirm) and the repo
  revision.

---

## S1. Storage

**Goal:** a filesystem location on Stokes that can hold the traces, chosen
before anything is transferred or generated.

**Tasks.**

1. Identify candidate locations and classify each as scratch or project space,
   with its retention policy. The campaign's prior Stokes root is
   `/lustre/fs1/home/ya867177`; the fig2 campaign used
   `/lustre/fs1/home/ya867177/data/input_trace_delta/` for inputs.
2. Check quota and free space on each: `lfs quota -h -u $USER /lustre/fs1`,
   `df -h`, and the per-directory usage with `du -sh`.
3. Size the requirement from both sides:
   - **Inputs**: about **33 GB** total for the 8 captures (measured:
     A07 20 GB, C01/dvs128 3.7 GB, A08 2.8 GB, C01/cifar10_dvs 2.4 GB,
     A04 1.7 GB, A02 1.4 GB, B09/resnet19 954 MB, B09/vgg16 349 MB).
   - **Outputs**: driven by record counts and therefore not yet known for the
     whole campaign - this is one of S3's deliverables. The anchor available
     now: gustavsnn's heaviest layer computes to about 2.9 GB of stream for
     **one** sample, so a single (arch, layer) pair at 500 samples is of order
     a terabyte if stored uncompressed. The harness compresses (`harness.py`
     writes through a compressor), and the real figure needs S3's estimates
     plus a measured compression ratio from S5's demo runs.
4. Decide whether output lands in scratch with periodic migration, or directly
   in project space, based on 2 and 3.

**Needed from the user (open since the handoff).**

- The **SSH alias** for Stokes.
- The **node-allocation helper** name, remembered as "ncode" or "cnode"
  (`which ncode cnode`, `ls ~/local/bin`, or cluster docs will settle it).
- Whether a project allocation exists beyond the home lustre path, and its
  quota.

**Verification criterion.** A written location with measured free space of at
least 3x the S3 output estimate, its retention policy recorded, and a test
write-and-read of a 1 GB file at that path.

---

## S2. Scheduler run (mode-sweeping)

**Goal:** a schedule cache for every (arch, layer) combo, produced by the
traffic-mode sweep per directive 3.

**Host decision: solve on this login node, not on Stokes.** Gurobi is licensed
and working here - verified, academic license 2828339, full size - and a Stokes
license is unconfirmed. The schedule cache is small (JSON per pair) and ships
easily, where a licensing dead end on Stokes would block the whole campaign.
If a Stokes license turns out to exist, solving there removes a transfer step,
but that is an optimization and not the plan of record.

**Tasks.**

1. Enumerate the combo set: 5 archs x 151 scheduled layers = **755** pairs.
   Prosperity's **6** partial-sum-infeasible pairs (A08 L1-L6 at `T = 32`,
   2,048 B against the 1,024 B psum budget) are expected to fail and must be
   **recorded as infeasible**, not retried - leaving **749** pairs that
   generate.
2. Solve each with `solve_and_cache_schedule(arch, arch_yaml, mapspace_yaml,
   trace_dir, layer, meta, cache_dir)`, caching under
   `zoo/wt500_fig3cfg/outputs/schedules/<arch>/<trace_dir>/<layer>.json`. The
   artifact records the winning mode, the DRAM step count, and the arch and
   mapspace SHA-256s, so a later mapspace change is detectable.
3. Run it under `setsid` with per-pair logging, since the A07 layers and the
   C01 heavy layers are the slow solves.
4. Run the **bridge-compatibility gate** over every solved schedule
   (`gen_inputs.check_bridge_compatibility(path, arch)`) and require
   `passed=True` for all 749. This is what catches a split kernel, a missing
   pixel offset, or a kernel bound below the full window - the gate is the only
   thing standing in for a kernel-offset field the wire format does not have.

**Verification criterion.** 749 schedule JSONs present; 6 prosperity pairs
recorded infeasible with their IIS; every artifact's mapspace hash matching the
current mapspace files; gate `passed=True` with zero violations on all 749; and
each artifact's recorded mode being a sweep winner rather than `base`.

---

## S3. Schedule conclusions (the digest, and the run order)

**Goal:** the step-1c-style digest for the new schedules, and the
fastest-to-slowest order directive 1 requires.

**Tasks.**

1. Emit one row per (arch, benchmark, layer) with: tile count, wave width
   (gustavsnn only, from the schedule's NodeLevel spatial product), feasibility
   status, frame count (`dram_num_steps x noc_num_steps`), and machine core
   count.
2. **Compute record-count estimates, which is this stage's substantive work.**
   The method is exact and cheap - a 3x3 neighbourhood sum over each capture
   giving per-output-position firing-line counts, multiplied by the
   output-channel slab count - and it must be used in preference to timing a
   slice, because subset extrapolation fails badly here: on gustavsnn's C01
   layer a 128-tile slice gives 2.1 records per tile and a 512-tile slice 22.6,
   against a true mean of 37.1, because the solved tile order front-loads
   sparse border regions. Per-arch rules established by the walkthroughs:
   - **loas** and **ptb**: one record per non-silent `(tap, channel)` line per
     output-channel slab. PTB's record stream is identical to LoAS's; only its
     cycle counts differ.
   - **prosperity**: on 1x1 layers, one record per firing channel per slab -
     numerically LoAS's rule. **On the 47 3x3 layers this is uncounted and must
     be measured here**, since prefix reuse (about 2.07x on one measured layer)
     and the tiling both differ from the 1x1 case and neither transfers.
   - **spinalflow**: one record per firing event per slab.
   - **gustavsnn**: one record per firing event per slab, with a slab of 2
     against spinalflow's 4, so **exactly 2x spinalflow** on the same layer.
3. Rank combos by total estimated records and emit the run order. The
   provisional ordering, to be replaced by step 2's numbers:
   **loas and ptb first** (smallest records per layer, and ptb's stream equals
   loas's), **then prosperity** (1x1 layers are loas-sized; its 3x3 layers land
   wherever step 2 puts them), **then spinalflow**, **then gustavsnn**; and
   within each architecture, benchmarks in ascending record total, which puts
   **spinalflow C01 and gustavsnn C01 last** as directed.
4. Record the known anchors for cross-checking step 2's output: gustavsnn C01
   `block2_0_0` at about 105 million records per sample on the cifar10_dvs
   variant and 77.8 million on dvs128; spinalflow's same layers at 52.5 million
   and 38.9 million; prosperity's heaviest surviving layer at about 3.9 million.

**Verification criterion.** Every one of the 755 pairs has a row; the row count
by architecture is 151 each; the stride-2 layers are **absent** from all five
architectures, which is directive 2's check; the 47 prosperity 3x3 layers have
record estimates; and the emitted order is monotonically non-decreasing in
estimated records with the two C01 combos of spinalflow and gustavsnn last.

---

## S4. Input transfer

**Goal:** the 8 captures on Stokes, verified.

**Tasks.**

1. Check which of the 8 already exist at the Stokes data root; the fig2
   campaign placed at least one there.
2. Compute SHA-256 for every `.npy` and `meta.json` on this side and write a
   manifest.
3. `rsync -aP --partial` the missing captures. Order the transfer **smallest
   first** (B09/vgg16 349 MB -> A07 20 GB) so an early quota failure surfaces
   cheaply rather than 20 GB in.
4. Verify with `sha256sum -c` **on Stokes**, against the manifest from step 2.
5. Re-check free space after transfer, since 33 GB of inputs sits alongside the
   output budget from S1.

**Verification criterion.** `sha256sum -c` passes for every file on Stokes,
the per-capture `meta.json` layer counts match the digest's (A02 12, A04 16,
A07 72, A08 13, B09/resnet19 19, B09/vgg16 13, C01 6 + 6 = 157 captured, 151
scheduled), and free space still exceeds the S1 output estimate.

---

## S5. Demo runs and scaling

**Goal:** one measured demo per (arch, benchmark) combo, then a multi-node plan
sized from those measurements.

**Tasks.**

1. **One demo per combo** - 5 archs x 8 benchmarks, minus combos with no
   generating layers - on one small layer each, at the campaign's real chunk
   size of 10 samples. Measuring at chunk 10 rather than 1 is not incidental:
   the stale-binary failure mode is invisible at chunk 1 and silent at chunk
   10, so the demo must exercise the configuration the campaign will use.
2. **Measure wall time, not a native-scan floor.** The lesson is recorded in
   `walkthroughs/spinalflow.md`: a subset timing of the native scan
   extrapolated to about 4 minutes for a layer an earlier pilot had taken 23
   minutes or more on, a 6x gap, because the subset timed scan and unpack only
   and excluded regroup, streaming and memory pressure - which is where a
   50-million-record layer spends most of its clock. Demos must time the whole
   `gen` invocation end to end, and record peak RSS alongside.
3. **Measure the compression ratio** on the demo output, since S1's output
   budget depends on it and no uncompressed-to-compressed figure exists yet.
4. **Shard by record count**, not by case count. `slurm/shard_cases.py`
   currently divides cases evenly (`cases_per_shard`), which is the flat budget
   the earlier pilot proved dead when one 131,072-tile SpinalFlow case ran 23+
   minutes at ~15 GB against a 2,000-case / 90-minute assumption. It needs a
   weighted mode taking S3's record estimates as input.
5. **Heavy layers get dedicated shards in their own process scopes.** The
   memory failure is structural, not incidental: records are materialized as
   Python objects before streaming, so a 52-million-record layer holds
   gigabytes of live objects however fast the native scan is. Each heavy shard
   runs one (arch, layer) with its own time and memory limit, started with
   `setsid` so an OOM kill does not take the pane or its siblings with it. The
   heavy set is at minimum: gustavsnn C01 L1-L4 and spinalflow C01 L1-L4, plus
   whatever S3's estimates put in the same band.
6. **Node-count x time estimate** from the demo rates and S3's record totals,
   with the heavy shards costed separately since their rate will not match the
   bulk.

**Verification criterion.** Every combo has a demo with a wall-clock time, a
peak RSS, a record count matching S3's estimate for that layer within a stated
tolerance, and a non-empty output whose record count is **greater than zero** -
the explicit check for the empty-trace failure mode, which a byte-size check
cannot make. A compression ratio is
recorded. The shard plan's weights come from records and its heaviest shard's
projected time fits the queue's wall-clock limit.

---

## S6. Checkpointing and verification cadence

**Goal:** a bad batch is caught early rather than at delivery.

**Tasks.**

1. **Per-shard completion manifest**: on shard completion, write the output
   paths, record counts, byte sizes and SHA-256s. `slurm/assemble_shards.py`
   and `merge_results.py` are the existing collection points to extend.
2. **Resumability, and a size check is not enough.** `slurm/rerun_missing.py`
   finds incomplete outputs and emits a replacement array manifest, but its
   completeness test is `path.is_file()` alone (`:78`). `harness.py` is
   stricter, rejecting zero-byte outputs (`:424`, `:566-578`) - and **neither
   catches the failure mode that matters here**, because a trace with zero
   records is not zero bytes: it still carries a 200-plus-byte header and a
   trailer, and the trailer honestly reports a burst count of 0. So the test has
   to be on the **record count**, compared against S3's estimate, not on
   presence and not on size. That comparison is what distinguishes a correct
   small layer from a silently empty one.
3. **Verification cadence, not just a final gate.** After the first shard of
   each architecture, and thereafter every N shards, check: record count within
   tolerance of the S3 estimate; a decoded sample of the stream (header fields,
   a burst record, the trailer's total matching the bursts written); and for
   gustavsnn specifically that the stream is v3 and its tick sequence is
   non-decreasing within each core. The first-shard-per-arch check is the one
   that would have caught the stale binary.
4. **Checkpoint the schedule cache and the digest** alongside the output, so a
   trace set is always interpretable against the schedules that produced it -
   which directive 3 makes necessary, since tick ordering and frame grouping
   are schedule-dependent.
5. **Record what is deliberately absent**: the 6 prosperity infeasible pairs,
   and the 6 stride-2 layers excluded for every architecture. A consumer
   counting 749 rather than 755, or 151 rather than 157, should find the reason
   in the manifest rather than inferring a failure.

**Verification criterion.** Every completed shard has a manifest entry with a
SHA-256 and a non-zero record count; `rerun_missing` run against a deliberately
deleted and a deliberately truncated output correctly reports both as missing;
the cadence check has run at least once per architecture; and the final
manifest's absences match the two recorded exclusion lists exactly.

---

## Operational caveats carried from the walkthroughs

Each of these is a property of the code that bears on running the campaign, and
each is recorded in `zoo/wt500_fig3cfg/CAVEATS.md` with its full verdict.

| id | what it means for this run |
|---|---|
| **G1** | Rebuild all five binaries; a stale one writes empty traces silently at the campaign's chunk size. Preflight, and S6's first-shard check. |
| **S3** (spinalflow) | Record count, not tile count, drives memory; heavy layers need dedicated shards in their own process scopes. S5 task 5. |
| **G2** | A wrong positive wave width is undetectable and leaves addresses correct while ticks are wrong. **Take the width from the schedule's NodeLevel spatial product, never from a constant** - it is 4 on 145 layers, 2 on five and 1 on one. (`sweep_config.yaml:67` now names that derivation rather than a value, so the config no longer invites the mistake; the instruction is durable regardless.) |
| **L2** | The bridge gate lives in `gen_inputs.py`, not in the bridges. Generation must go through the gated path; a direct bridge call loses every kernel and offset check. S2 task 4. |
| **L5** | `mac_cycles` is a maximum across a frame's cores, and it is **not** degenerate for prosperity or gustavsnn. Do not compare cycle counts across architectures without accounting for it. |

## Open questions for the user

1. **S1's three items**: SSH alias, node-helper name, and whether a project
   allocation exists beyond the home lustre path. S1 cannot complete without
   these; everything else can be planned around them.
2. **Solve host**: this plan solves on the login node because Gurobi is
   confirmed here and unconfirmed on Stokes. If a Stokes license exists, say
   so and S2 moves there, removing one transfer.
3. **Output retention**: whether traces live in scratch with migration or
   directly in project space, which depends on the quota S1 measures and on how
   long the traces must outlive the cache-simulation runs that consume them.
4. **Tolerance for S5 and S6's record-count checks**: a demo's measured count
   should match S3's estimate, but the estimate is exact only for the archs
   whose rule is one-record-per-spike. A tolerance of zero is right for those
   and wrong for prosperity's 3x3 layers, where prefix reuse makes the estimate
   an upper bound. Recommendation: exact for loas, ptb, spinalflow and
   gustavsnn; upper-bound-only for prosperity.
