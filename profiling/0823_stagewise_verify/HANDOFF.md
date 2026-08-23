# Handoff: is this SNN spike density plausible?

Written 2026-08-23 so another session, on another machine, can answer one
question without re-deriving the project. Everything needed is in this file.

---

## The question

**What spike density do real, correctly trained SNNs exhibit on CIFAR-10, per
layer, at T=4, and does it rise with depth?**

Specifically:

1. What per-layer firing rate do published SNNs on CIFAR-10 report at low
   timestep counts (T=2 to T=8)? Typical papers to check: LoAS, SpinalFlow,
   PTB, Prosperity, and the SNN training literature they cite (spike-driven
   transformers, TET, tdBN, diet-SNN, surrogate-gradient VGG/ResNet work).
2. Is a **rising** density with depth normal, or do trained SNNs hold roughly
   constant or falling rates deeper in the network?
3. Is a deep layer at **0.92 density, with 86% of neurons firing at every one
   of four timesteps**, ever reported as normal, or is that always a symptom of
   an undertrained or miscalibrated model?
4. What do accelerator papers assume as their evaluated sparsity? LoAS in
   particular, since this project models LoAS hardware. If LoAS assumes ~10%
   density and our traces are 42-92%, the modelled speedups are meaningless.

## Why it matters

This project models SNN accelerators whose entire value proposition is skipping
silent neurons. If the input traces are 50-90% dense, the hardware being
modelled has almost nothing to skip, and every downstream number describes a
workload nobody would build this accelerator for.

---

## The measurements to check against

Full 10,000-sample captures, CIFAR-10, T=4, binary spikes, captured 2026-07-17.
Density is the fraction of `[T, Cin, Hin, Win]` entries that are 1, over the
first 200 images. `always` is the fraction of neurons firing at all 4
timesteps; `never` is the fraction firing at none.

### vgg16

| # | layer | CIN | HO | density | always | never |
|---|---|---|---|---|---|---|
| 1 | `features_3` | 64 | 32 | 0.1747 | 0.141 | 0.783 |
| 2 | `features_7` | 64 | 16 | 0.1493 | 0.092 | 0.784 |
| 3 | `features_10` | 128 | 16 | 0.2262 | 0.110 | 0.640 |
| 4 | `features_14` | 128 | 8 | 0.1485 | 0.061 | 0.743 |
| 5 | `features_17` | 256 | 8 | 0.1718 | 0.058 | 0.684 |
| 6 | `features_20` | 256 | 8 | 0.1741 | 0.051 | 0.664 |
| 7 | `features_24` | 256 | 4 | 0.1532 | 0.042 | 0.694 |
| 8 | `features_27` | 512 | 4 | 0.1995 | 0.078 | 0.632 |
| 9 | `features_30` | 512 | 4 | **0.5781** | 0.415 | 0.249 |
| 10 | `features_34` | 512 | 2 | 0.2705 | 0.114 | 0.550 |
| 11 | `features_37` | 512 | 2 | 0.4269 | 0.239 | 0.370 |
| 12 | `features_40` | 512 | 2 | 0.5280 | 0.423 | 0.351 |

### resnet19

| # | layer | CIN | HO | density | always | never |
|---|---|---|---|---|---|---|
| 1 | `layer1_0_conv1` | 64 | 32 | 0.1431 | 0.115 | 0.822 |
| 2 | `layer1_0_conv2` | 128 | 16 | 0.1296 | 0.075 | 0.805 |
| 3 | `layer1_0_shortcut_0` | 64 | 32 | 0.1431 | 0.115 | 0.822 |
| 4 | `layer1_1_conv1` | 128 | 16 | 0.1839 | 0.092 | 0.709 |
| 5 | `layer1_1_conv2` | 128 | 16 | 0.1172 | 0.045 | 0.792 |
| 6 | `layer1_2_conv1` | 128 | 16 | 0.2054 | 0.088 | 0.652 |
| 7 | `layer1_2_conv2` | 128 | 16 | 0.1903 | 0.090 | 0.685 |
| 8 | `layer2_0_conv1` | 128 | 16 | 0.3039 | 0.161 | 0.534 |
| 9 | `layer2_0_conv2` | 256 | 8 | 0.1840 | 0.083 | 0.685 |
| 10 | `layer2_0_shortcut_0` | 128 | 16 | 0.3039 | 0.161 | 0.534 |
| 11 | `layer2_1_conv1` | 256 | 8 | 0.4971 | 0.358 | 0.360 |
| 12 | `layer2_1_conv2` | 256 | 8 | 0.7131 | 0.590 | 0.177 |
| 13 | `layer2_2_conv1` | 256 | 8 | 0.8394 | 0.764 | 0.096 |
| 14 | `layer2_2_conv2` | 256 | 8 | **0.9166** | **0.858** | **0.038** |
| 15 | `layer3_0_conv1` | 256 | 8 | 0.8231 | 0.756 | 0.117 |
| 16 | `layer3_0_conv2` | 512 | 4 | 0.4239 | 0.284 | 0.425 |
| 17 | `layer3_0_shortcut_0` | 256 | 8 | 0.8231 | 0.756 | 0.117 |
| 18 | `layer3_1_conv1` | 512 | 4 | 0.3488 | 0.222 | 0.513 |
| 19 | `layer3_1_conv2` | 512 | 4 | 0.6615 | 0.519 | 0.205 |

Raw data: `profiling/0823_stagewise_verify/input_trace_audit/density_audit.{txt,json}`.
Regenerate with `conda run -n base python profiling/0823_stagewise_verify/input_trace_audit/audit_density.py`.

## What has already been ruled out

Do not spend time re-checking these; they were tested directly.

1. **Not a dtype or units error.** `np.unique` returns exactly `[0, 1]` on all
   31 layers, so `sum/size` is a genuine firing rate.
2. **Not a subsetting artifact.** The committed 5-sample subset is
   bit-identical to the corresponding slice of the full capture on every layer
   compared.
3. **Not a thresholding artifact.** `t=0` has the lowest density in every
   layer, consistent with LIF charging, and the always/never split is graded
   rather than bimodal. These are real spikes with real temporal structure.
4. **The capture is internally coherent.** The three resnet19 shortcut layers
   have densities identical to their block's `conv1`, which is correct because
   a shortcut branch consumes the same input tensor.

The escalation is not uniformly monotonic. vgg16 runs 0.20, 0.58, 0.27, and
resnet19 recovers from 0.82 at layer 15 to 0.42 at layer 16. That argues against
one systemic scale error and for specific layers saturating.

## What the capture code says

The capture code and checkpoints survive in a home snapshot, verified present
2026-08-23 at
`/u/yyu9/.snapshot/snapshot-daily-_2026-08-11_17_00_00_UTC/neuro_cache_trace/`.
**That snapshot expires around 2026-09-10.**

The single most important thing it establishes:

> `capture/run_loas.py` loads **LoAS's own released checkpoints**
> (`model/LoAS/sample_ckpts/{resnet19,vgg16}_final_dict.pth.tar`) against
> LoAS's own `archs/cifarsvhn/{resnet,vgg}` model definitions, on the CIFAR-10
> test set at T=4. Nothing was trained locally.

So this is not a case of a badly trained model of ours. Either the LoAS authors'
published checkpoints genuinely fire this densely, or the capture hooks the
wrong tensor. That reframes question 4 below as the central one: **what sparsity
does the LoAS paper itself report for these exact checkpoints?** If the paper
claims high sparsity for resnet19 and the released checkpoint fires at 0.92 in
its deep layers, something is wrong with the released artifact or with how it is
being run.

Two mechanical details, both checked:

- `InputGrabber` hooks `input[0]` of every `nn.Conv2d` except the first, and
  casts with `.astype(np.uint8)`. Every captured value is exactly 0 or 1, so no
  truncation happened and the hooked tensors really were binary.
- `run_loas.py` never passes `module_filter`, though `InputGrabber` documents it
  as the way to "exclude Conv2d layers that receive non-binary inputs (e.g.
  layers immediately after average pooling)". A real gap, but **not shown to
  explain anything**: uint8 truncation of fractional post-pool values would push
  density down rather than up, and the elevated vgg16 layers are mid-block, not
  post-pool.

---

## Project context, minimum needed

`/u/yyu9/projects/neuro_cache`, branch `wcache-rebuild-phase-a`. A four-stage
pipeline for SNN accelerator modelling:

1. `mip_solver` (Gurobi) solves a loop schedule for a layer against a hardware
   config.
2. `scripts/generate_weight_traces.py` replays real captured spike data against
   that schedule to produce weight-address traces. A `(kh, kw, cin)` position
   emits one address **iff** it fires at least once across the tile's T range;
   silent positions contribute nothing. Input sparsity is the entire mechanism.
3. `src/nocsim` turns that into NoC/DRAM transactions.
4. `src/wcache` simulates the weight cache.

The current run models **LoAS** on a 16-core configuration, NoC global buffer
2 MiB and per-node buffer 32 KiB, both split 30:1:1 across weight/psum/vmem.

Stages 1 and 2 were verified clean on 2026-08-23. In particular an independent
NumPy reimplementation of the weight-trace reconstruction matched the generator
**exactly as integers on all ten samples**, so the density figures above are not
a measurement bug in this repo's tooling.

Full write-up: `profiling/0823_stagewise_verify/CONCLUSIONS.md`.

---

## What the answer changes

| If the literature says | Then |
|---|---|
| Deep-layer density of 0.4 to 0.9 is normal at T=4 | Keep the current layers. The traces are representative and Stages 3-4 proceed as planned. |
| Trained SNNs hold roughly 0.05 to 0.20 throughout | The capture's model is broken. Either swap to healthy layers or retrain and recapture. |
| It depends on the training recipe | Report the recipe our numbers imply, and state the sparsity regime explicitly in any result. |

### If a swap is the answer

- **vgg16 `layer_08_features_27` is free.** Its derived workload is
  `KH3 KW3 CIN512 COUT512 HO4 WO4 T4`, **identical** to the currently used
  `layer_09_features_30`, because a layer's captured tensor is its input and
  layer 8's input is 512 channels at 4x4 with layer 9's CIN as its COUT. Same
  Stage 1 schedule, same tile geometry, density 0.1995 instead of 0.578.
- **resnet19 has no clean equivalent.** Every CIN=512 layer is compromised:
  layer 16 at 0.424, layer 18 at 0.349, layer 19 at 0.662. Going to genuine
  ~0.18 means dropping to `layer_09_layer2_0_conv2` (CIN 256, COUT 128, HO 8).

Cost of switching: one Stage 1 solve and one Stage 2 pass per layer, a few
minutes each. Nothing downstream has run.

## Deliverable wanted back

A short note recording: the density figures real SNNs report on CIFAR-10 at low
T, whether rising-with-depth is normal, what LoAS itself evaluated at, and a
verdict on whether these traces are usable. Cite sources. Append it to this
file or drop it beside as `HANDOFF-ANSWER.md`.
