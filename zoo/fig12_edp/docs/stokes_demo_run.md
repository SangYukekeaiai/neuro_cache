# Stokes demo run (T97): stage-1 counts / stage-2 dummy pricing

## Host

Stokes (UCF ARCC), partition `normal`: 153 nodes, 32+ cores, ~192 GB each; account `dwu2`, limits MaxJobs 250, MaxArraySize 1001. Access from Delta over the boss's reverse tunnel (`localhost:2223`) through an authenticated SSH multiplexing socket (`~/.ssh/cm-stokes.sock`; Stokes sshd allows password/keyboard-interactive only, no public keys).

Staging root on Lustre: `~/snn_edp_stokes_20261114/`

| Entry | Content |
|---|---|
| `neuro_cache_wcache/` | single-repo upload per STAGING.md; vendored archx backend at `zoo/archx/`, model at `zoo/archx/zoo/snn_edp/` |
| `input_trace_sample0/<ID>/<benchmark>/` | read-only sample-0 slice of `input_trace_delta` + per-benchmark `meta.json`, SHA-verified |
| `env/` | conda env; vendored backend rebuilt natively (prebuilt core incompatible with Stokes glibc 2.28) |
| `schedules/`, `logs/` | shipped schedule manifest; run logs |
| `scientific_sources.sha256` | ledger: 175 subset + 252 simulator/model/fixture source files verified |

## Cases

559 kept feasible architecture x layer pairs: 113 kept layers of 151 (38 fully connected layers excluded, user decision B; see [input_trace_and_layers.md](input_trace_and_layers.md)) across 8 benchmarks (A02 spikformer, A04 SDT, A07 spikingLM, A08 vgg16-T32, B09 loas vgg16 + resnet19, C01 two DVS variants) x 5 architectures (spinalflow, ptb, loas, gustavsnn, prosperity), minus the 6 infeasible Prosperity A08 schedules. 1 sample per case, 3 arms per case: spd (nocsim), cacheA (next_access + distance_aware), cacheB (**NextLine at both levels**, T96; first-ever cacheB numbers under this policy, not comparable to any earlier cacheB result).

## Per-task command chain (stage 1: counts only, no energy table anywhere)

```
trace gen  -> <case>/sample_00000/sample_00000.wcts   (command, record count, SHA in generation.json)
counts     -> counts.json
simulators -> noc/result.json (spd); cache_a.csv; cache_b.csv   (configs/production_cache_{a,b}.json)
stage A    -> python zoo/archx/zoo/snn_edp/run.py count --case <case_dir> \
                --out <case_dir>/archx_artifacts/sample_00000/counts
```

Environment per task: `ARCHX_DISABLE_PERFORMANCE_CACHE=1`, thread caps, node-local `TMPDIR`; the transient trace is deleted after the durable result commit (provenance retained).

## Submission tiers

One Slurm array (or three tiered arrays), throttle <= 250 concurrent; OOM/timeout retries once in the next tier up before being reported failed.

| Tier | Cases | Memory | Time cap |
|---|---|---|---|
| default | 505 | 16 GB | 25 min |
| heavy (planning proxy > 16 GiB) | 50 | 64 GB | 45 min |
| SpinalFlow, 54 GiB OOM history (T84) | 4 | 120 GB | 60 min |

Estimated wall time to drain: ~45-60 min with 250 slots (queue empty at submission planning).

## Stage 2 (held until boss inspects stage-1 counts)

```
python zoo/archx/zoo/snn_edp/run.py price --counts <case>/archx_artifacts/sample_00000/counts \
    --table zoo/archx/zoo/snn_edp/characterization/energy_table_dummy.json --out .../energy
collect -> results.csv, whole_model.csv ; plot -> EDP comparison figure
```

A later real-table reprice is stage-B-only: it rebinds a new table to the same saved count checkpoints without rerunning any simulator.

## Gate that authorized this run

Five fixtures x 3 arms reproduced on Stokes against the pinned reference: 15 rows, 386 terms, max total relative error 2.69e-16, term error 0. Production config byte-pins verified; remote config B confirmed NextLine. Evidence: `/u/yyu9/peon-snapshots/energy-performance-estimation/T97-20261114-stokes/`.

## Checkpoints

1. After the array drains: per-case success/fail table, wall time, and 2-3 exact count-checkpoint paths (one small, one big, one Prosperity) for manual inspection.
2. Stage 2 + plot only on explicit go after that inspection.

Operational notes: keep the window-2 Stokes master session alive (socket persists 8 h); a dead socket halts transfers safely (password fallback disabled) and needs one boss re-login.
