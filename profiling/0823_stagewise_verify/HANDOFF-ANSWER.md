# Handoff answer: the density is real, and it is LoAS's

Written 2026-08-23 from a literature survey (12 papers deep-read, 7 more read
to figure depth, 88-paper database) filed in the Obsidian vault at
`research/surveys/snn-spike-sparsity-cifar10/`. Every number below is cited;
every link was fetched and verified. "Density" = spikes per neuron per timestep
(fraction of 1s in the binary tensor); sparsity = 1 - density.

## Short version

1. **The capture is correct.** Converted into LoAS's own measurement, the
   project's traces reproduce the authors' released profiling output to within
   0.03-3.3 points on four independent statistics.
2. **The ~0.10 expectation was the error.** It is a citation-chain figure that
   LoAS's introduction repeats ("~90%") and LoAS's own Table II contradicts:
   ResNet19 is 68.6% sparse, i.e. **0.314 dense**, and its deepest reported
   layer is **0.421 dense**.
3. **0.7-0.92 in a deep layer is still outside every published profile.** The
   literature reports 0.4-0.5 in individual layers; nobody reports a trained
   binary layer above ~0.57, and the ResNet-19 architecture's own paper shows
   density *falling* with depth.
4. **Verdict:** usable as a *stated low-sparsity stress case tied to a real
   published artifact*, not as a representative workload. Swap vgg16 to
   `features_27`; for resnet19 either take `layer_09_layer2_0_conv2` or keep
   the dense layer and label it.

## 1. What LoAS reports for these exact checkpoints

Source: the paper ([Yin et al., MICRO 2024](https://doi.org/10.1109/MICRO61859.2024.00084),
arXiv [2407.14073](https://arxiv.org/abs/2407.14073)) and the repo
[RuokaiYin/LoAS](https://github.com/RuokaiYin/LoAS).

**Table II of the paper** (all values are *sparsity* in %, measured on the
im2col-lowered spike matrix; "packed" = fraction of neurons silent across all T;
parenthesis = after masking once-firing neurons and fine-tuning):

| workload | NL | T | AvSpA origin | AvSpA packed (+FT) | AvSpB (weights) |
|---|---|---|---|---|---|
| AlexNet | 7 | 4 | 81.2 | 71.3 (76.7) | 98.2 |
| VGG16 | 14 | 4 | 82.3 | 74.1 (79.6) | 98.2 |
| **ResNet19** | 19 | 4 | **68.6** | 59.6 (66.1) | 96.8 |
| V-L8 (4,16,512,2304) | | 4 | 88.1 | 76.5 (86.8) | 96.8 |
| **R-L19** (4,16,512,2304) | | 4 | **57.9** | 51.4 (55.7) | 99.1 |

So the paper's own numbers are **0.177 density for vgg16, 0.314 for resnet19,
0.421 for its deepest resnet19 layer**. Section IV-A summarizes the silent
fraction as "60% ~ 70%". Fig. 16(b) shows the silent ratio *falling* as T goes
4 to 8 (0.92x, 0.91x). There is **no per-layer density table and no statement
about density versus depth** anywhere in the paper.

**Recipe:** T=4; 15 rounds of lottery-ticket pruning to 96.8-98.2% weight
sparsity, then fine-tuning; spikingjelly LIF with `tau = 1/(1-0.25)`,
`Vth = 1`, ATan surrogate, hard reset (from `archs/cifarsvhn/resnet.py`). The
paper never names the dataset, TET, or tdBN. The released ResNet19 is a
64-128-256-512 network, not Zheng's 128-256-512 ResNet-19.

**The "~90%" claim:** Sec. II-B says SNN output sparsity is "usually much
higher (~90%)" and cites four earlier papers, two of them the same group's.
That sentence, not the measurement, is where the 0.10 expectation came from.

**Repo:** `artifact/Table-II/reference.txt` is the authors' own profiling
output for `sample_ckpts/`: vgg16 82.325% / 74.09%, resnet19 68.667% / 59.59%
(original / packed). `loas_input_convert.py` defines the measurement:
`1 - nnz/numel` over the lowered `(T, Ho*Wo, k*k*Cin)` matrix, batch 1,
element-weighted across layers. `model_profile.py` + `utils.py::hook_fn` hook
`input[0]` of every `nn.Conv2d` except the first, the same as `InputGrabber`.
README lists no known checkpoint problems; no issues mention sparsity.

## 2. Does the capture reproduce the artifact? Yes.

Two differences between the audit and LoAS's script: LoAS measures the
**lowered** matrix (which includes zero-padding entries: 30.6% of a 3x3 pad-1
conv on a 4x4 map, 16% on 8x8, 8% on 16x16) and aggregates **element-weighted**;
the audit measures the raw `[T,Cin,H,W]` tensor and averages layers
unweighted. Converting the audit's per-layer numbers into LoAS's space
(script: vault `phase5_synthesis/loas_comparable.py`):

| statistic | LoAS `reference.txt` | project audit, converted | gap |
|---|---|---|---|
| vgg16 spike sparsity | 82.325% | 82.56% | 0.24 pt |
| vgg16 silent-neuron sparsity | 74.09% | 74.06% | 0.03 pt |
| resnet19 spike sparsity | 68.67% | 71.98% | 3.3 pt |
| resnet19 silent-neuron sparsity | 59.59% | 62.92% | 3.3 pt |
| vgg16 `Layer_7` = audit #7 `features_24` | 88.07% | 89.36% | 1.3 pt |

The silent-neuron check uses the audit's `never` column, the spike check uses
`density`; both land on the authors' figures. **The hooks capture the right
tensor and the released checkpoint really fires this densely.** Items already
ruled out in HANDOFF.md stand.

One open detail: the paper's `R-L19` shape `4,16,512,2304` is identical to
`V-L8`'s and implies Cin=256, while every 19th-layer candidate has Cin=512;
likely a copy error in Table II. `artifact/Table-II/src_matrices/resnet19_final_matrices_dict.pth`
(93 MB, CPU-loadable, no dataset needed) holds LoAS's own per-layer matrices,
so all 19 layers can be compared offline in under an hour.

## 3. Comperity's benchmark set

[Zhou et al., ACM TACO vol. 23 no. 3, 2026](https://doi.org/10.1145/3828526),
CC-BY, NUDT / Academy of Military Science / Qiyuan Lab. Full text obtained via
a text proxy (dl.acm.org returns 403 to fetchers). **No code, no checkpoints,
and no timestep count appear anywhere in the article.** Models are "implemented
in SpikingJelly/PyTorch following the hyperparameters of their original
publications".

| network | dataset | T | reported spike density | adjacent-row Jaccard | checkpoint source |
|---|---|---|---|---|---|
| VGG16 | CIFAR-10 | not stated | 9.9% | 0.333 | not stated |
| VGG16 | CIFAR-100 | not stated | 23.0% | 0.461 | not stated |
| ResNet18 | CIFAR-10 | not stated | 9.8% | 0.296 | not stated |
| Spikformer | CIFAR-10 | not stated | 13.8% | 0.329 | not stated |
| Spike-driven Transformer | CIFAR-10 | not stated | 12.5% | 0.290 | not stated |
| SpikeBERT | SST-2 | not stated | 7.1% | 0.956 | not stated |
| SpikeBERT | MR | not stated | 16.8% | 0.580 | not stated |
| SpikingBERT | SST-2 | not stated | 14.4% | 0.515 | not stated |

Sec. 7.1 also lists CIFAR10-DVS, QQP and MNLI; none appears in any table or
figure. All densities are network averages; no per-layer data. Baselines:
Eyeriss-like dense (168 PE), PTB (128 PE), MINT (128 PE), Prosperity (128 PE,
TCAM), iso-28 nm / 500 MHz; A100 running SpikingJelly; Loihi and TrueNorth as
analytical SynOp references. The 1.62x over Prosperity uses 8x128 PEs; at
iso-PE (Table 3) Prosperity leads 16.2x vs 2.72x over dense.

**Prosperity** ([Wei et al., HPCA 2025](https://doi.org/10.1109/HPCA61900.2025.00066))
evaluates the same family and ships layer-keyed activation `.pkl`s in its
artifact, but its VGG-16 / ResNet-18 run at **T=32** (only visible in the
artifact's `configs.py`); the T=4 members are VGG-9 (13.5%), Spikformer
(14.9%), SDT (14.6%), SpikeBERT (13.2%). **Phi** ([Wei et al., ISCA 2025, arXiv](https://arxiv.org/abs/2505.10909))
gives VGG16-C10 8.7%, ResNet18-C10 7.4%.

## 4. Broader survey: density ranges, depth trend, accelerator assumptions

### (a) Typical density

| source | workload | T | density | metric |
|---|---|---|---|---|
| [LoAS](https://doi.org/10.1109/MICRO61859.2024.00084) Table II | AlexNet / VGG16 / ResNet19 C10, pruned | 4 | 0.188 / 0.177 / **0.314** | lowered-matrix, network |
| [Comperity](https://doi.org/10.1145/3828526) Table 5 | VGG16 / ResNet18 C10 | ? | 0.099 / 0.098 | network |
| [Prosperity](https://doi.org/10.1109/HPCA61900.2025.00066) | VGG-9 C10 | 4 | 0.135 | network bit density |
| [Phi](https://arxiv.org/abs/2505.10909) Table 4 | VGG16 / ResNet18 C10 | ? | 0.087 / 0.074 | network |
| [MINT](https://arxiv.org/abs/2305.09850) | VGG-9 C10 | 8 | 0.094-0.141 | network |
| [Diet-SNN](https://doi.org/10.1109/TNNLS.2021.3111897) Table 3 | VGG16 / ResNet-20 C10 | 5 | 0.078 / 0.152 | spikes/neuron over T, divided by T |
| [SATA](https://doi.org/10.1109/TCAD.2022.3213211) Table VI | VGG5 C10 | 8 | input 0.565, conv1 0.142, conv2 0.084, conv3 0.016 | per layer per timestep |
| [tdBN](https://doi.org/10.1609/aaai.v35i12.17320) Supp. Fig. 6 | ResNet-19 C10 | 2-6 | 1.93 (conv1) to 0.23 (L16) spikes/neuron over T; mean 0.77 (~0.13/step at T=6) | figure read-off |
| [MS-ResNet](https://doi.org/10.1109/TNNLS.2024.3355393) Fig. 3a | ResNet34 / 104 ImageNet | 6 / 5 | layer range 0.03-0.513; network 0.225 / 0.192 | per layer |
| [SEW-ResNet](https://arxiv.org/abs/2102.04159) Fig. 4 | ResNet-18..152 ImageNet | 4 | early 0.05-0.15, mid 0.2-0.44, last blocks ~0; ceiling 0.25 (<=50L), 0.5 (101/152L) | residual-branch neuron |
| [Spike-driven Transformer](https://doi.org/10.52202/075280-2798) Table S1 | SDT-8-512 ImageNet | 4 | block inputs 0.34-0.41, MLP-L1 0.35-0.43, attention to 1e-5 | nonzero ratio per timestep |
| [Shen et al.](https://arxiv.org/abs/2311.10802) Fig. 6 | 29-layer C100 | 4 | 0.02-0.34, most layers 0.15-0.31 | per layer |
| [PTB](https://doi.org/10.1109/HPCA53966.2022.00031) | DVS-Gesture / CIFAR10-DVS | 300 / 100 | 0.01-0.15 | per-layer medians |
| [TET](https://arxiv.org/abs/2202.11946) | ResNet-19 C10 | 2-6 | **no firing number anywhere** | - |

Network averages for CIFAR CNNs at T=4-8 cluster at **0.07-0.19**; ResNet-class
nets run denser (0.15-0.31). First-conv layers are the outlier (0.57 in SATA).
Spiking transformers are densest, 0.34-0.43 in block inputs.

### (b) Depth trend, and is 0.4-0.9 ever normal?

- **Falls with depth** in the VGG family (SATA 0.565 to 0.016; BNTT
  [Kim & Panda](https://arxiv.org/abs/2010.01729) Fig. 4a; Lu & Sengupta
  [Fig. 6](https://arxiv.org/abs/2002.10064); Diet-SNN front-loaded with a
  mid rebound). For **ResNet-19 on CIFAR-10 specifically**, tdBN's own
  supplementary shows a slow monotone fall (1.07 / 0.74 / 0.45 spikes per neuron
  by thirds; "as the network goes deeper, the firing rates also decrease
  slowly"). MS-ResNet falls through stages 1-3 (0.341 / 0.262 / 0.143) and
  recovers modestly in stage 4; Diet-SNN explains the mechanism (learned
  thresholds rise, leaks fall with depth).
- **Some rise** exists: SEW-ResNet's residual-branch neuron goes 0.05-0.15
  early to 0.2-0.44 mid-depth, then collapses to 0 in the last blocks; Shen et
  al. rise mildly from ~0.19 to ~0.31; LoAS's R-L19 (0.421) exceeds its
  network mean (0.314). Spikingformer's 0.88 ([Fig. 3a](https://arxiv.org/abs/2304.11954))
  is the nonzero ratio of an integer SEW-style tensor, not a spike density; the
  binary model beside it is flat at 0.32-0.36.
- **0.4-0.5 in a single deep layer: reported** (LoAS R-L19 0.421; SDT MLP-L1
  0.456 in one block; MS-ResNet 0.513 at layer 1).
- **0.6-0.92, with 86% of neurons firing at every timestep: not reported
  anywhere** as the steady state of a trained binary layer. MS-ResNet credits
  its low rate to "the large number of silent neurons"; SEW-ResNet's only
  defect is the opposite silence problem.

### (c) What each accelerator assumes

| accelerator | assumed / measured sparsity | how obtained |
|---|---|---|
| [SpinalFlow](https://doi.org/10.1109/ISCA45697.2020.00038) ISCA'20 | 90% headline, 60/98% bounds | assumed from two citations; never measured; 1.18x *worse* than Eyeriss at 60% |
| [SATO](https://doi.org/10.1145/3489517.3530592) DAC'22 | density = 1/T | single-spike temporal code; only 2.9x over SpinalFlow at T=4 |
| [PTB](https://doi.org/10.1109/HPCA53966.2022.00031) HPCA'22 | 1-15% density | measured on DVS at T=100-300; speedup *rises* with density |
| [LoAS](https://doi.org/10.1109/MICRO61859.2024.00084) MICRO'24 | 68.6-82.3% sparsity | measured on own pruned CIFAR nets; speedup never swept vs spike sparsity |
| [Stellar](https://doi.org/10.1109/HPCA57654.2024.00023) HPCA'24 | unknown | no free full text; abstract only |
| [Prosperity](https://doi.org/10.1109/HPCA61900.2025.00066) HPCA'25 | 9-34% density, geomean 15.7% | measured; CNNs at T=32 |
| [Phi](https://arxiv.org/abs/2505.10909) ISCA'25 | 7-15% | measured; T unstated |
| [Comperity](https://doi.org/10.1145/3828526) TACO'26 | 7-23% | measured; T unstated |

## 5. Verdict against the "What the answer changes" table

The literature answer is the third row, **"it depends on the recipe"**, with a
sharp edge: LoAS's LTH-pruned resnet19 at T=4 genuinely runs at 0.31 mean /
0.42 deep-layer density, and the project's traces are that checkpoint. The
0.7-0.92 layers are beyond anything published, but they are what the released
artifact does. Whether 15 rounds of pruning to 96.8% weight sparsity drove the
surviving weights to fire denser is a plausible mechanism and an **inference,
not a finding**; no paper measures it.

| trace | as-is | as stated stress case | broken |
|---|---|---|---|
| vgg16 `features_27` (0.20) | yes: matches the 0.18-0.20 LoAS / literature band | | |
| vgg16 `features_30` (0.58) | no | yes, at the top of the published range (SATA input 0.565) | no |
| resnet19 `layer_09` (0.18) | yes | | |
| resnet19 CIN=512 layers (0.35-0.66) | no | yes, labelled as LoAS-pruned-resnet19 | no |
| resnet19 `layer2_2_conv2` (0.92) | no | only with the label "outside every published profile" | not broken, but not representative |

**Layer-swap recommendation.**
- **vgg16: swap to `layer_08_features_27`.** Identical Stage 1 workload
  (`KH3 KW3 CIN512 COUT512 HO4 WO4 T4`), density 0.20 sits inside the
  published band, and the audit's `features_24` reproduces LoAS's own V-L8
  number to 1.3 points, which makes the neighbouring layers trustworthy.
- **resnet19: no CIN=512 layer is representative.** `layer_09_layer2_0_conv2`
  (CIN 256, COUT 128, HO 8, density 0.18) is the honest choice for a
  "typical" layer; it matches the 0.15-0.19 band for ResNet-class CIFAR nets
  and tdBN's mid-network 0.13/step. If a CIN=512 shape matters more than
  density, keep `layer3_0_conv2` (0.42, matching LoAS's own R-L19 0.421) and
  state that density in every result.
- Run both regimes rather than choosing: the accelerator's value proposition
  is a function of density, and the survey shows the field's own workloads
  span 0.07 to 0.42.

**Comperity's benchmark set: adopt the workload list, not the paper's
checkpoints, because there are none.** The set (VGG16 / ResNet18 / Spikformer
/ SDT on CIFAR-10, SpikeBERT on SST-2 / MR, SpikingBERT on SST-2) is shared
with Prosperity and Phi and is where the field is going; Comperity gives no
T, no code and no per-layer data. The practical route is Prosperity's artifact
(layer-keyed activation `.pkl`s, `print_sparsity` helper), restricted to its
T=4 members (VGG-9, Spikformer, SDT, SpikeBERT), plus a public tdBN/TET
ResNet-19 checkpoint captured with the existing hooks so accuracy and density
are reported together. Report density per layer in every result; no paper in
the corpus does, and it is the number the whole speedup depends on.

## 6. Cheapest next checks (no GPU, no dataset)

1. Load `artifact/Table-II/src_matrices/resnet19_final_matrices_dict.pth`
   from the LoAS repo and print per-layer `1 - nnz/numel` for all 19 layers;
   compare against the audit's converted numbers layer by layer. Resolves the
   `R-L19` shape question and confirms the 0.92 layer is in the authors' own
   matrices.
2. Run `model_profile.py -profile --n_mask 0` from the snapshot copy of the
   repo; its per-layer `[0 spikes .. 4 spikes]` histogram is the authors' own
   `always` / `never` split for comparison with the audit's columns.

Vault survey (full report, per-paper notes, DB, search log):
`/home/ya867177/obsidian_vault/research/surveys/snn-spike-sparsity-cifar10/`.
