# SpinalFlow hardware node-size sweep

This demo varies the number of PEs in one SpinalFlow node:
N = 32, 64, 128, 256, and 512. Each hardware configuration runs the same
captured layers and the same five samples. The two curves represent the
VGG16 and ResNet19 captures in `examples/input_trace/loas/`, with four
timesteps and CIFAR-10 input sizes. N denotes hardware width, not a layer's
output-channel count.

The ResNet19 series is a **13-of-19-convolution partial sum**. VGG16
includes all 12 captured convolutions. Network latency here is the sum
of the included layer latencies for one sample,
assuming sequential layer execution and **no inter-layer overlap**. This
is a sum over captured, replayable convolutions, not a model of uncaptured
operations or a full inference software stack.

## Layers and samples

| Capture | Included captured layers | Runs |
|---|---|---:|
| VGG16 | All 12 captured convolutions, layers 01–12 | 300 |
| ResNet19 | All convs except downsample/shortcut: 02, 04–07, 09, 11–14, 16, 18–19 | 325 |

The 625 layer runs yield 50 network/sample totals: two networks × five
hardware sizes × five samples. Sample indices 0–4 in each capture refer
to original capture indices 2697, 3078, 5110, 6367, and 8502. Captured
metadata and spike arrays are used directly without modification.

ResNet19 layers 01, 03, 08, 10, 15, and 17 are excluded. These are stride-2
3×3 convolutions or stride-2 1×1 shortcuts. The replay binary receives no
stride field, and the public trace loader permits only 3×3 stride-1
convolutions. These six layers are precisely the spatial-downsampling
convolutions, so the omission is not uniform across network depth.
`check_replay.py` compares native replay at N=128, sample 0,
against raw NumPy receptive-field counts. The independent reference pads
the raw input by `(kernel-1)//2`, then counts each kernel-sized window
starting at `(ho*stride, wo*stride)` in padded input. A 1×1 shortcut thus
uses one unpadded input pixel; a 3×3 convolution uses nine padded positions.

| Layer | Kernel/stride | Tiles | Differing tiles | Reference cycles | Native cycles |
|---|---|---:|---:|---:|---:|
| ResNet19 08 | 3×3 / 2 | 128 | 126 | 164,200 | 156,796 |
| ResNet19 10 | 1×1 / 2 | 128 | 126 | 21,938 | 19,638 |
| ResNet19 09, control | 3×3 / 1 | 128 | 0 | 196,964 | 196,964 |

Per-tile counts and coordinates are retained in `outputs/feasibility/`.
The ResNet19 curve covers its stated subset; it must not be read as all
19 convolutions or compared with a full-network measurement without
accounting for the omitted layers.

## Architecture and mapping

All five architectures have `single_node: true`, one node, no physical
global buffer, and no inter-node traffic. Weight/psum/vmem widths are
8/16/32 bits. DRAM port occupancy is 0.25 cycles per 32-byte packet.

| N (PEs) | Weight buffer (bytes) | Psum buffer (bytes) | Vmem buffer (bytes) |
|---:|---:|---:|---:|
| 32 | 147,456 | 4,608 | 4,608 |
| 64 | 294,912 | 9,216 | 9,216 |
| 128 | 589,824 | 18,432 | 18,432 |
| 256 | 1,179,648 | 36,864 | 36,864 |
| 512 | 2,359,296 | 73,728 | 73,728 |

Local buffers scale as `weight = 3*3*512*N` and `psum = vmem = 144*N`.
The 144*N psum/vmem allocation preserves the v6 N=128 sizing rather than
being a computed requirement; the per-tile psum need is `2*min(N,COUT)` bytes.
These sizes constrain the scheduler; nocsim does not enforce byte
capacities. The simulator models two logical weight banks. Tile send m
waits for all MACs that consumed tile m-2, and every MAC depends on its
resident tile's actual weight send. Direct DRAM traffic and compute may
overlap subject to those dependencies.

Each manual schedule assigns full KH, KW, CIN, and T temporally to the
node, with `min(N,COUT)` output channels spatially across PEs. Extra lanes
are idle when COUT<N. CIN comes from the captured input tensor and can
differ from COUT, including VGG's channel transitions. Both NoC loop
lists are empty. DRAM loops, outer to inner, are HO → WO → COUT, with
`HO*WO*(COUT/min(N,COUT))` steps. One step covers one output pixel and one
output-channel tile. There is no solver invocation or optimality claim.

## Reproduce

Run from the repository root. The Python environment needs NumPy, PyYAML,
and Matplotlib; a Gurobi solve or license is not needed.

```bash
make -C src/lays/weight_trace_gen/spinalflow
make -C src/lays/nocsim/eventsim
PYTHONPATH=src /u/yyu9/miniconda3/envs/gurobi/bin/python zoo/fig3_hw_n_sweep/check_replay.py
PYTHONPATH=src /u/yyu9/miniconda3/envs/gurobi/bin/python zoo/fig3_hw_n_sweep/gen_inputs.py
setsid env PYTHONPATH=src /u/yyu9/miniconda3/envs/gurobi/bin/python zoo/fig3_hw_n_sweep/run.py --dry-run --jobs 2
setsid env PYTHONPATH=src /u/yyu9/miniconda3/envs/gurobi/bin/python zoo/fig3_hw_n_sweep/run.py --jobs 4 > zoo/fig3_hw_n_sweep/outputs/full_run.log 2>&1
/u/yyu9/miniconda3/envs/gurobi/bin/python zoo/fig3_hw_n_sweep/plot.py
/u/yyu9/miniconda3/envs/gurobi/bin/python zoo/fig3_hw_n_sweep/record_provenance.py
```

`--jobs` bounds the number of independent replay/simulator subprocess
pairs. Each replay request handles one sample. The dry run covers three
cases, including a CIN/COUT transition and idle lanes, in `outputs/smoke/`.
The full run writes per-run progress to `outputs/full_run.log`, exact
commands to `outputs/logs/commands.txt`, and stdout/stderr to per-case log
files. Workload YAMLs, step-cycle traces, and transaction dumps are retained
under `outputs/layers/`, `outputs/weight_traces/`, and `outputs/nocsim/`.
Rerunning replaces this campaign's corresponding outputs. The host has
no usable systemd user bus, so these jobs use `setsid` alone.

The repository's `src/lays/nocsim/combine.py` is modified relative to the
recorded base commit. Its exact source hash and `outputs/combine.patch`
are recorded in provenance; a reproduction from the base revision needs
that patch before running the commands above.

The ignored root directory `neuro_cache_bench_trace/` is a checkout of
`git@github.com:SangYukekeaiai/neuro_cache_bench_trace.git` for a future
100-sample capture workflow. It is not a submodule and is not used by this
five-sample demo. The demo does not regenerate captures.

## Results and figure

`outputs/results.csv` contains one row per layer run:

```text
network,layer,N,sample,total_cycles,count_cycles
```

`outputs/summary.csv` sums layers for each fixed network/N/sample:

```text
network,N,sample,layers,total_cycles,count_cycles,memory_cycles
```

`total_cycles` and `count_cycles` are summed separately. Exposed memory
is their difference, equivalently the sum of the per-layer residuals.
It measures latency beyond compute, not all DRAM service cycles or bytes.
Sample identity is preserved across layers; samples are never pooled
before the network sum.

`plot.py` validates all 625 layer keys and all 50 network totals before
drawing `fig3_hw_n_sweep.pdf` and its 300-dpi PNG preview. At each N, each
network's box shows the 25th–75th percentiles of its five sample totals;
the center line is the median and the whiskers span the full min–max.
Colored lines connect the medians across hardware sizes. The horizontal
positions are equally spaced powers of two, labeled with N. Y-axis tick
suffix M means millions of cycles. These are empirical sample ranges,
not confidence intervals.

The per-sample network totals have these medians (cycles):

| N (PEs) | VGG16, all 12 convs | ResNet19, 13-of-19 partial sum |
|---:|---:|---:|
| 32 | 7,149,601 | 20,966,959 |
| 64 | 3,721,391 | 10,653,942 |
| 128 | 2,620,980 | 5,442,911 |
| 256 | 1,916,012 | 3,378,667 |
| 512 | 1,247,454 | 2,820,690 |

Neither sampled curve reaches a flat plateau. The ResNet19 partial sum
shows diminishing returns at larger widths: successive doublings reduce
its median by 49.2%, 48.9%, 37.9%, and 16.5%. VGG16's corresponding
reductions are 47.9%, 29.6%, 26.9%, and 34.9%; its final interval still
has a substantial decrease. N=512 is the fastest tested setting for both.
Layer-level saturation is measured within the sweep: every layer/sample
total is bit-identical across tested widths N≥COUT for VGG16's
64/128/256-channel groups and ResNet19's 128/256-channel groups.
VGG16's COUT=64 group is flat from N=64 through 512; both networks'
COUT=128 groups are flat from N=128 through 512, and their COUT=256 groups
are flat at N=256 and 512. The COUT=512 groups have only one tested width
at or above COUT. All included layers have COUT≤512, so identical channel
tiles and a network-level floor beyond N=512 remain a model prediction;
no larger N is simulated here.
The ResNet19 trend applies only to its stated partial layer sum.

Exposed memory accounts for VGG16's rebound in total-latency reductions:
its compute-only reductions shrink monotonically (50.0%, 44.4%, 31.9%,
16.2%; ResNet19: 50.0%, 50.0%, 41.9%, 10.2%), while the measured memory
residual peaks at intermediate widths as shown below.

| N | VGG16 median memory (cycles) | Median memory / median total | ResNet19 partial median memory (cycles) | Median memory / median total |
|---:|---:|---:|---:|---:|
| 32 | 11,008 | 0.15% | 9,382 | 0.04% |
| 64 | 148,722 | 4.0% | 112,134 | 1.1% |
| 128 | 636,937 | 24.3% | 203,912 | 3.7% |
| 256 | 566,309 | 29.6% | 351,525 | 10.4% |
| 512 | 114,912 | 9.2% | 84,096 | 3.0% |

Interpretation: per-step compute is independent of N while weight-tile
bytes scale as `9*CIN*min(N,COUT)`, making steps more DRAM-bound as N grows
until N reaches COUT, where a single channel tile can remain resident
across spatial steps; memory medians above are `median(total-count)`,
not the difference of separately computed medians.

Caption: **SpinalFlow latency versus hardware node size.** Boxes show
five sample totals per network and hardware size N, with median lines,
interquartile boxes, and min–max whiskers. Lines connect the medians.
Each total sums the included captured convolutions sequentially without
inter-layer overlap: all 12 VGG16 convolutions and a 13-of-19-convolution
ResNet19 partial sum. ResNet19 layers 01, 03, 08, 10, 15, and 17 are
omitted because replay does not implement stride 2. These are precisely
the spatial-downsampling convolutions, so omission is not uniform across
network depth. Larger N leaves lanes idle
when a layer has fewer output channels. The samples and layer sets are
fixed across N.

The plot uses the lab's chopper style: 3.375-inch width, 8-pt text, blue
`#648FFF` and gold `#FFB000`, a solid y grid, and an unframed upper legend.
No Gill Sans TTF is present in the campaign directory, so the export uses
Matplotlib's default DejaVu Sans and prints one warning. A `GIL*.TTF/ttf`
placed in this directory is registered and used on subsequent exports.
PDF creation timestamps are omitted; the PDF is vector graphics.
`provenance.json` records inputs, source, binaries, commands, environment,
and result/figure hashes. Its wording describes the recorded artifacts.
