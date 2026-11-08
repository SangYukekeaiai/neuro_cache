# SpinalFlow hardware node-size sweep

This campaign varies the number of PEs in one SpinalFlow node:
N = 32, 64, 128, 256, and 512. It uses the 500-sample capture at
`/lustre/fs1/home/ya867177/data/input_trace_delta/B09/loas_resnet19_T4_n500`
and runs the deterministic 100-sample subset selected by
`sample_indices(n=100, seed=0, n_total=500)`. The campaign is ResNet19 only;
the old five-sample VGG16/ResNet19 demo outputs remain untouched.

The ResNet19 series is a **13-of-19-convolution partial sum**. Network latency
is the sum of the included layer latencies for one sample, assuming sequential
layer execution and **no inter-layer overlap**. This is a sum over captured,
replayable convolutions, not a model of uncaptured operations or a full
inference software stack.

## Layers and samples

| Capture | Included captured layers | Layer runs |
|---|---|---:|
| ResNet19 n500 | 02, 04–07, 09, 11–14, 16, 18–19 (13 stride-1 convolutions) | 6,500 |

The 6,500 layer runs yield 500 network/sample totals: one network × five
hardware sizes × 100 selected samples. The exact selected indices are recorded
in `inputs/manifest.json` under `sample_selection.indices` and in every Slurm
case manifest. Captured metadata and spike arrays are used directly without
modification.

ResNet19 layers 01, 03, 08, 10, 15, and 17 (with the trace's `core_` infix)
are excluded. These are stride-2 3×3 convolutions or stride-2 1×1 shortcuts.
The replay binary receives no stride field, and the public trace loader permits
only 1×1 or 3×3 stride-1 convolutions. These six layers are precisely the
spatial-downsampling convolutions, so the omission is not uniform across depth.
`check_replay.py` compares native replay at N=128, sample 0,
against raw NumPy receptive-field counts. The independent reference pads
the raw input by `(kernel-1)//2`, then counts each kernel-sized window
starting at `(ho*stride, wo*stride)` in padded input. A 1×1 shortcut thus
uses one unpadded input pixel; a 3×3 convolution uses nine padded positions.

| Layer | Kernel/stride | Tiles | Differing tiles | Reference cycles | Native cycles |
|---|---|---:|---:|---:|---:|
| ResNet19 01 | 3×3 / 2 | 256 | 254 | 50,709 | 45,435 |
| ResNet19 03 | 1×1 / 2 | 256 | 252 | 5,883 | 5,382 |
| ResNet19 02, control | 3×3 / 1 | 256 | 0 | 144,914 | 144,914 |

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
PYTHONPATH=src $PY zoo/fig3_hw_n_sweep/check_replay.py
PYTHONPATH=src $PY zoo/fig3_hw_n_sweep/gen_inputs.py
PYTHONPATH=src:zoo/fig3_hw_n_sweep/slurm $PY zoo/fig3_hw_n_sweep/slurm/shard_cases.py \
  --batch-samples --num-shards 250 --cases-per-shard 100 \
  --output-dir zoo/fig3_hw_n_sweep/outputs/slurm/n500-cases \
  --shard-root zoo/fig3_hw_n_sweep/outputs/slurm/n500-runs
sbatch --partition=normal --time=90:00 --cpus-per-task=4 --array=0-64%65 \
  zoo/fig3_hw_n_sweep/slurm/run_array.sbatch \
  --case-dir zoo/fig3_hw_n_sweep/outputs/slurm/n500-cases \
  --shard-root zoo/fig3_hw_n_sweep/outputs/slurm/n500-runs \
  --batch-samples
PYTHONPATH=src:zoo/fig3_hw_n_sweep/slurm $PY zoo/fig3_hw_n_sweep/slurm/assemble_shards.py \
  --manifest zoo/fig3_hw_n_sweep/outputs/slurm/n500-cases/manifest.json \
  --source zoo/fig3_hw_n_sweep/outputs/slurm/n500-cases/manifest.json \
           zoo/fig3_hw_n_sweep/outputs/slurm/n500-runs \
  --output-root zoo/fig3_hw_n_sweep/outputs/slurm/n500-assembled-runs
PYTHONPATH=src:zoo/fig3_hw_n_sweep/slurm $PY zoo/fig3_hw_n_sweep/slurm/merge_results.py \
  --manifest zoo/fig3_hw_n_sweep/outputs/slurm/n500-cases/manifest.json \
  --shard-root zoo/fig3_hw_n_sweep/outputs/slurm/n500-assembled-runs \
  --output-dir zoo/fig3_hw_n_sweep/outputs
PYTHONPATH=src $PY zoo/fig3_hw_n_sweep/plot.py
PYTHONPATH=src $PY zoo/fig3_hw_n_sweep/record_provenance.py
```

`--batch-samples` pays the weight-trace generator startup and trace load once
per `(layer, N)` group with `--sample-count 100 --sample-total 500`; nocsim
still runs once per selected sample. The Slurm manifest keeps each batch group
whole, so the full campaign has 65 non-empty array tasks of 100 cases each.
The harness writes per-shard progress, commands, native logs, and cycle results;
`merge_results.py` validates all 6,500 layer keys exactly once before writing
the final results and summary. `assemble_shards.py` maps each source round to
the target shard by its exact case set, checks equivalent rerun results, and
renames command logs to the target shard index before merging. If reruns are
needed, pass each rerun manifest and shard root as another `--source` pair;
`rerun_missing.py` emits the reduced manifest and time-limited array command.
The host has no usable systemd user bus, so these jobs use `setsid` alone.

The repository's `src/lays/nocsim/combine.py` behavior is already included in
the current repository commit. No external combine patch or separate checkout
is required to reproduce the commands above.

The current `outputs/results.csv` and `outputs/summary.csv` are the merged
n500 campaign.
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

`plot.py` validates all 6,500 layer keys and all 500 network/sample totals
before drawing `fig3_hw_n_sweep.pdf` and its 300-dpi PNG preview. At each N,
the single ResNet19 box shows the 25th–75th percentiles of 100 sample totals;
the center line is the median and the whiskers span the full min–max. The
line connects medians across hardware sizes. These are empirical sample
ranges, not confidence intervals.

The y axis is logarithmic in cycles. Equal vertical distances are therefore
equal ratios, which is the reading the saturation section below depends on:
proportional scaling with N would place the five medians on a straight line of
constant slope, and the measured medians instead flatten as N grows, with the
vertical step between successive N shrinking from 32 → 64 to 256 → 512. A log
axis excludes zero, so the axis is bounded by the data rather than anchored at
the origin, and the interquartile boxes at the larger N appear taller relative
to their medians than a linear axis would render them.

The merged campaign's median metrics are:

| N (PEs) | Median total cycles | Median count cycles | Median memory cycles | Median memory / total |
|---:|---:|---:|---:|---:|
| 32 | 20,640,842 | 20,629,030 | 9,396 | 0.05% |
| 64 | 10,450,763.5 | 10,314,515 | 116,077 | 1.11% |
| 128 | 5,352,196.5 | 5,157,257.5 | 192,321 | 3.59% |
| 256 | 3,379,137.5 | 3,022,898.5 | 353,750.5 | 10.47% |
| 512 | 2,811,275.5 | 2,727,179.5 | 84,096 | 2.99% |

## Saturation

Each doubling of N removes less latency than the one before it. Reductions in
the median total, computed from the medians above:

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

Caption: **SpinalFlow ResNet19 latency versus hardware node size.** Boxes show
100 sample totals at each hardware size, with median lines, interquartile boxes,
and min–max whiskers; the line connects medians. The y axis is logarithmic, so
equal vertical distances are equal ratios and the flattening of the median line
is the diminishing return per doubling of N. Each total sums the 13
included captured convolutions sequentially without inter-layer overlap.
Layers 01, 03, 08, 10, 15, and 17 are omitted because replay does not
implement stride 2. Larger N leaves lanes idle when a layer has fewer output
channels. The selected sample indices and layer set are fixed in the manifest.

The plot uses the lab's chopper style: 3.375-inch width, 8-pt text, a solid
y grid, and an unframed upper legend above the axes. The single ResNet19
series uses two colors, not one: gold `#FFB000` for the box faces (35% alpha),
their edges, and the whisker and cap lines, and blue `#648FFF` for the median
line inside each box and for the square-marker line connecting medians across
hardware sizes. The legend carries that median line as the series' one entry.
No Gill Sans TTF is present in the campaign directory, so the export uses
Matplotlib's default DejaVu Sans and prints one warning. A `GIL*.TTF/ttf`
placed in this directory is registered and used on subsequent exports.
PDF creation timestamps are omitted; the PDF is vector graphics.
`provenance.json` records inputs, source, binaries, commands, environment,
and result/figure hashes. Its wording describes the recorded artifacts.
