# Figure 1: inputs, configuration decisions, and step-by-step schedule (FOR BOSS REVIEW - nothing implemented)

Companion to [plan.md](plan.md). Part A lists every ingredient and every open configuration knob with its proposed value. Part B is the full pipelined breakdown with inputs/outputs per step.

## Part A - what is used, and what must be decided

### A1. Fixed ingredients (already exist, reused as-is)

| Ingredient | Location | Role |
|---|---|---|
| Input spike traces | `/work/nvme/bebv/yyu9/input_trace_delta/` (read-only) | source of real spikes; drives both baseline runs and needed-weights counts |
| Schedule manifest | `zoo/wt500_fig3cfg/outputs/manifest.json` | the inherent, fixed per-arch schedules (boss decision: untouched) |
| Hardware model | `zoo/archx/zoo/snn_edp/hardware.json` (SHA b640ca5a) | all non-SRAM parameters stay exactly as-is |
| Energy table | `zoo/archx/zoo/snn_edp/characterization/energy_table_nangate45.json` (SHA 2d8e4ea0) | Stage-B pricing; ASAP7 replaces later by reprice only |
| Stage-A/B machinery | `zoo/fig12_edp/` (run.py count/price, energy_driver) | unchanged code paths; fig1 only reuses readers/pricers |
| Fetched campaign rows + receipts | `zoo/fig12_edp/stokes/full500_rows_fetch_20261116/` | Stage-0 ranking queries; no new compute needed for selection |
| Layer keep/skip rule | `zoo/fig12_edp/docs/input_trace_and_layers.md` (113 kept / 38 skipped) | same whole-model layer set as Fig 12 |
| Figure generator | `docs/fig1_mock.py` (approved layout) | promoted to production renderer in the last step |
| Native simulators | built per-venue from source (nocsim for spd arm) | baseline event counts |

### A2. Decisions to make (proposed value -> boss confirms or overrides)

| # | Knob | Proposed | Notes |
|---|---|---|---|
| D1 | 3 architectures | from Stage-0 ranking (expected PTB/LoAS/GustavSNN) | ranked by measured gen+sim wall time from fetched receipts |
| D2 | Benchmark (1) | from Stage-0 ranking (provisional B09) | rank = off-chip-weight energy fraction x all-vs-needed gap x 1/trace-size, small-trace set only |
| D3 | SRAM sweep sizes | 64KB / 256KB / 1MB weight scratchpad | 16x span; "default" = closest to each arch's published size |
| D4 | Default size for Ideal bar | 256KB | Ideal computed once at default; it is (near) size-independent |
| D5 | Samples N | 10 (sample indices 000-009, already characterized) | CI from sample spread; raise only if CIs visibly wide |
| D6 | Normalization | per-arch, baseline@256KB = 1.0 | cross-arch absolute J table goes in an appendix cell if wanted |
| D7 | Needed-weights definition | unique weight words touched by nonzero spikes per layer per sample, at the OFF-CHIP level, under the arch's inherent schedule (compulsory traffic) | re-loads excluded by definition of "ideal"; stated in caption |
| D8 | Substitution scope | off-chip weight reads + the L1 fills they imply; everything else (compute, input, psum, on-chip reads, leakage) from the matching baseline run; TIME FIXED | boss decision recorded; caption carries both sentences |
| D9 | Segment classification | compute / on-chip SRAM / off-chip (weights) / off-chip (other) | mapping from the 98 hardware.json rows to the 4 segments is written down in a small table (step 3 deliverable) and boss-checkable |
| D10 | Venue for the ~90 sweep runs | Delta login-scale or any single node | one benchmark x 3 arch x 3 sizes x 10 samples; hours of compute |
| D11 | Error bars | 95% CI across the N samples, whole-model totals | matches Fig 12 methodology |

## Part B - pipelined schedule (step-by-step)

Steps marked [GATE] stop for boss review. Each step names inputs -> outputs. Steps 1-2 are pure queries; first new compute is step 5.

1. **Rank architectures** - inputs: fetched Stage-A receipts (per-case gen/sim wall times, 23 samples). Output: `outputs/stage0_arch_ranking.csv` + 5-row summary table. Decides D1.
2. **Rank benchmarks** - inputs: fetched NG45 rows (off-chip weight fraction per benchmark/arch) + trace sizes. Output: `outputs/stage0_benchmark_ranking.csv`. Decides D2.
3. **Write the segment map** - inputs: hardware.json 98 rows. Output: `docs/segment_map.md` (row -> one of 4 segments). Decides D9 concretely.
4. **[GATE 1]** boss reviews steps 1-3 outputs; confirms D1-D6, D9.
5. **Needed-weights counter** - new code ONLY under `zoo/fig1_energy_profiling/src/`; reads traces + manifest schedule, emits per-layer per-sample on-demand weight counts in Stage-A count schema. Validation: (a) density-1 run must equal baseline compulsory traffic; (b) 2 small layers hand-checked. Output: counter + `outputs/ideal_counts/` + validation note.
6. **[GATE 2]** boss reviews D7/D8 as implemented + validation evidence.
7. **SRAM sweep configs** - 9 config variants (3 arch x 3 sizes): hardware.json deltas limited to the weight-scratchpad capacity attribute; SHA-pinned. Output: `configs/` + manifest of SHAs.
8. **Baseline runs** - the ~90 spd-arm runs (D10 venue): trace gen (or reuse) -> nocsim counts -> Stage-A checkpoints under `outputs/baseline_counts/`. Idempotent per-case fingerprints as in the campaign.
9. **Pricing** - Stage-B over baseline counts (NG45 table) -> `outputs/baseline_priced.csv`; Ideal bars priced by substituting off-chip weight counts from step 5 into the matching baseline rows -> `outputs/ideal_priced.csv`.
10. **Aggregate + render** - whole-model sums over the 113-layer set, per-arch normalization, 95% CIs; render with the production version of fig1_mock.py -> `outputs/fig1_energy_profiling.{pdf,png}` + numbers table.
11. **[GATE 3]** boss reviews figure + numbers; caption text (2 methodology sentences) drafted alongside.
12. **Paper integration** - drop PDF into the paper repo, replace the placeholder block in 02_introduction.tex, update caption/Description. Done after boss sign-off only.

Dependencies: 1,2,3 parallel -> 4 -> 5 -> 6 -> (7,8 parallel with nothing) -> 9 -> 10 -> 11 -> 12. Steps 5 and 7 can be prepared concurrently after Gate 1; step 9's ideal half waits on Gate 2.

Estimated effort after each gate: Gate1->Gate2: ~1 day (counter + validation). Gate2->Gate3: a few hours compute + 2h analysis/render. Total new compute: ~90 small runs.
