# eval_scaling execution plan (full chain) - PLAN ONLY, nothing implemented

Boss spec 2026-11-16 (verbatim decisions) applied on top of `plan.md`:

- Two series only: single-node vs multi-node. **Supersedes plan.md v2's third
  (multi-node cache) series - confirm this is intended before plotting.**
- Workload: loas_vgg16, samples 000-009 (10), the 12 kept layers (C5/C6).
- Utilization: the Row-1 formula in `plan.md` (U = sum_l C_l / (N * sum_l T_l)),
  computed from nocsim total latency + per-core per-tile latency.
- Traffic: **CoSA weight-traffic formula (analytic, from the solved schedule)**,
  not the nocsim DRAM-byte counter of plan.md Row 2. nocsim DRAM bytes are kept
  as a cross-check diagnostic only.
- Single-node side goes through the scheduler too, then nocsim's single-node
  path (weight traces are still produced by the single-node core model).
- Venue: Stokes (bridge already built). All inputs/outputs under
  `zoo/eval_scaling/`, fully separated from every other zoo figure.

## Sweep definition

| Side | Node mapspace | Nodes | lb (L1 weight) per node | GB (L2 weight) | Total weight storage |
|---|---|---|---|---|---|
| single | CIN/KH/KW full, COUT=64, T full | 1 | 1024 KB × {1,2,4,8,16} → 1-16 MB | - (single_node: true, direct DRAM→node) | 1-16 MB |
| multi | CIN/KH/KW full, COUT=4, T full | 16 | 32 KB × {1,2,4,8,16} → 32-512 KB | 512 KB × {1,2,4,8,16} → 0.5-8 MB | 1-16 MB (16·lb + GB) |

- Equal-capacity accounting (resolves C9): **total weight storage =
  sum of node lb + GB**; psum/vmem/state buffers held constant per fig1
  convention. 16×32 KB + 512 KB = 1024 KB matches single x1 exactly, and the
  match holds at every multiplier. Caption must state this rule.
- PE accounting: multi-node keeps campaign `num_pes: 4` per node (64 total);
  single node gets `num_pes: 64` so compute capability is equal and only the
  memory organization differs. (Assumption - flag to boss.)
- Note for the caption/text: single-node x1 (1024 KB) is already 32× the
  published LoAS lb (32 KB); the x-axis is total on-chip capacity, not
  multiples of published.

Case counts: schedules 2 sides × 5 capacities × 12 layers = **120 solves**;
trace-gen/sim 120 × 10 samples = **1,200 cases** per stage.

## Full chain (input → module → intermediate → output)

### S0. Ingest + configs (Delta, no compute)
- **Input:** boss spec above; bases `zoo/wt500_fig3cfg/arch.yaml`,
  `zoo/wt500_fig3cfg/mapspaces/loas.yaml`; B09 vgg16 capture `meta.json`
  (layer dims, kept-layer list) from `/work/nvme/bebv/yyu9/input_trace_delta/`.
- **Module:** none (config authoring), S0-style snapshot of external inputs.
- **Output:** `zoo/eval_scaling/configs/`
  - `arch_single_x{1,2,4,8,16}.yaml` (single_node: true, lb per table, COUT-64 mapspace `mapspaces/loas_single.yaml`)
  - `arch_multi_x{1,2,4,8,16}.yaml` (16 nodes, lb+GB per table, campaign COUT-4 mapspace `mapspaces/loas_multi.yaml`)
  - `sweep_config.yaml` (case list: side × capacity × layer × sample), published-capacity note with citation.

### S1. Scheduler (Delta login - Gurobi license lives here; module `lays.scheduler`)
- **Input:** per case: arch yaml + mapspace + layer dims.
- **Module:** `lays.scheduler` CLI (MIP solve, branch problems for
  traffic-free cases). Thread caps per login-node rules (Gurobi Threads=1,
  OPENBLAS/OMP_NUM_THREADS=1).
- **Intermediate:** per-case solver logs.
- **Output:** `zoo/eval_scaling/outputs/schedules/{side}_x{m}/{layer}.json`
  + `extract_metrics` dump (util, spatial_cost, temporal_traffic, delay)
  per schedule. 120 solves, minutes each - login-friendly, no Slurm needed.

### S2. Analytic CoSA weight traffic (Delta; small join script, no sim)
- **Input:** S1 schedules + metrics.
- **Module:** `lays.scheduler.metrics` values; per plan.md closed form
  W_weight = GB-tile bytes × product of DRAM-boundary-crossing temporal trips
  (= `util[weight]` × `temporal_traffic[weight]` in linear scale, bw_weight/8).
- **Output:** `zoo/eval_scaling/outputs/traffic.csv`:
  (side, capacity, layer) → W_weight bytes. **Schedule-determined, so
  sample-independent: the traffic panel has no CI** (flag to boss; plan.md
  Row 2 had per-sample CI from counted DRAM bytes).

### S3. Weight trace generation (Stokes Slurm; module `lays.weight_trace_gen`, LoAS model)
- **Input:** S1 schedules shipped over the bridge + B09 vgg16 spike captures
  samples 000-009 (already mirrored on Stokes).
- **Module:** `lays.weight_trace_gen` (LoAS core model) - replays spikes
  through the node tile computation: single side with the COUT-64 node,
  multi side with the COUT-4 node.
- **Output (intermediate, /dev/shm then scratch):** per (side, capacity,
  layer, sample): per-tile weight-address trace + per-tile cycle counts
  (wcts). 1,200 cases. Traces deleted after S4 consumes them (wave pattern).

### S4. nocsim (Stokes Slurm; module `lays.nocsim`)
- **Input:** S1 schedule + S3 per-tile cycles/traces, arch yaml.
- **Module:** `lays.nocsim` - single side through the single-node path
  (`combine.py` direct DRAM→node sends with weight-change elision), multi
  side through the full NoC eventsim (GB tiles, K/T-chains).
- **Output:** per case CSV: T_l (makespan), C_l per node (compute-transaction
  occupancy = per-core per-tile latency summed), D_l, DRAM transaction bytes
  (diagnostic cross-check against S2 only - not plotted).
  1,200 runs. Slurm array via the `wt500_fig3cfg/stokes/sim_shard` pattern:
  real `--mem`, TMPDIR=/dev/shm, thread env caps, shard manifest + rerun_missing.

### S5. Transfer back + aggregate (Delta; join script in `zoo/eval_scaling/`)
- **Input:** S4 CSVs (bridge back), S2 traffic.csv.
- **Formulae (per plan.md):**
  - U = (sum_l C_l) / (N · sum_l T_l), cycle-weighted over the 12 layers
    (sum before divide), per sample → mean ± 95% CI over 10 samples.
  - Traffic y = W(side, x) / W_single(x1), layer-summed, one baseline per panel.
- **Output:** `zoo/eval_scaling/outputs/aggregate.csv`
  (side, capacity → U_mean, U_ci, traffic_norm) + stall-decomposition
  diagnostics columns (exposed/overlapped, not plotted).

### S6. Plot (Delta; `zoo/eval_scaling/plot.py` per approved mock)
- **Input:** aggregate.csv; mock `docs/scaling_mock.py` restyled to TWO series.
- **Output:** `zoo/eval_scaling/outputs/eval_scaling.{pdf,png}` +
  `provenance.json`. 1×2 panels: left U, right normalized traffic with the
  compulsory floor (R=1, every weight once) as dotted reference; x-axis
  total on-chip capacity, log2. → copied into the paper repo `fig/` only
  after boss sign-off.

## Boss gates
1. This plan + the two-series mock (regenerate scaling_mock without the cache series).
2. S1 schedule sanity spot-check (one layer per side, capacities x1/x16) before launching S3/S4 on Stokes.
3. Figure sign-off before paper integration.

## Open flags for boss
- F1: cache series really dropped (contradicts plan.md v2 note of 2026-11-16)?
- F2: single-node num_pes = 64 (equal compute) - confirm.
- F3: traffic panel without CI (analytic CoSA traffic is per-schedule) - OK,
  or also plot nocsim-counted DRAM bytes (per-sample, with CI) as the check?
- F4: single-node solves may be near-trivial (mapspace mostly fixed by the
  inherent dataflow) - scheduler still run for uniformity per spec item 5.
