# Layer swap plan: context for the Delta run

Written 2026-08-23 on CECSUnaryLab. **Nothing below has run.** Under ruling
R7 (`log/2026-08-20-phaseD-sweep-profiling-plan.md`, rulings table) the Stage 1
solve and Stage 2 trace generation belong on NCSA Delta
(`/u/yyu9/projects/neuro_cache`). This note is the handoff for that session.

## What the survey settled

Full answer with citations: `HANDOFF-ANSWER.md` (same directory). Vault survey:
`research/surveys/snn-spike-sparsity-cifar10/`.

- The capture is correct. Converted into LoAS's own measurement convention it
  reproduces the authors' released `reference.txt`: vgg16 82.56% / 74.06% vs
  82.325% / 74.09% (sparsity / silent); resnet19 71.98% / 62.92% vs
  68.67% / 59.59%.
- The ~0.10 density expectation was the error. LoAS Table II
  (MICRO 2024, DOI 10.1109/MICRO61859.2024.00084) reports ResNet19 at 68.6%
  sparsity (density 0.314) and its deepest per-layer entry R-L19 at 57.9%
  (density 0.421). The "~90%" in the intro is a citation chain the table
  contradicts.
- Density falls with depth in the literature (VGG-family, tdBN's ResNet-19).
  0.6-0.92 in a trained binary layer is reported nowhere. resnet19
  `layer2_2_conv2` at 0.917 is an oddity of the released artifact.
- Verdict: current traces are usable only as a stated low-sparsity stress
  case tied to a real published artifact, not as a representative workload.
- Comperity (TACO 23(3), 2026, DOI 10.1145/3828526): VGG16, ResNet18,
  Spikformer, SDT, SpikeBERT at 7.1-23.0% density, but no T, checkpoints,
  code or per-layer data. If its workload list is adopted, source models via
  Prosperity's artifact (T=4 members only).

## Decisions taken (user, 2026-08-23)

1. **vgg16: swap `layer_09_features_30` (density 0.578) for
   `layer_08_features_27` (density 0.1995).** HANDOFF.md states the derived
   workload is identical, `KH3 KW3 CIN512 COUT512 HO4 WO4 T4`, so the Stage 1
   schedule should be reusable. Verify that against the workload/config files
   and how the schedule is keyed before reusing; re-solve if keyed by name.
2. **resnet19: swap `layer_16_layer3_0_conv2` (density 0.424) for
   `layer_09_layer2_0_conv2` (density 0.184; CIN 256, COUT 128, HO 8) as the
   representative layer.** New workload shape: needs a fresh Stage 1 solve.
3. **Redo Stage 2** (`scripts/generate_weight_traces.py`) for both new layers
   over the same five paired samples in
   `input_trace/loas/{vgg16_T4_n5,resnet19_T4_n5}/`, then re-apply the 0823
   independent-reconstruction check and record per-sample input density.

Old layers' Stage 1/2 artifacts and the `cache16_results.csv` rows that use
them are kept and to be labelled superseded / stress case, not deleted.

## Rules to follow on Delta

- R7: campaign work on Delta, through Slurm where the existing procedure did.
- Python only as `conda run -n "$CONDA_ENV" --no-capture-output python`.
- Stage 1 at NoC global buffer 2 MiB, per-node 32 KiB, 30:1:1 split, 16 cores,
  LoAS dataflow; match `stage1_mip_solver/outputs/RESULTS.md`.
- n = 5, indices `[2697, 3078, 5110, 6367, 8502]`, paired; report per-sample
  ratio with median + full range, no t-test; raise n if range > 5% of median.
- R1 stream-header rulings for the trace format; R2/R6 L1 axis
  {2, 4, 8, 16, 32} KB unchanged.
- Verify before claiming done; keep command output in the write-up.

## Deliverable expected from the Delta session

`profiling/0823_stagewise_verify/LAYER_SWAP.md`: what was swapped, exact
commands and host, per-sample densities of the new traces, verification
results, and what remains for Stages 3-4 / campaign re-runs.

## Ground truth gathered locally (read-only scout, 2026-08-23)

- **`features_27` == `features_30` workload: confirmed.** Shapes are derived
  at run time in `src/archmodels/trace.py:105-143` (`HO = Hin`, `COUT` = next
  layer's CIN). `meta.json` gives both layers `[4, 5, 512, 4, 4]` with next
  CIN 512, so the derived YAML is byte-identical to
  `stage1_mip_solver/inputs/workloads/vgg16_T4_all__layer_09_features_30.yaml`.
- **The Stage 1 schedule is keyed by layer name**, in the path
  (`outputs/schedules/pe16/loas/vgg16_T4_all/<layer>.json`) and the body
  (`layer_name`, `trace_dir`). Copy-and-rename would work, but a fresh solve is
  deterministic (verified byte-identical on 0823) and takes minutes: prefer
  re-solving. `resnet19 layer_09_layer2_0_conv2` is `[4, 5, 256, 8, 8]`, next
  CIN 128, so CIN 256 / COUT 128 / HO 8 / WO 8, a genuinely new solve.
- **Stage 1 entry point:** `stage1_mip_solver/run_stage1.py`, no CLI; edit
  `LAYERS` at lines 44-48. Canonical arch
  `inputs/arch/loas_inst16_node32kb_noc2MiB_pe16.yaml` (NoC weight 1966080 B,
  node weight 30720 B, `entries` are bytes). Run as `conda run -n base`,
  gurobipy 13.0.2, needs `GRB_LICENSE_FILE` and `PYTHONPATH=src`.
- **Stage 2 invocation actually used** (`stage2_weight_trace/outputs/logs/*.log`):
  `generate_weight_traces.py --arch loas --trace-root <stage2>/inputs/input_trace
  --trace-dir vgg16_T4_n5 --layer <layer> --schedule-cache <stage2>/inputs/schedules
  --workers 1 --out-dir <stage2>/outputs/weight_traces --combo-tag noc2MiB_node32kb
  --sample-start 0 --sample-count 5`; pass B adds `--stream --sample-count 1
  --dump-trace .../stream/<layer>_s00000.wcts`. Those logs used a bare
  interpreter path; the redo must use `conda run -n`.
- Per-sample input density is computed by `run_stage2.py:148-172` into
  `outputs/stage2_report.json` (`combos/<trace_dir>/<layer>/input_trace[]`).
- **The exact-integer NumPy reconstruction check from CONCLUSIONS.md was not
  committed.** Only `run_stage2.py` and `wcts_excerpt.py` exist. To re-apply it
  on the new layers it must be rewritten per `stage2_weight_trace/outputs/RESULTS.md:131-135`
  and committed this time.
- Nothing under `profiling/0820_phaseD_spad_vs_cache/grids/` names any layer;
  the Phase D grids do not yet carry the layer picks. `stage3_nocsim/` and
  `stage4_wcache/` directories do not exist.
- Host `CECSUnaryLab`: no Slurm, no `/u` or `/work` paths, no `cosa_snn` env
  (only `base`, `env_name`, `gurobi`). All Delta paths in logs are unresolvable
  here.
