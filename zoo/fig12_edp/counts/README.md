# SpinalFlow analytic counts

`prosperity_counts.py` reads realized tiles from `--manifest`, consumes the
two exact sample-0 anchors in `--digest`, and accepts saved exact counts
with `--record-counts CSV` (`capture,layer,sample,R_p`). It never reruns
the prefix walk. Other 3x3 samples fail explicitly without that CSV:
the checked-in S3 digest/shards retained means/ranges/totals, not the full
500 per-sample vectors. 1x1 counts use the tile-local closed form and check
any supplied digest value. Infeasible schedules are skipped.
Front-end `N_rows`/`SORT` are charged once over spatial/time tiles and CIN,
without a COUT-slab multiplier. `raw` uses the same burst units as `R_p`;
`A_p=R_p*cout_n`. Seed reads use `N_rows*cout_n`. `SORT` is the plan's
`2*M*log2(M)` estimate, including fractional estimates for non-power-of-two M.

Pipeline contract: after generating a Prosperity WCTS, emit an exact
per-case CSV with header `capture,layer,sample,R_p` and one row whose `R_p`
is the total emitted weight records (the WCTS trailer count, equivalently
the native access/mac-cycle sum for Prosperity). Use the full relative
capture identity and local sample index, not an average or source-sample
index. Flush and atomically rename the CSV after successful generation;
retain it when deleting the transient WCTS. Pass its path as
`prosperity_counts.py --record-counts <case.csv>`, together with the matching
capture/layer/sample selection. T68/T69 and the campaign runner consume this
same durable count; collecting it requires no second prefix walk. The S3
aggregates only cross-check values, never replace a missing sample.
`validate_prosperity.py --limit 1` times the authorized sample-0-only 3x3
check; a subsequent run resumes the remaining pairs. It stages only sample
0 in a temporary NPY, invokes the unchanged S3 helper, and records exact
rows in `prosperity_sample0_records.csv`. Inputs and the S3 source remain
read-only. Paper-anchor validation waits for planned ASAP7 synthesis.

`gustavsnn_counts.py` shares SpinalFlow's `S_win` and `A`, using the largest
COUT divisor capped at two. `R_g/R_spinalflow` is two when SpinalFlow uses
four lanes, and one for classifier COUT=10/11 where its divisor is two/one.
Both HO lanes' repeated fetches remain charged. `W_o` counts expected output
bits; the 32-bit FIFO energy uses `W_o/32` packed-word equivalents.

`loas_counts.py` uses the PTB convolution core and CLI, adding
`W_o=O/T=d_out*HO*WO*COUT`. `O` remains the estimated spike count, while
`W_o` is the output-word count specified by the LoAS model. Its tests compare
the analytic fetches to native LoAS WCTS for two real layers.

`ptb_counts.py` accepts the same capture, sample, layer, thread and resume
options and writes `ptb_counts.csv`. It computes `S_or` (OR across time),
`S_sum`, `B=S_or*COUT/cout_n`, `A=S_sum*COUT`, and `L=HO*WO*COUT*T`.
`O=d_out*L` is an estimate and can be fractional. Density is measured per
sample from the next layer in metadata order; the final layer uses its own
input density as a labeled proxy. Layer filtering does not change which
layer supplies density. Input captures are always opened read-only.
The public PTB/LoAS `count_sample` function requires explicit `d_out`;
callers must resolve next-layer density or label a final-layer proxy.
Optional PTB WCTS validation checks the full layer's weight-lane count,
allowing a different burst width. The regression test generates actual
native PTB streams for two example layers and verifies burst totals. A
separate test checks `S_sum` against the delivered SpinalFlow CSV on B09 captures. Resume drops an interrupted final CSV row and
rejects interior corruption or duplicates.

`spinalflow_counts.py` reads the captured `[T, B, CIN, Hin, Win]` `uint8`
arrays and writes one CSV row per `(capture, layer, sample)`.  It accepts the
1x1 and 3x3 stride-1 layers supported by the SpinalFlow replay path and skips
other layers.

For each input spike, the script computes its multiplicity in the padded
receptive field (the same result as summing a ones kernel over `T`):

```text
S_win = sum over t, output pixel, receptive (kh, kw, cin) of spike
A     = S_win * COUT
R     = A / cout_n
O     = HO * WO * COUT * T       # conservative output-spike bound
```

`cout_n` is the largest divisor of `COUT` not exceeding the campaign's
four-PE COUT cap, unless `--cout-n` overrides it.  `O_source=bound` is
intentional: these captures contain layer inputs, not a separate exact output
spike tensor.

The run is serial, mmap-backed, and flushes every CSV row.  Use `--resume` to
skip rows already present after an interrupted task.  `--max-captures`,
`--max-layers`, `--sample-start`, `--sample-count`, and `--max-samples` bound a
task for a Slurm array.  Common BLAS/OpenMP pools are capped by `--threads`
(default 1, maximum 4).

Example smoke run:

```bash
conda run -n base python zoo/fig12_edp/counts/spinalflow_counts.py \
  --trace-root /work/nvme/bebv/yyu9/input_trace_delta \
  --capture A08/vgg16_cifar10_loas_T32_n500 \
  --max-layers 1 --max-samples 2 --threads 1 \
  --output zoo/fig12_edp/counts/spinalflow_counts.csv
```

For replay checks, point `--wcts-root` at a tree containing
`<trace_dir>/<layer>/sample_NNNNN.wcts` or `.wcts.gz` (the campaign tree may
have an additional `spinalflow/` component).  The parser validates the WCTS
header, frame payloads, trailer, and lane-operation count (sum of burst
widths). Full streams at the campaign width report `replay_status=pass`;
full streams at another width report `pass_geometry` when lane operations
match `A`. Partial streams fail validation.

The CSV columns are the count schema: capture/layer/sample identity, tensor
dimensions, `cout_n`, `S_win`, `A`, `R`, `O`, `O_bound`, `O_source`, and the
optional WCTS path/count/status/detail fields.

Submit the full serial run from the repository root on Delta:

```bash
sbatch --account=YOUR_CPU_ACCOUNT --partition=cpu \
  --output=zoo/fig12_edp/counts/slurm-%j.log \
  zoo/fig12_edp/counts/run_counts.sbatch
```

Replace `YOUR_CPU_ACCOUNT` with a CPU allocation listed by Delta's `accounts`
command. Delta rejects a GPU allocation for CPU-only jobs. The count process
uses one CPU and requests no GPU resources.
The wrapper requests 8 GB and four hours, caps thread pools at one, and resumes
the single `spinalflow_counts.csv`. Do not run two jobs against the same CSV.
It includes all supported layers in the eight captures, without a schedule
feasibility filter. Bulk capture rows have `replay_status=unavailable` unless
the matching streams are supplied.

For the authorized login-node post-processing run, a 99-row slice across all
eight captures used 1.348 CPU-seconds in the counting phase (1.796 seconds
wall time), projecting to 17.13 CPU-minutes for 75,500 rows. A separate cold
process including conda startup used 5.35 CPU-seconds / 7.92 seconds wall time;
the per-row projection excludes that one-time environment startup.

```bash
setsid -w systemd-run --user --scope -q -p OOMPolicy=continue \
  nice -n 10 env OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 \
  NUMEXPR_NUM_THREADS=4 BLIS_NUM_THREADS=4 VECLIB_MAXIMUM_THREADS=4 \
  conda run --no-capture-output -n base python zoo/fig12_edp/counts/run_login.py
```

This driver covers the eight 500-sample captures in serial 50-sample chunks,
caps thread pools at four, and stops after a chunk if total CPU usage exceeds
30 minutes. It resumes the same CSV and verifies the complete identity set,
uniqueness and count equations, saving timing and coverage in
`counts_validation.json`. The two 99-row timing samples are retained as
`timing_slice.csv` and `timing_slice_2.csv`. Do not run this driver and a Slurm
job against the CSV simultaneously.

The delivered CSV contains 75,500 unique rows: 151 supported layers across
eight captures, each with samples 0–499. Full coverage and count equations
passed. The measured run used 207.34 CPU-seconds (3.46 CPU-minutes), 557.46
seconds wall time, and zero GPU-hours; see `counts_validation.json`.

`validate_replay.py` independently replays sample 0 of the committed
`examples/input_trace/loas/vgg16_T4_n5` capture through the native generator,
serializes actual WCTS, then checks it with the count parser. Run:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  conda run -n base python zoo/fig12_edp/counts/validate_replay.py
```

`replay_validation.json` records section 8's 82,232 / 64,728 bursts at width
128, corresponding to `S_win=41,116 / 16,182` and `A=10,525,696 / 8,285,184`.
Those stream burst counts differ from campaign `R` because the campaign uses
width four. Temporary native outputs and streams are removed after validation.
