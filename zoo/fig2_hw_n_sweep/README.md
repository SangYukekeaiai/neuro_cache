# SpinalFlow hardware node-size sweep

This campaign varies the number of PEs in one SpinalFlow node:
N = 32, 64, 128, 256, and 512. It covers four networks, each from its own
500-sample capture under `/lustre/fs1/home/ya867177/data/input_trace_delta`,
and runs the deterministic 100-sample subset selected by
`sample_indices(n=100, seed=0, n_total=500)`. The old five-sample
VGG16/ResNet19 demo outputs remain untouched.

| Network | Capture directory |
|---|---|
| ResNet19 | `B09/loas_resnet19_T4_n500` |
| VGG16 | `B09/loas_vgg16_T4_n500` |
| SDT | `A04/sdt_2_512_T4_n500` |
| VGG8-DVS | `C01/sma_azo_vgg_cifar10_dvs_T10_n500` |

Every series is a partial sum over that network's captured, replayable
convolutions. Network latency is the sum of the included layer latencies for
one sample, assuming sequential layer execution and **no inter-layer overlap**.
The ResNet19 series is a **13-of-19-convolution partial sum**. These are sums
over captured, replayable convolutions, not a model of uncaptured operations or
a full inference software stack.

## Layers and samples

A network's included layer set is whatever the public loader admits for its
capture: 1×1 (PAD=0) or 3×3 (PAD=1) convolutions with stride 1 and positive
output spatial dimensions. Every other captured layer is excluded, with the
reason recorded per layer. Each network has its own feasibility report, and
`gen_inputs.py` checks three separate things about it before building any
input. It compares the report's `valid_layers` against the layer set derived
from the capture's `meta.json`, so a stale report cannot silently change the
included set. It compares the report's `trace` against the capture path
configured for that network in `NETWORKS`, so a report cannot be paired with
the wrong capture. And it asserts that `stride2_supported` is false outright,
rather than comparing it with anything: a report claiming stride-2 support
stops the run until the public loader is reassessed.

| Capture | Feasibility report | Included captured layers |
|---|---|---|
| ResNet19 n500 | `outputs/feasibility/report.json` | 13 of 19: 02, 04–07, 09, 11–14, 16, 18–19 (stride-1 convolutions) |
| VGG16 n500 | `outputs/feasibility/vgg16/report.json` | 13, per that report's `valid_layers` |
| SDT n500 | `outputs/feasibility/sdt/report.json` | 16, per that report's `valid_layers` |
| VGG8-DVS n500 | `outputs/feasibility/vgg8dvs/report.json` | 6, per that report's `valid_layers` |

ResNet19 is the only network with excluded layers: six of its 19 captured
convolutions are left out, and VGG16, SDT, and VGG8-DVS have every captured
layer included. ResNet19 keeps its report at the feasibility root; each other
network has a subdirectory named after the network. `inputs/manifest.json`
records, for every network, its `arch`, `trace`, `feasibility` path,
`included_layers`, and `excluded_layers` with the reason for each.

One layer run is one (network, layer, N, sample). The campaign runs every
included layer of every network at all five hardware sizes for all 100 selected
samples: 48 included layers across the four networks, so 24,000 layer runs,
yielding 2,000 network/sample totals (four networks × five hardware sizes × 100
selected samples). Of those layer runs, 6,500 are the ResNet19 ones already
merged and carried rather than re-run, and 17,500 are the VGG16, SDT, and
VGG8-DVS ones added by the extension. The per-network layer sets are listed in
`inputs/manifest.json`, along with the exact selected indices under
`sample_selection.indices`, which every Slurm case manifest repeats. Captured metadata and spike arrays are used directly
without modification.

ResNet19 layers 01, 03, 08, 10, 15, and 17 (with the trace's `core_` infix)
are excluded. These are stride-2 3×3 convolutions or stride-2 1×1 shortcuts.
The replay binary receives no stride field, and the public trace loader permits
only 1×1 or 3×3 stride-1 convolutions. These six layers are precisely the
spatial-downsampling convolutions, so the omission is not uniform across depth.

`check_replay.py` runs the same comparison for each of the four networks. Per
capture it selects up to two stride-2 excluded layers, the first included
layer, and the first included 1×1 layer, and compares native replay at N=128,
sample 0, against raw NumPy receptive-field counts. The independent reference pads
the raw input by `(kernel-1)//2`, then counts each kernel-sized window
starting at `(ho*stride, wo*stride)` in padded input. A 1×1 shortcut thus
uses one unpadded input pixel; a 3×3 convolution uses nine padded positions.

It requires every stride-1 control to agree exactly, and records
`stride2_supported` as true only if stride-2 cases were checked and all of them
agreed; a capture with no replayable layer at all is rejected. `gen_inputs.py`
in turn refuses to build inputs for any network whose report claims stride-2
support. The ResNet19 cases are:

| Layer | Kernel/stride | Tiles | Differing tiles | Reference cycles | Native cycles |
|---|---|---:|---:|---:|---:|
| ResNet19 01 | 3×3 / 2 | 256 | 254 | 50,709 | 45,435 |
| ResNet19 03 | 1×1 / 2 | 256 | 252 | 5,883 | 5,382 |
| ResNet19 02, control | 3×3 / 1 | 256 | 0 | 144,914 | 144,914 |

Per-tile counts and coordinates are retained in `outputs/feasibility/`:
ResNet19 at the root, each other network in its own subdirectory. Every curve
covers only its network's stated subset; none must be read as that network's
full convolution set or compared with a full-network measurement without
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
differ from COUT across residual stages. Both NoC loop
lists are empty. DRAM loops, outer to inner, are HO → WO → COUT, with
`HO*WO*(COUT/min(N,COUT))` steps. One step covers one output pixel and one
output-channel tile. There is no solver invocation or optimality claim.

## Reproduce

Run from the repository root. The Python environment needs NumPy, PyYAML,
and Matplotlib; a Gurobi solve or license is not needed. The validated Python
interpreter is `/lustre/fs1/home/ya867177/.venvs/neuro_cache_wcache/bin/python`.

```bash
PY=/lustre/fs1/home/ya867177/.venvs/neuro_cache_wcache/bin/python
make -C src/lays/weight_trace_gen/spinalflow
make -C src/lays/nocsim/eventsim
PYTHONPATH=src $PY zoo/fig2_hw_n_sweep/check_replay.py
PYTHONPATH=src $PY zoo/fig2_hw_n_sweep/gen_inputs.py
PYTHONPATH=src:zoo/fig2_hw_n_sweep/slurm $PY zoo/fig2_hw_n_sweep/slurm/shard_cases.py \
  --batch-samples --num-shards 250 --cases-per-shard 100 \
  --output-dir zoo/fig2_hw_n_sweep/outputs/slurm/n500-cases \
  --shard-root zoo/fig2_hw_n_sweep/outputs/slurm/n500-runs
# shard_cases.py prints the exact sbatch line; SHARDS is the shard count it reports
SHARDS=<shards printed above>
sbatch --partition=normal --time=90:00 --cpus-per-task=4 --array=0-$((SHARDS-1))%$SHARDS \
  zoo/fig2_hw_n_sweep/slurm/run_array.sbatch \
  --case-dir zoo/fig2_hw_n_sweep/outputs/slurm/n500-cases \
  --shard-root zoo/fig2_hw_n_sweep/outputs/slurm/n500-runs \
  --batch-samples
PYTHONPATH=src:zoo/fig2_hw_n_sweep/slurm $PY zoo/fig2_hw_n_sweep/slurm/assemble_shards.py \
  --manifest zoo/fig2_hw_n_sweep/outputs/slurm/n500-cases/manifest.json \
  --source zoo/fig2_hw_n_sweep/outputs/slurm/n500-cases/manifest.json \
           zoo/fig2_hw_n_sweep/outputs/slurm/n500-runs \
  --output-root zoo/fig2_hw_n_sweep/outputs/slurm/n500-assembled-runs
PYTHONPATH=src:zoo/fig2_hw_n_sweep/slurm $PY zoo/fig2_hw_n_sweep/slurm/merge_results.py \
  --manifest zoo/fig2_hw_n_sweep/outputs/slurm/n500-cases/manifest.json \
  --shard-root zoo/fig2_hw_n_sweep/outputs/slurm/n500-assembled-runs \
  --output-dir zoo/fig2_hw_n_sweep/outputs
PYTHONPATH=src $PY zoo/fig2_hw_n_sweep/plot.py
PYTHONPATH=src $PY zoo/fig2_hw_n_sweep/record_provenance.py
```

To run only part of the campaign, restrict the manifest with
`shard_cases.py --networks`, which takes one or more names (space-separated, or
comma-separated within one value) out of `resnet19 vgg16 sdt vgg8dvs`. An
unknown name is a usage error, and `--networks` cannot be combined with the
single-value `--network`. The three networks added to the ResNet19 campaign are
sharded and run this way, then merged with `--carry-existing`. Their 35
included layers give 17,500 cases in 175 shards: 175 `(layer, N)` groups of 100
samples each, one group per shard at `--cases-per-shard 100`.

```bash
PYTHONPATH=src:zoo/fig2_hw_n_sweep/slurm $PY zoo/fig2_hw_n_sweep/slurm/shard_cases.py \
  --networks vgg16 sdt vgg8dvs \
  --batch-samples --num-shards 250 --cases-per-shard 100 \
  --output-dir zoo/fig2_hw_n_sweep/outputs/slurm/n500-ext-cases \
  --shard-root zoo/fig2_hw_n_sweep/outputs/slurm/n500-ext-runs
# then the printed sbatch line, with --case-dir/--shard-root above
PYTHONPATH=src:zoo/fig2_hw_n_sweep/slurm $PY zoo/fig2_hw_n_sweep/slurm/merge_results.py \
  --manifest zoo/fig2_hw_n_sweep/outputs/slurm/n500-ext-cases/manifest.json \
  --shard-root zoo/fig2_hw_n_sweep/outputs/slurm/n500-ext-runs \
  --output-dir zoo/fig2_hw_n_sweep/outputs \
  --carry-existing
```

`--carry-existing` keeps the ResNet19 results already in `outputs/`: ResNet19 is
never re-simulated for the extension. The flag requires both `results.csv` and
`summary.csv` to be present in `--output-dir`, re-validates them as exactly the
full ResNet19 case set (its included layers × five hardware sizes × 100
samples) with no duplicates, recomputes the existing summary from the existing
result rows and requires a match, and refuses the merge if any carried row
overlaps a case in the shard manifest. The carried rows are then concatenated
ahead of the newly merged rows and the union is validated again.

Without `--carry-existing`, a merge that would drop data refuses to run: if
`outputs/results.csv` contains a network that the shard manifest does not,
`merge_results.py` exits naming those networks and telling you to rerun with
`--carry-existing`. A merge whose manifest covers all four networks therefore
needs no flag.

`--batch-samples` pays the weight-trace generator startup and trace load once
per `(layer, N)` group with `--sample-count 100 --sample-total 500`; nocsim
still runs once per selected sample. The Slurm manifest keeps each batch group
whole and empty trailing array tasks are never materialized, so one task holds
100 cases, the array length is the printed shard count, and at most 250 shards
are allowed. The harness writes per-shard progress, commands, native logs, and
cycle results; `merge_results.py` validates every manifest layer key exactly
once before writing the final results and summary. `assemble_shards.py` maps
each source round to the target shard by its exact case set, checks equivalent
rerun results, and renames command logs to the target shard index before
merging. If reruns are
needed, pass each rerun manifest and shard root as another `--source` pair;
`rerun_missing.py` emits the reduced manifest and time-limited array command.
The host has no usable systemd user bus, so these jobs use `setsid` alone.

The repository's `src/lays/nocsim/combine.py` behavior is already included in
the current repository commit. No external combine patch or separate checkout
is required to reproduce the commands above.

The current `outputs/results.csv` and `outputs/summary.csv` hold the merged
four-network n500 campaign: 24,000 layer runs and 2,000 network/sample totals,
500 totals per network. Of the layer runs, 6,500 are the carried ResNet19 runs
and the rest came from the `--carry-existing` merge above — 6,500 VGG16, 8,000
SDT, and 3,000 VGG8-DVS.
Validation uses separate ignored output directories and does not overwrite the
campaign results.

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

`plot.py` derives its expected keys from `inputs/manifest.json` and validates
every layer key and every network/sample total, and re-derives each summary row
from its layer rows, before drawing `fig2_hw_n_sweep.pdf` and its 300-dpi PNG
preview. At each N it draws one box per network, offset from the tick by
0.18 per network slot, each box showing the 25th–75th percentiles of that
network's 100 sample totals; the center line is the median and the whiskers span
the full min–max. One line per network connects its medians across hardware
sizes. These are empirical sample ranges, not confidence intervals.

The y axis is logarithmic in cycles, with limits taken from the pooled data of
all networks. Equal vertical distances are therefore equal ratios, which is the
reading the saturation section below depends on: proportional scaling with N
would place a network's five medians on a straight line of constant slope, and
the measured ResNet19 medians instead flatten as N grows, with the vertical step
between successive N shrinking from 32 → 64 to 256 → 512. A log axis excludes
zero, so the axis is bounded by the data rather than anchored at the origin, and
the interquartile boxes at the larger N appear taller relative to their medians
than a linear axis would render them.

The ResNet19 series' median metrics are:

| N (PEs) | Median total cycles | Median count cycles | Median memory cycles | Median memory / total |
|---:|---:|---:|---:|---:|
| 32 | 20,640,842 | 20,629,030 | 9,396 | 0.05% |
| 64 | 10,450,763.5 | 10,314,515 | 116,077 | 1.11% |
| 128 | 5,352,196.5 | 5,157,257.5 | 192,321 | 3.59% |
| 256 | 3,379,137.5 | 3,022,898.5 | 353,750.5 | 10.47% |
| 512 | 2,811,275.5 | 2,727,179.5 | 84,096 | 2.99% |

## Saturation

The numbers in this section are the ResNet19 series. Each doubling of N removes
less latency than the one before it. Reductions in the median total, computed
from the medians above:

| Step | Median total | Median compute (`count_cycles`) |
|---|---:|---:|
| 32 → 64 | 49.4% | 50.0% |
| 64 → 128 | 48.8% | 50.0% |
| 128 → 256 | 36.9% | 41.4% |
| 256 → 512 | 16.8% | 9.8% |

The first two doublings are close to the ideal halving. The third returns
36.9%, and the fourth returns 16.8%, so going from 256 to 512 PEs buys about a
third of what going from 32 to 64 buys. Cumulatively the median total falls
7.34× across the sixteen-fold range of N, and the median compute 7.56×, against
16× for proportional scaling.

The cause is the mapping, not memory. Each schedule places `min(N,COUT)` output
channels across PEs, so a layer's compute scales with `min(N,COUT)` and stops
scaling once N reaches that layer's COUT. The 13 layers hold three COUT values:
five at 128, five at 256, three at 512. Their measured per-layer compute from
N=32 to N=512 is exactly 4.00×, 8.00×, and 16.00× respectively, that is
`COUT/32`. Across all 6,500 layer runs, `count_cycles` equals
`count_cycles(N=32) * 32 / min(N,COUT)` exactly, with no exceptions. The
aggregate per-doubling compute reductions in the table above are therefore
reproduced by that relation to the stated precision; the compute column is a
measured quantity that the `min(N,COUT)` relation also predicts, not an
independent model fit.

How many layers have stopped scaling sets the aggregate shape. At N=32 and
N=64 every layer still splits COUT across multiple tiles. At N=128 the five
COUT=128 layers reach their ceiling. At N=256 those five run with half their
lanes idle and five more reach their ceiling. At N=512 ten of the 13 layers
run with idle lanes, and those ten account for 89.1% of compute at that width,
which is why the last doubling returns 9.8% of compute rather than 50%. That
share is the median over the 100 samples of each sample's own idle-layer share
of its network compute sum, the same per-sample basis used everywhere else in
this file; taking it instead as a ratio of per-layer medians gives 89.1% as
well.

### Compute versus exposed memory

Compute and total do not fall together. For the first three doublings the
total falls slightly *less* than compute (49.4% against 50.0%, 48.8% against
50.0%, then 36.9% against 41.4%), because the exposed-memory residual is
growing and partly offsets the compute saving. Only at the last doubling does
the total fall *more* than compute (16.8% against 9.8%), because there the
residual shrinks. That residual is not monotone in N:

| N (PEs) | Median exposed memory | Median memory / total | Min–max over the 100 samples |
|---:|---:|---:|---|
| 32 | 9,396 | 0.05% | 7,945 – 31,224 |
| 64 | 116,077 | 1.11% | 71,388 – 246,797 |
| 128 | 192,321 | 3.59% | 136,294 – 242,755 |
| 256 | 353,750.5 | 10.47% | 328,164 – 380,441 |
| 512 | 84,096 | 2.99% | 84,096 – 84,096 |

The residual rises from 0.05% of the total at N=32 to a peak of 10.47% at
N=256, then falls to 2.99% at N=512. It therefore peaks at an intermediate
hardware size rather than growing with N, and at N=512 it is smaller than at
N=256 both in absolute cycles and as a share of the total. At N=512 it is
also identical across all 100
samples (84,096 cycles), whereas at every smaller N it varies sample to
sample. These are measured differences of two summed counters, as defined
above; they are not a measurement of all DRAM service cycles or bytes, and
this campaign does not isolate which dependency exposes them.

### Flatness check for N ≥ COUT

For N ≥ COUT the schedule is unchanged as N grows: `min(N,COUT)` is COUT,
`dram_num_steps` stays `HO*WO`, and the extra lanes are idle. The data agrees
bit for bit. For every layer and every one of the 100 samples, both
`total_cycles` and `count_cycles` are identical across all widths N ≥ COUT —
not close, equal.

This check is non-trivial for 10 of the 13 layers, covering 1,000
(layer, sample) pairs: the five COUT=128 layers compare three widths
(128, 256, 512) and the five COUT=256 layers compare two (256, 512). For the
three COUT=512 layers only N=512 satisfies N ≥ COUT, so the campaign's width
range gives nothing to compare and the check does not apply to them.

All of the above is the 13-of-19-convolution partial sum described at the top
of this file: a sum over captured, replayable stride-1 convolutions under
sequential layer execution with no inter-layer overlap. The six omitted layers
are exactly the spatial-downsampling convolutions, so the saturation point of
the full 19-convolution network is not measured here. The percentages are
properties of these 100 samples and these 13 layers, not interval estimates.

Caption: **SpinalFlow latency versus hardware node size, four networks.**
Boxes show 100 sample totals per network at each hardware size, with median
lines, interquartile boxes, and min–max whiskers; one line per network connects
its medians. The y axis is logarithmic, so equal vertical distances are equal
ratios and the flattening of a median line is the diminishing return per
doubling of N. Each total sums that network's included captured convolutions
sequentially without inter-layer overlap, and the legend entry gives its
included/total layer counts. ResNet19 layers 01, 03, 08, 10, 15, and 17 are
omitted because replay does not implement stride 2; the other three networks
have no omitted layers. Larger N leaves lanes idle when a layer has fewer output
channels. The selected sample indices and layer sets are fixed in the
manifest.

The plot uses the lab's chopper style: 3.375-inch width, 8-pt text, a solid
y grid, and an unframed upper legend above the axes, in up to two columns. Each
network has one color and one marker, used for its box faces (35% alpha), their
edges, the whisker and cap lines, the median line inside each box, and the
marker line connecting medians across hardware sizes: gold `#FFB000` with square
markers for ResNet19, purple `#785EF0` with circles for VGG16, magenta `#DC267F`
with triangles for SDT, and blue `#648FFF` with diamonds for VGG8-DVS. The
legend carries one entry per network, labelled `Name (included/total)` from the
manifest's layer counts, and that entry is the network's median line.
No Gill Sans TTF is present in the campaign directory, so the export uses
Matplotlib's default DejaVu Sans and prints one warning. A `GIL*.TTF/ttf`
placed in this directory is registered and used on subsequent exports.
PDF creation timestamps are omitted; the PDF is vector graphics.
`provenance.json` records inputs, source, binaries, commands, environment,
each network's feasibility report and its artifact hashes, and result/figure
hashes. `record_provenance.py` requires a feasibility report for every network
in the manifest, with a matching trace and layer set. Its wording describes the
recorded artifacts.
