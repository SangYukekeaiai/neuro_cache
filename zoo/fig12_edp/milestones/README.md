# First 100 complete samples

This independent watcher reads committed Stage-B products from Stokes, Delta and
DeltaAI. It never submits, holds, stops, prices or simulates campaign work. The
campaign continues through the milestone.

`config.json` defines the front roots, existing SSH control sockets and the
output workspace. Remote access uses only those authenticated masters, with
password prompting and fresh connections disabled. A failed remote request
suspends that connection until its master socket is replaced or an operator
clears its entry in `blocked_connections.json`. Missing front inventories delay
publication; they do not stop any campaign controller.

Every ten minutes the watcher inventories full commits and copies at most the
first 100 into the milestone workspace. Every committed artifact is SHA-verified,
then row arithmetic and coverage are checked. Quarantined partial samples do not
count. A commit newer than the earliest front inventory time waits for the next
poll, so a scan racing a new commit cannot choose a different first-100 cohort.
Duplicate sample IDs across fronts fail closed.

At 100 verified commits, `snapshot_partial100.json` freezes the sample IDs,
fronts, original paths, commit times and commit hashes. Outputs are published
atomically in `partial100/` only after collection and all three plots succeed:

- `results_partial100.csv`: 167,700 original layer/arm rows, with source-front and
  commit provenance added.
- `case_statistics_partial100.csv`: per-case means and 95% confidence intervals.
- `whole_model_partial100.csv`: per-benchmark/architecture/arm means and CIs.
- `figures/model_{latency,energy,edp}_overview_partial100.{pdf,png}` and captions.
- `collection.json` and `artifact_sha256.json`: aggregation rules and output hashes.

Whole-model energy and latency are summed **within each sample**. Model EDP is
that sample's summed energy times its summed latency. Means and percentile
bootstrap 95% CIs are then computed across samples using 2,000 resamples and seed
100. The same resampled sample IDs apply to every case, metric and arm. The three
Prosperity A08 groups have incomplete nominal layer coverage: totals/CIs stay
blank and the figures show hatches, never partial bars.

The cohort is completion-selected, not a random sample of the 500-sample
campaign. CIs measure sample variation, not completion-selection bias or energy
model uncertainty. Energy/EDP retain the NanGate45 interim caveat and full table
SHA; latency is count-derived at 500 MHz and table-independent.

`status.json` reports full commits, quarantined partials and per-front six-hour
commit rates. Its hours-to-target is explicitly a conditional rate extrapolation,
not a scheduler forecast. Stokes owns only 000–059; until another front has
measured throughput, extrapolating Stokes alone cannot establish an ETA to 100.

Run and reproduce (from the repository root):

```sh
bash zoo/fig12_edp/milestones/launch.sh
conda run -n fig12-archx python -B zoo/fig12_edp/milestones/collect.py \
  --snapshot /work/hdd/bebv/yyu9/fig12_full500_milestone/snapshot_partial100.json \
  --out /tmp/partial100-reproduction
conda run -n gurobi python -B zoo/fig12_edp/milestones/plot.py \
  --input /tmp/partial100-reproduction
conda run -n fig12-archx python -B -m pytest -q zoo/fig12_edp/milestones
```

Reports are sent to manager pane `%0` every two hours and when figures are ready.
A copy-mode rejection is recorded in `report_delivery.json`; the next poll retries
the notification without affecting collection or campaign work.

The watcher log is `watch.log` in the configured workspace. Its tmux session is
`fig12-partial100`; a user scope caps memory at 4 GiB and tasks at 32. Thread caps
are set by `launch.sh`. No campaign source, receipt, checkpoint or ledger is
modified. The collector exits after publishing the milestone products.
