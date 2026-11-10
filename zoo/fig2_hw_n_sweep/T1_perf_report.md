# T1 — fig3_hw_n_sweep pipeline profile, cycles-only feasibility, campaign runtime estimate

Scope: can `lays.weight_trace_gen` + `lays.nocsim` produce only cycle counts, skipping
the per-tick weight addresses; how much faster that makes the pipeline; and what the
planned resnet19 campaign costs on the cluster.

Measurements: 6 representative (layer, N) cases, 1 sample each, single-threaded on the
login node with warm page cache, `/lustre/fs1/home/ya867177/.venvs/neuro_cache_wcache`,
`spinalflowgen` and `eventsim` as freshly rebuilt. Raw data and the profiling scripts are
in the session scratchpad (`prof_all.json`, `prof2.py`, `campaign.json`); nothing under
`src/` was modified.

---

## 1. Correction to the task premise

The task asked about "the huge per-tick `sample_XXXXX.json.gz` weight traces". **Those do
not exist.** The `gen` CLI persists through
`lays.nocsim.step_cycles.save_step_cycles` (`src/lays/weight_trace_gen/cli.py:117`,
`cli.py:224`), whose docstring states it plainly: the weight addresses "are left out; they
reach the cache simulator through the WCTS stream (`stream_weight_trace`) instead"
(`src/lays/nocsim/step_cycles.py:28-39`). The file holds only the identity fields, the step
counts, and each tile's `dram_i, noc_i, mac_cycles, lif_cycles`
(`step_cycles.py:49-53`).

Measured: the file is **3.7 KB** for a case whose intermediate address stream is **16 MB**,
and **3.7 KB** for the 100 MB case. The on-disk artifact is already cycles-only.

The waste is one layer earlier, entirely in-process:

| where | what happens | size for one case (layer_14, N=32) |
|---|---|---|
| `spinalflowgen` stdout/`out.bin` | 7 int32 per MAC cycle: `tick_value`, `num_addresses`, then `kh,kw,cin,cout_start,cout_end` | **100.2 MB** |
| Python `_unpack_output` | 2 `struct.unpack_from` calls + a dict + a tuple + 2 list appends **per MAC cycle** (the `"<2i"` tick header at `native_bridge.py:60` and the `"<5i"` address at `:64`; the `"<4i"` at `:56` is once per (tile, sample)) | 3.58 M ticks |
| `assemble_layer_traces` | builds `CoreEntry`/`TickEntry` objects holding every address | 3.58 M addresses |
| `save_step_cycles` | **discards all of it**, writes `mac_cycles` only | 3.7 KB |

The wire format is specified at `src/lays/weight_trace_gen/spinalflow/main.cpp:16-21` and
written by `write_tick_grouped` (`src/lays/weight_trace_gen/tick_output.h:34-59`); the
reader is `src/lays/weight_trace_gen/spinalflow/native_bridge.py:45-69`. For SpinalFlow
every tick group has exactly one address by construction (`main.cpp:22-23`), so the stream
is 28 bytes per MAC cycle.

## 2. What nocsim actually needs

Only `{(dram_i, noc_i): ComputeCycles}`. The CLI's single use of the trace is

```python
cycles_by_step = load_step_cycles(pathlib.Path(args.weight_trace)).by_step
```

(`src/lays/nocsim/sim.py:337`), handed to `run_from_json` (`sim.py:344-347`), which
passes it through to `combine()` (`sim.py:184-186`). `load_step_cycles` reads `mac_cycles` and `lif_cycles` per tile and
nothing else; it explicitly tolerates and **ignores** a `ticks` field if present
(`src/lays/nocsim/step_cycles.py:143-152, 167-174`). No address, byte count, or per-tick
datum reaches `combine()`.

So nocsim needs no change at all. Confirmed end to end: `--simulate` reproduces
`total_cycles`/`count_cycles` from a file written by every variant below.

## 3. Time breakdown, measured

Per case, 1 sample. `stage1` = `weight_trace_gen` (schedule load, trace load+slice, task
pack, native run, read back, unpack+assemble, save). `stage2` = nocsim
(`load_step_cycles` + `combine`+CSV + `eventsim`). `import` = 0.33 s, the measured
interpreter+import cost of the two subprocesses `run.py` spawns per case
(`zoo/fig3_hw_n_sweep/run.py:35-47`): 0.18 s for `lays.weight_trace_gen.cli`, 0.15 s for
`lays.nocsim.sim`.

| layer | N | tiles | MAC cycles | out.bin | native | unpack+assemble | stage1 | stage2 | import | **total** |
|---|---|---|---|---|---|---|---|---|---|---|
| layer_14_layer2_2_conv2 | 32 | 512 | 3,579,568 | 100.2 MB | 1.897 | **14.472** | 16.505 | 0.022 | 0.33 | **16.86** |
| layer_02_layer1_0_conv2 | 32 | 1024 | 579,656 | 16.2 MB | 0.289 | **2.148** | 2.467 | 0.042 | 0.33 | **2.84** |
| layer_19_layer3_1_conv2 | 128 | 64 | 538,352 | 15.1 MB | 0.287 | **2.214** | 2.605 | 0.005 | 0.33 | **2.94** |
| layer_14_layer2_2_conv2 | 512 | 64 | 447,446 | 12.5 MB | 0.350 | **1.591** | 1.949 | 0.004 | 0.33 | **2.28** |
| layer_02_layer1_0_conv2 | 512 | 256 | 144,914 | 4.1 MB | 0.110 | **0.524** | 0.644 | 0.009 | 0.33 | **0.98** |
| layer_05_layer1_1_conv2 | 512 | 256 | 131,892 | 3.7 MB | 0.064 | **0.385** | 0.548 | 0.010 | 0.33 | **0.89** |

Seconds. Bold = the address work.

Findings:

- **Python unpack+assemble is the bottleneck**, 70–88 % of stage 1, and it is cleanly
  linear in MAC cycles: **3.66 µs per address** (range 2.92–4.11 across the six cases).
  Native + unpack together are 82–100 % of stage 1.
  Baseline stage 1 as a whole is **4.44 µs per MAC cycle** (range 4.15–4.84).
- The native binary is 11–18 % of stage 1. It is *not* proportional to MAC cycles alone —
  it also scans the whole `T x KH x KW x CIN` window per tile regardless of spike count
  (`SpinalFlowGen.h:69-93`).
- **nocsim is already negligible**: 0.004–0.042 s per case, under 2 % of the total. `combine`
  + CSV is 0.002–0.034 s, `eventsim` 0.002–0.007 s, `tc.csv` at most 0.25 MB.
- Interpreter+import (0.33 s) already exceeds stage 2, and becomes the dominant per-case
  cost once the address work is removed.

## 4. Proposed modification (design only)

`mac_cycles` is a popcount: it is incremented once per nonzero trace element and never
reads an `AddressRow` (`src/lays/weight_trace_gen/spinalflow/SpinalFlowGen.h:86-88`). It is
already written to the wire **before** any address
(`main.cpp:139`, ahead of `write_tick_grouped` at `main.cpp:140`). Nothing downstream of
the counter depends on the addresses existing.

**(a) native — a `--cycles-only` output mode.** Replace the `write_tick_grouped(out_fh,
result.addresses)` call at `main.cpp:140` with `write_i32(out_fh, 0)`, i.e. emit
`num_ticks = 0`, and compute the count with a twin of `reconstruct_sample` that has the
identical loop nest and identical `trace[idx] != 0` predicate but no `AddressRow` and no
`std::vector` (`SpinalFlowGen.h:76-88` minus lines 80-87's `push_back`).

Emitting `num_ticks = 0` rather than a new file format is the point of the design: the
existing framing is unchanged, so `_unpack_output`
(`native_bridge.py:45-69`) still parses the stream correctly and simply yields empty
`ticks`. No format version, no `format:` key, no reader migration.

This also skips `write_tick_grouped`'s `std::map<int32_t, std::vector<const AddressRow*>>`
(`tick_output.h:39-42`) — a red-black-tree node allocated per MAC cycle to group buckets
that, for SpinalFlow, always hold exactly one element (`main.cpp:22-23`).

**(b) Python — a header-only reader.** A cycles-only sibling of `_unpack_output` that reads
the 4-int header per `(tile, sample)` and yields `(tile_idx, sample_idx, mac_cycles, [])`.
`assemble_layer_traces` needs no change: it already handles an empty `ticks` list, and
`merge_cores_by_tick` returns `[]` for it (`weight_trace.py:75-81`).

**(c) optional, orthogonal — memoize per `(ho, wo)`.** `mac_cycles` depends on
`t_off/t_n`, `kh_n/kw_n`, `cin_off/cin_n`, `ho`, `wo` — **not** on `cout_off`/`cout_n`,
which only populate `row.cout_start`/`row.cout_end` (`SpinalFlowGen.h:84-85`). In this
sweep the DRAM loop is `HO x WO x (COUT/active)` (`gen_inputs.py:85-87, 103`), so for
`N < COUT` the same window is recounted `COUT/N` times. This is directly visible in the
existing results: summed `count_cycles` for resnet19 is 104,365,892 at N=32 and
52,182,946 at N=64 — an exact factor of 2.

Measured gain from memoizing: layer_14 at N=32, native 0.021 s → 0.011 s. Worth little on
its own, because once (a) and (b) land the native scan is no longer the bottleneck.
**Recommend (a)+(b); treat (c) as optional.**

I did not examine the other four arch bridges (loas, ptb, gustavsnn, prosperity). `main.cpp`
and `tick_output.h` are shared in shape across all five (`tick_output.h:8-11`), so the same
change likely applies, but I did not verify it and the fig3 campaign does not need it.

### Correctness

Prototyped in the scratchpad (`build/spinalflow/main_proto.cpp`, a copy — the repo source
was not touched) and compared against the current binary on all 6 cases:

- `mac_cycles` per `(dram_i, noc_i)` tile: **identical in all 6 cases**, for both the
  cycles-only and the memoized variant.
- The written `sample_NNNNN.json.gz`: **decompressed bytes identical** across baseline,
  cycles-only, and memoized.
- `--simulate` `total_cycles`/`count_cycles` therefore identical, since they are a pure
  function of that file plus the schedule.

The argument is structural, not just empirical: the counter is incremented by the same
predicate over the same loop nest, and it is already serialized at `main.cpp:139`
independently of the address stream. The only removed work is the construction and
transport of data that `save_step_cycles` discards.

**One caveat.** The addresses are not dead everywhere — `lays.cachesim` consumes them via
`stream_weight_trace` (`cli.py:48`, `step_cycles.py:28-39`). `--cycles-only` must be an
opt-in flag used by the fig3 path, never the default, or the cache-simulator pipeline
loses its input.

## 5. Projected speedup

| case | stage 1 baseline | stage 1 cycles-only | speedup (stage 1) | speedup (end-to-end incl. stage 2 + import) |
|---|---|---|---|---|
| layer_14, N=32 | 16.505 s | 0.127 s | **130x** | **35.2x** |
| layer_02, N=32 | 2.467 s | 0.032 s | 77x | 7.0x |
| layer_19, N=128 | 2.605 s | 0.101 s | 26x | 6.7x |
| layer_14, N=512 | 1.9491 s | 0.0083 s | 236x | 6.7x |
| layer_02, N=512 | 0.644 s | 0.012 s | 53x | 2.8x |
| layer_05, N=512 | 0.548 s | 0.102 s | 5x | 2.0x |

Stage 1 effectively stops costing anything (5x–236x, 130x on the largest case). End-to-end speedup is capped by the 0.33 s of
interpreter+import that `run.py` pays per case — after the fix, **~80 % of the remaining
per-case time is Python startup, not simulation.**

## 6. Campaign runtime estimate

Planned: resnet19, 13 stride-1 conv layers x N in {32,64,128,256,512} x 100 samples =
**6500 cases**. I confirmed the trace
`/lustre/fs1/home/ya867177/data/input_trace_delta/B09/loas_resnet19_T4_n500` yields exactly
13 valid layers.

Model: baseline stage 1 = 4.44 µs x `count_cycles`; cycles-only stage 1 = 0.061 s flat;
stage 2 = 0.015 s; import = 0.33 s. `count_cycles` per (layer, N) is the 5-sample mean from
the existing `outputs/results.csv`; I validated that against the 500-sample trace directly
(layer_02 N=32: 579,656 measured vs 567,419 predicted, +2.2 %; layer_14 N=32: 3,579,568 vs
3,627,938, −1.3 %).

| N | cases | address records | out.bin written+parsed | baseline core-h | cycles-only core-h |
|---|---|---|---|---|---|
| 32 | 1300 | 2,087,317,840 | 58 GB | 2.70 | 0.15 |
| 64 | 1300 | 1,043,658,920 | 29 GB | 1.41 | 0.15 |
| 128 | 1300 | 521,829,460 | 15 GB | 0.77 | 0.15 |
| 256 | 1300 | 305,141,220 | 9 GB | 0.50 | 0.15 |
| 512 | 1300 | 274,991,640 | 8 GB | 0.46 | 0.15 |
| **all** | **6500** | **4,232,939,080** | **119 GB** | **5.85** | **0.73** |

**8.0x** on core-hours (21,050 → 2,642 core-seconds); mean per case 3.24 s → 0.41 s.

Wall time, 32 cores/node, assuming perfect packing (partition `normal`, 153 nodes, 32+ cpus):

| nodes | cores | baseline | cycles-only |
|---|---|---|---|
| 1 | 32 | 11.0 min | 1.4 min |
| 4 | 128 | 2.7 min | 0.3 min |
| 8 | 256 | 1.4 min | 0.2 min |
| 16 | 512 | 0.7 min | 0.1 min |

### The actionable conclusion

**The campaign does not need this optimization.** It is ~6 core-hours as it stands, about
11 minutes on a single node. At these scales SLURM scheduling overhead dominates: 6500
tasks of 0.4 s each is pathological, and the 250-job `maxsubmit` cap means the array must
be chunked regardless.

Two cheaper changes buy more than the cycles-only work does, for the campaign specifically:

1. **Batch samples per invocation.** `run.py` calls `weight_trace_gen` with
   `--sample-count 1` per case (`run.py:35-40`), so the 0.33 s import and the trace
   load/slice (up to 0.094 s measured) are paid 6500 times. `gen` already supports
   `--sample-count` and a worker pool (`cli.py:128-181`). One invocation per (layer, N) with
   100 samples = 65 invocations instead of 6500. Stage 1 then drops to roughly
   65 x 0.38 s + 6500 x 0.03 s ≈ 220 core-s.
2. **Chunk the SLURM array** so each task handles ~26 cases (250 tasks), keeping job
   overhead a small fraction of task runtime.

With batching *and* cycles-only, stage 1 is ~220 core-s and the campaign is dominated by
nocsim's own per-case import: ~0.36 core-h total, ~16x baseline.

My recommendation: **do the cycles-only change for its own sake** — it removes 119 GB of
write-and-reparse and makes per-case cost independent of spike density, which matters for
any larger sweep (more samples, denser layers, the other four archs) — but do not treat it
as a blocker for this campaign. Batching and array chunking are the higher-leverage
work here.

## 7. Caveats and what I could not determine

- All timings are **login-node, warm-cache, single-threaded**. Contention on a shared login
  node and cold Lustre reads of the 954 MB trace are not represented; the 32-core-per-node
  wall-time figures assume no memory-bandwidth contention, which I did not test.
- `zoo/fig3_hw_n_sweep/inputs/` was absent when I profiled, so I reconstructed the
  schedule JSON and arch YAML in the scratchpad using `gen_inputs.py`'s exact construction
  (lines 56-108). `gen_inputs.py` has since been run, so it now holds `inputs/arch` with 5 YAMLs and
  125 schedule JSONs — but for the 5-sample in-repo trace.
  **Campaign prerequisite:** schedules for `trace_dir =
  loas_resnet19_T4_n500` do not exist yet; the committed `results.csv` was produced against
  the 5-sample in-repo trace. `check_schedule_matches_trace` (`cli.py:135`) keys on
  `trace_dir`, so `gen_inputs.py` must be re-run against the 500-sample trace first.
- The 4.44 µs/address figure is fitted on 6 points spanning 132 K–3.6 M MAC cycles, with
  ±9 % spread. Projections inherit that.
- `lif_cycles` is `None` for every tile on this path (`weight_trace.py:151`); I did not
  investigate whether any configuration populates it.
- I did not measure peak RSS. Holding 3.58 M `CoreEntry`/`TickEntry` objects is on the order
  of GB and is plausibly why `SAMPLE_CHUNK_SIZE = 10` exists (`cli.py:62-66`, "a dense layer
  at chunk_size=100 OOM'd on real data"). Cycles-only removes that constraint and would let
  the batching in §6 use far larger chunks, but I did not verify the memory numbers.
