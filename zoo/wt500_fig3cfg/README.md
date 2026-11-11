# wt500_fig3cfg: input configs for the 5-arch x 8-benchmark x 500-sample weight-trace campaign

Status: **configs for user review**; nothing has been solved or generated from
them yet. Plan: `docs/plans/2026-11-10-weight-trace-500-campaign-plan.md`.

## Files

| File | Role |
|---|---|
| `sweep_config.yaml` | One-file listing of the whole weight-trace sweep (axes, inputs, order, outputs) |
| `arch.yaml` | Campaign hardware (one fixed multi-node LAYS config, shared by all 5 archs) |
| `mapspaces/loas.yaml` | LoAS node-mapspace |
| `mapspaces/ptb.yaml` | PTB node-mapspace (**review flag inside: T 64 vs 32**) |
| `mapspaces/spinalflow.yaml` | SpinalFlow node-mapspace |
| `mapspaces/prosperity.yaml` | Prosperity node-mapspace |
| `mapspaces/gustavsnn.yaml` | GustavSNN node-mapspace |

## Hardware (`arch.yaml`): diffs from `zoo/fig3_design_space/arch.yaml`

| Field | fig3 | campaign | Why |
|---|---:|---:|---|
| `num_pes` per node | 32 | **4** | user: each node limited to exactly 4 PEs |
| L1 (node) weight scratchpad | 30,720 B | **32,768 B** (32 KB) | user correction |
| L2 (global buffer) weight | 1,966,080 B | **2,097,152 B** (2 MB) | user correction (was 15/16 of 2 MB) |
| `problem:` block | fig3 showcase layer | **removed** | workloads come from each benchmark's `meta.json` |

Unchanged: 16 nodes, L1 psum/vmem 1,024 B, L2 psum/vmem 65,536 B, bitwidths
8/16/32, `DRAM_LATENCY: 0.25`, `single_node: false`, inter-node fanout <= 16.
Total PEs: 16 nodes x 4 = 64.

## Mapspaces: diffs from `zoo/fig3_design_space/mapspaces/`

| Arch | fig3 variant | Campaign change |
|---|---|---|
| loas | `loas_t4.yaml`: T {spatial: 4} | **T: full** (back to published `examples/node_mapspace/loas.yaml`) |
| ptb | `ptb_t4.yaml`: T {spatial: 4} | **T: 64**, the published window. User recalled 32; the previous config (`examples/node_mapspace/ptb.yaml`) says 64, matching PTBGen.h (TW_SIZE 8 x 8 columns). **Confirm on review.** |
| spinalflow | `spinalflow_fig3.yaml` | kept as-is |
| prosperity | `prosperity_fig3.yaml` | kept as-is (CIN 16 residency: see bridge note in the file) |
| gustavsnn | `gustavsnn_fig3.yaml` | kept as-is |

Spatial-budget check against `num_pes: 4`: every mapspace's node spatial
product is exactly 4 (loas/ptb/spinalflow/prosperity COUT 4; gustavsnn
COUT 2 x HO 2), so no idle or over-subscribed lanes.

## Benchmarks and samples (fixed inputs, not files here)

8 captures under `/work/nvme/bebv/yyu9/input_trace_delta/` (A02, A04, A07,
A08, B09 vgg16, B09 resnet19, C01 cifar10-dvs, C01 dvs128-gesture), all
`n_samples: 500`; the campaign runs **all 500 samples** of every valid layer.
GustavSNN executes last. See the plan for the stage list (schedule solve on
DeltaAI, generation on Stokes, delivery back to DeltaAI).
