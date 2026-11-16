# Figure 1 (fig:energy-profiling) work plan - PLAN ONLY, NOT IMPLEMENTED, AWAITING BOSS REVIEW

Paper target: `2027_ASPLOS_neuro_cache/src/02_introduction.tex`, `\label{fig:energy-profiling}`.
Message the figure must carry: off-chip weight movement dominates baseline SNN-accelerator energy, persists across SRAM sizes, and collapses when only needed weights are loaded.

Boss decisions already made (2026-11-16):
- Single-node baselines, as published. No multi-node content.
- Whole-model energy, mean across input samples (CI from sample spread).
- Fixed inherent scheduling per architecture (manifest schedules, untouched).
- Baseline bars from the standard energy model; Ideal bar substitutes ONLY the weight-access count (on-demand, derived from the input trace); all other event energies unchanged; TIME FIXED (energy-only substitution, leakage x time unchanged) - both stated in the caption.
- Layout approved via mockup (docs/fig1_mockup.{png,pdf}, generator docs/fig1_mock.py): per architecture 4 bars = baseline@{64KB,256KB,1MB} + Ideal@256KB; stacked segments compute / on-chip SRAM / off-chip weights / off-chip other; normalized to baseline@256KB=1.0; hatched substituted segment on Ideal.

## Stage 0 - selection (data query only, no new simulation)

0a. Rank the 5 architectures by measured weight-trace generation + simulation wall time from the Stage-A receipts of the 23 fetched samples. Deliver a table; pick the 3 fastest (expected PTB / LoAS / GustavSNN; SpinalFlow expected slowest - verify, do not assume).
0b. Rank benchmarks among the small-trace set (B09, A02, A04, A08) by: off-chip-weight energy fraction (from existing NG45 rows) x estimated all-vs-needed weight gap x 1/trace-size. Deliver the ranking; provisional pick B09 - confirm with data.
REVIEW GATE 1: boss approves the 3 architectures + 1 benchmark before any new runs.

## Stage 1 - needed-weights (ideal) counts

- Definition: per layer, per sample, the on-demand weight-access count = weights actually touched given the nonzero spikes of the input trace, under the architecture's inherent schedule (unique fetches at the off-chip level; derived from the analytic count stage, no simulator changes).
- Implementation: a small counts-mode addition in the fig1 folder only (no edits to the campaign's Stage-A code paths; reuse its readers). Output schema mirrors Stage-A counts so Stage-B pricing applies unchanged.
- Validation: dense sanity (density 1 -> needed == loaded per compulsory traffic), plus 2 hand-checked small layers.
REVIEW GATE 2: boss reviews the counting definition + validation before the sweep.

## Stage 2 - SRAM sweep runs

- Baseline spd-arm runs for the chosen benchmark x 3 architectures x 3 weight-scratchpad sizes {64KB, 256KB, 1MB} x N samples (propose N=10; CI from samples; raise only if CIs are wide).
- All other hardware parameters unchanged from hardware.json; scheduling unchanged; NG45 table (ASAP7 later by reprice only).
- Venue: wherever compute is available at the time (Delta login-scale is enough: ~90 runs of one benchmark).

## Stage 3 - pricing + figure

- Stage-B pricing of baseline runs as usual; Ideal bar priced by substituting the off-chip weight-access count with Stage-1 numbers (and implied fills), everything else from the matching baseline run.
- Render with the approved generator (docs/fig1_mock.py promoted to production script), real numbers + error bars; export PDF for the paper + PNG preview.
- Caption drafted with the two methodology sentences (energy-only substitution; time fixed).
REVIEW GATE 3: boss reviews numbers + figure before it enters the draft.

## Non-goals

- No multi-node, no cache arms, no Prosperity detector modeling, no schedule changes, no ASAP7 blocking (reprice later).

## Estimated effort once approved

Stage 0: ~1 h (queries over fetched rows/receipts). Stage 1: ~0.5-1 day incl. validation. Stage 2: a few hours of compute. Stage 3: ~2 h.
