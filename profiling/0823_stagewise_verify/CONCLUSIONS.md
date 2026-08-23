# 2026-08-23 stagewise verification: conclusions

Stages 1 and 2 are complete. Stages 3 and 4 have not started. The headline is
that **the pipeline verified clean and the input data did not**.

---

## 1. What was verified, and how hard

### Stage 1, the MIP solver: no defects found

| Question | Answer | Evidence |
|---|---|---|
| Does `num_pes` change the schedule? | No, for any `num_pes >= 4` | Four values, both layers, byte-identical JSON. `num_pes` is only a ceiling (`spatial.py:78`); `configs/dataflow/loas.yaml`'s `COUT: {spatial: 4}` is a linear equality (`node_level.py:62`) that the ceiling never binds. |
| Are all 13 TrafficModes enumerated? | Yes; 2 feasible, `gb_oooo` wins both layers | `mode_sweep.json` records all 26 solves, not just winners. BASE is feasible but loses on `_mode_score`, as `tracegen.py:92-98` claims. |
| What is the minimum NoC global buffer? | 32 KiB to be feasible, ~307 KiB to stay useful | Ten sizes swept. Feasibility floor is the NodeLevel footprint (18432 B) because the NoC expression covers levels `[0, dram_start)`. |
| Is a given config reproducible? | Yes | Two independent solves of the same model, and a full second run of the script, reproduced byte-identically. |

### Stage 2, weight-trace generation: no defects found

Four independent checks passed:

1. **Row counts reproduce from raw spikes.** A NumPy recomputation applying the
   same padding rule and counting non-silent sites matched the generator
   **exactly, as integers, on all ten samples**. This is the strongest single
   result in the verification.
2. `mac_cycles / tile_count` equals `rows_per_core` to the digit.
3. Padding accounts for the emission gap: predicted `0.6944 * site_fire_rate`
   lands within 0.001 of measured on vgg16.
4. Every WCTS stream is self-consistent: trailer magic, `total_bursts` against
   a full frame walk, and bytes-consumed against file size.

---

## 2. The blocking finding: input trace density

**The captured spike traces are far denser than an SNN should be, and the two
layers chosen for this verification are both in the bad regime.**

Expected density is about 10%. Measured, over the first 200 images of the full
10,000-sample captures:

- **vgg16** layers 1-8: 0.149 to 0.226, acceptable. Layer 9 jumps to **0.578**;
  layers 10-12 run 0.271, 0.427, 0.528.
- **resnet19** layers 1-7: 0.117 to 0.205, acceptable. Then a monotone climb
  through the layer2 blocks to **0.917** at `layer_14_layer2_2_conv2`, where
  86% of neurons fire at every timestep and only 3.8% are ever silent.

The two verification layers measured 0.578 (vgg16 `layer_09_features_30`) and
0.424 (resnet19 `layer_16_layer3_0_conv2`). Both HIGH.

Full table in `input_trace_audit/density_audit.txt`.

### Three explanations ruled out

1. **Not a units or dtype error.** `np.unique` returns exactly `[0, 1]` on all
   31 layers, so `sum/size` is a firing rate.
2. **Not a subsetting artifact.** `n5 == all[:, [2697,3078,5110,6367,8502]]` is
   `True` on every layer compared. The 5-sample subset is faithful.
3. **Not a thresholding artifact.** Per-timestep density is not flat: `t=0` is
   the lowest in every layer, which is LIF charging, and the always-fire /
   never-fire split is graded rather than bimodal. These are real spikes.

The capture is also internally coherent: the three resnet19 shortcut layers have
densities identical to their block's `conv1` (0.1431, 0.3039, 0.8231), which is
correct since a shortcut branch takes the same input tensor.

### The residual hypothesis

The capture faithfully records a model whose deep layers saturate, most
plausibly an undertrained or badly calibrated checkpoint where deep-layer
thresholds sit far below the input drive. The escalation is not uniformly
monotonic (vgg16 goes 0.20, 0.58, 0.27; resnet19 recovers from 0.82 to 0.42),
which argues against a single systemic scale error and for specific layers
saturating.

**This is unresolved.** It needs an external reference for what spike density
real SNNs on CIFAR-10 exhibit at depth, and in particular what the LoAS paper
reports for the very checkpoints this capture used. See `HANDOFF.md`.

### Provenance is recoverable until about 2026-09-10

Captured 2026-07-17 in a sibling repo at `/u/yyu9/neuro_cache_trace/`, deleted
between the 2026-08-11 and 2026-08-12 home snapshots. The capture code **and the
model checkpoints still exist** in the snapshot, verified present 2026-08-23:

```
/u/yyu9/.snapshot/snapshot-daily-_2026-08-11_17_00_00_UTC/neuro_cache_trace/
  capture/input_grabber.py   capture/run_loas.py   model/LoAS/...
```

Reading them narrows the diagnosis considerably:

- `run_loas.py` loads **LoAS's own released checkpoints**,
  `model/LoAS/sample_ckpts/{resnet19,vgg16}_final_dict.pth.tar`, against LoAS's
  own `archs/cifarsvhn/{resnet,vgg}` definitions. Nothing here was trained by
  us. So "undertrained checkpoint" is a weak hypothesis: if these densities are
  real, they are real in the LoAS authors' published models, which would be a
  finding about LoAS rather than about this capture.
- `InputGrabber` hooks `input[0]` of every `nn.Conv2d` except the first, and
  casts with `.astype(np.uint8)`. Since every captured value is exactly 0 or 1,
  no truncation occurred, so the hooked tensors really were binary.
- **`run_loas.py` never passes `module_filter`**, although `InputGrabber`
  documents it as the mechanism to "exclude Conv2d layers that receive
  non-binary inputs (e.g. layers immediately after average pooling)". That is a
  concrete gap. It is **not** established that it explains the high densities:
  uint8 truncation of fractional post-pool values would push density down, not
  up, and the elevated vgg16 layers are mid-block rather than post-pool. Worth
  checking, not yet an answer.

**Deadline: the snapshot expires around 2026-09-10.** Copy `capture/` and the
relevant checkpoints out before then if this is to be investigated at all.

---

## 3. Three secondary findings

**a. The objective does not pin down the schedule.** At 4 MiB, 2 MiB, 1 MiB and
512 KiB the vgg16 objective is bit-identical at `160.2873338750062` with
identical delay, yet `dram_num_steps` comes back 16, 16, 64, 128. None of those
capacities binds. The models differ only in a non-binding right-hand side, so
Gurobi returns a different member of the same optimal face. `dram_num_steps`
sets the tile count Stage 2 walks, so an 8x swing there is decided by a
tie-break rather than by the model. One config is reproducible; comparisons
*across* configs are not safe to read as a size effect.

**b. NoC size below ~307 KiB changes the spatial mapping's character.** All 16
cores are always used, but *which* dimension is spread across them changes:
COUTx16 above 307 KiB, then HO/WO progressively replacing COUT below it. Under
COUTx16 the cores fetch 16 different weight slices; under WOx4 -> HOx4 they
fetch the same slice. Opposite cache workloads. This would also trip `PROGRESS.md`
U29, where a non-COUT `burst_dim` decodes silently wrong rather than being
refused. The chosen 2 MiB is 6.7x clear.

**c. A misleading diagnostic.** `num_pes=2` reports "every TrafficMode
infeasible" when the real cause is
`ValueError: SNNDataflow: NodeLevel spatial product=4 exceeds arch num_pes=2`.
`solve.py:74` runs the validator inside the per-mode loop at `solve.py:300`, so
it escapes on the first mode and `tracegen.py:112` relabels it. A configuration
error is reported as model infeasibility, pointing at the wrong file.

---

## 4. The fact that will drive Stage 4

From the WCTS header and confirmed by enumerating every tile offset:

```
vgg16     16 cores x 32 COUT channels, disjoint, union = 0..511  complete
resnet19  16 cores x 16 COUT channels, disjoint, union = 0..255  complete
```

Core `c` owns COUT `[c*32, c*32+32)`, walked 4 at a time across the DRAM steps
(`tiles.py:157`: `core_idx * node_bound * noc_t * dram_t = 1*4*1*8 = 32`).

**The 16 cores never request the same weight address.** For any `(kh, kw, cin)`
each wants a different COUT slice, so a shared L2 sees zero cross-core weight
reuse within a tile. All reuse must come from revisiting `(kh, kw, cin, cout)`
across different `(ho, wo)` tiles. Worth holding onto when Stage 4 numbers look
wrong.

---

## 5. Method: what made this work

The discipline that produced the findings above, worth keeping for stages 3
and 4:

1. **Gate before every stage.** List the inputs, the exact command, and the prior
   stage's output; wait for review. Two of the four decisions that came out of
   those gates (32 KiB node buffer, `_n5` traces) changed the run.
2. **Copy inputs, never reference them.** Each stage's `inputs/` is a complete
   record of what it saw, with SHA-256 in `MANIFEST.json`. A stage never writes
   into another stage's directory.
3. **Recompute the answer independently.** The exact-integer match between the
   generator and a NumPy reimplementation is worth more than any number of
   internal consistency checks.
4. **Check the data, not only the code.** Both stages verified clean. The
   problem was in the input distribution, which no amount of pipeline testing
   would have surfaced.
5. **Verify the binaries you run.** `loasgen` was 18 days stale against its own
   `main.cpp`. It happened to be benign; that was luck, not design.

---

## 6. State

| Stage | Status |
|---|---|
| 1 MIP solver | Complete at NoC 2 MiB, node 32 KiB. `stage1_mip_solver/outputs/RESULTS.md` |
| 2 weight trace | Complete, 10 samples. `stage2_weight_trace/outputs/RESULTS.md` |
| 3 nocsim | Not started, gate not drafted |
| 4 wcache | Not started. Note: the engine has **no event logging**; the five event traces requested need an emitter written first |

**Open decision blocking further work:** whether to swap to healthy-density
layers, keep the current ones as a stated low-sparsity stress case, or fix the
capture. vgg16 `layer_08_features_27` is a free swap, with an identical
workload shape (`KH3 KW3 CIN512 COUT512 HO4 WO4 T4`) at density 0.1995 instead
of 0.578. resnet19 has no clean equivalent: every CIN=512 layer is 0.349 or
worse.
