# wt500_fig3cfg campaign handoff - state as of 2026-11-10

Written for restarting the work in a fresh tmux/team session. Everything below
is verified state, not plan. Repo: `/u/yyu9/projects/neuro_cache`, branch
`wcache-rebuild-phase-a` @ `1932ba7` (128 commits ahead of main; tracked tree
clean; untracked: `docs/plans/2026-11-10-weight-trace-500-campaign-plan.md`,
`zoo/wt500_fig3cfg/`).

## Goal

Weight traces for 5 SNN architectures (loas, ptb, spinalflow, prosperity,
gustavsnn, with gustavsnn executing LAST) x 8 benchmarks x all 500 samples,
from the fig3 config with user corrections: L1 weight 32,768 B, L2 weight
2,097,152 B, exactly 4 PEs/node, 16 nodes. Schedule solve on DeltaAI;
generation planned on Stokes (undecided, see open decisions); final traces
delivered to DeltaAI at `/work/nvme/bebv/yyu9/weight_traces/` with sha256
verification.

One-file sweep description: `zoo/wt500_fig3cfg/sweep_config.yaml`.
Plan doc: `docs/plans/2026-11-10-weight-trace-500-campaign-plan.md`.

## DONE and verified

### Configs (user-reviewed)
- `zoo/wt500_fig3cfg/arch.yaml` + `mapspaces/{loas,ptb,spinalflow,prosperity,gustavsnn}.yaml`.
- Open review flag: PTB mapspace uses **T: 64** (published window, matches
  PTBGen.h TW_SIZE 8x8); user recalled 32, never confirmed.

### Schedule solve stage (S2): RE-RUNNING AS MODE-SWEEPING, PARTIAL
The earlier DeltaAI pass was BASE mode and is superseded. The driver now
enumerates every traffic mode and keeps the best CoSA score, so all 755 pairs
are being re-solved, 5 arch shards into
`zoo/wt500_fig3cfg/outputs/<arch>/manifest.json` (there is no longer a single
top-level `outputs/manifest.json`). 755 valid (arch, capture-layer) pairs, 151
per arch; 30 excluded; 377,500 total (arch, layer, sample) cases.

State on disk as of 2026-11-11 07:40, the last shard write:
- **437 of 755 solved**, every winner OPTIMAL, no TIME_LIMIT winner.
  Winning modes: gb_oooo 237, gb_oook 152, base 20, dram_oook 15,
  dram_ooot 12, gb_ooot 1.
- **6 INFEASIBLE**, all prosperity, all A08 `vgg16_cifar10_loas_T32` layers
  01-06: genuine all-T-resident psum pressure on large spatial maps, not a
  bug. Policy: INFEASIBLE = recorded outcome, no trace.
- **312 ERROR with no schedule written**, spread over all five archs
  (gustavsnn 82, loas 81, ptb 53, spinalflow 50, prosperity 46). Every one is
  `solver_status: NO_OUTPUT` with returncode 130, 2 or 1 - the interruption
  signature, not a solver verdict. These pairs still need a re-solve before
  S2 can be called complete.
- Solver runs under `conda run -n gurobi`; `gen_inputs.py` has
  CONDA_ENV="gurobi" as its default, so no `--conda-env` flag is needed.
- Schedule cache is content-hash gated: artifacts store
  arch_yaml_sha256/mapspace_yaml_sha256; mismatch/missing means re-solve
  (`src/lays/scheduler/artifact.py`, `src/lays/scheduler/cli.py`). A prosperity
  mapspace revision would re-solve only prosperity's 151 pairs.

### Code changes, reviewed pass (all on this branch, uncommitted history in git)
- **WCTS v3** (gustavsnn): writer picks v3 via `trace.arch == "gustavsnn"`
  (`src/lays/cachesim/stream.py:219`); v2 = ticks strictly ascending per core,
  v3 = non-decreasing within core (equal tick = concurrent in-core bursts);
  byte-identical layout otherwise. Reader gate `native/.../stream_format.h`
  (versions 2+3); v3 tick rule enforced reader-side `stream_trace.cpp:283-290`
  (decl `stream_trace.h:56-57`), writer-side `stream.py:134-140`. Native suite:
  184 stream-trace checks green.
- **GustavSNN wave width is a runtime parameter** (no hardcoded PE_COUNT_MAX):
  derived per schedule as the NodeLevel spatial_split product
  (`weight_trace.py:37-58`, `node_level_spatial_product`), plumbed
  CLI to `_pack_task` to `main.cpp` (refuses nonpositive); `native_bridge.py`
  refuses non-int/<=0/missing; refused for non-gustavsnn archs.
- **Bridge gate fix** (`zoo/wt500_fig3cfg/gen_inputs.py:448`): missing HO/WO
  offset accepted iff `int(problem[name]) == 1` (matches bridge
  default-to-zero). Plus shared `sha256_file` import and
  missing_split_offset guard.
- **Prosperity per-CIN enumeration** (`prosperity/native_bridge.py`
  `_expand_cin_tiles`/`_combine_cin_results`): reviewed pass as T4 earlier;
  a later reviewer flagged it as "unrowed" by mistake. It does stale the
  "1 CIN" claims in `docs/weight_trace_gen_archs.md` (:29, :87, :470).
- `GustavGen.h` cleaned of lockstep framing (172 lines; two cosmetic leftovers
  at :70-71 and :120-121).
- Docs synced through earlier rows: `docs/atlas/{pipeline.md, README.md,
  cachesim_native.md, nocsim.md}`, `docs/REPRODUCE.md` (partially; see sync
  pass below).

### Pilot (S3): partial
- `outputs/pilot/{run2,run3}/`: LoAS 3, PTB 3, SpinalFlow small+medium
  measured clean: 32 rows, rc=0 (measurements.csv, selection.csv).
- **Blocker finding**: the 131,072-tile SpinalFlow C01 case ran >=23 min on
  ONE sample at ~15 GB RSS, so the flat 2000-case/90-min shard budget is dead.
  Shards must be weighted by tile count; heavy layers need dedicated
  shards/longer --time.
- Real gustavsnn artifact check (layer_04): NodeLevel COUT=2 x HO=2, product 4.

## CRITICAL fact: gustavsnn wave width

"Wave width = 4 in WT500" is FALSE as a flat claim. Sweep over all 151 solved
gustavsnn schedules: 145 give product 4, **five give 2, one gives 1** (the
HO=1 classifier/FC layers). The correct invariant everywhere (pilot checks,
docs, generation validation) is **width == that schedule's NodeLevel spatial
product**, never a constant. Places still carrying the flat "4":
`docs/weight_trace_gen_archs.md:31,:167,:471`, plan doc `:98`,
`sweep_config.yaml:67` comment, and the T22 pilot instruction wording.

## UNFINISHED work (exact findings, ready to redispatch)

### T14: archs.md doc fixes (reviewed FAIL, 3rd time; findings never reached implementer)
1. Flat "4 in WT500" at `docs/weight_trace_gen_archs.md:31,:167,:471`; fix to
   per-schedule spatial product (see CRITICAL fact above).
2. `:281-284` credits the v3 tick rule to `stream_format.h` (contains "tick"
   zero times); correct location is `stream_trace.cpp:283-290` /
   `stream_trace.h:56-57`.

### T21: dead-reference sweep (reviewed FAIL; findings never reached implementer)
Surviving references to deleted Python (address.py/cycles.py/reconstruct.py):
- `loas/LoASGen.h:7-9` (non_silent.reshape/num_batch numpy) and `:11-13`
  (.lines/.bitmask/.ptr/.bits deleted-dataclass attrs)
- `prosperity/ProsperityGen.h:154-156` (event_to_address/divmod)
Porting narration: `ProsperityGen.h:23`, `ptb/PTBGen.h:25-26`.
Broken sentences: `LoASGen.h:7`, `ProsperityGen.h:36-39` (unbalanced paren),
`spinalflow/SpinalFlowGen.h:61-63`.

### T22: generation pilot (was in progress; direction never delivered)
Corrected direction: exclude the 131,072-tile SpinalFlow C01 pathological
case from the normal pilot (substitute largest SpinalFlow layer under ~20k
tiles); ONE timed heavy-case run capped 3 h/60 GB via `/usr/bin/time -v` to
`pilot/heavy_case.log`; report tiles-per-layer so shard weights can be
derived; width check = per-schedule spatial product (6/151 artifacts give
2 or 1, so a flat-4 check would false-fail them).

### Consolidated doc sync pass (deliberately deferred until content rows close)
Conventions adopted: section-name citations for cross-file refs; "(N lines)"
line-count stamps for drift detection. Accumulated scope:
- `REPRODUCE.md`: inbound refs shifted NON-uniformly (+7 above old :81, +11
  below old :87); 19 pipeline.py off-by-one anchors; `:57` pre-existing
  overrun (cites trace.py:152-162 in a 160-line file; real block 150-159).
- `docs/plans/2026-10-29-l2-next-tile-demo-plan.md:158` (now 225-254), `:17/:50/:38`.
- `docs/demo_l2pf_artifact_prompt.md:75/:80/:89`.
- `docs/atlas/pipeline.md`: `:60/:112` "WCTS v2" now v2/v3; section 2.2
  weight_trace.py block missing wave_width kw + node_level_spatial_product;
  stale "(N lines)" at `:502/:604`; `:896` now `:905`; `:905` describes text
  T21 removes.
- `docs/atlas/README.md:85-86`.
- `archs.md` section-1 anchors: reconstruct_samples at weight_trace.py:188,
  assemble_layer_traces at :134, stream_weight_trace at stream.py:194,
  files-mode worker at cli.py:118; `:317` describes text T21 removes; "1 CIN"
  at `:29/:87/:470` stale after per-CIN enumeration.
- `GustavGen.h:70-71,:120-121` cosmetic leftovers.
- Plan doc `:98` flat "4".

## NOT started

- S4/S5 full generation (all 738 feasible pairs x 500 samples; gustavsnn
  last). Shard plan must be rebuilt with tile-count weighting from pilot data.
- S6 delivery to `/work/nvme/bebv/yyu9/weight_traces/` + sha256 and
  exact-coverage verification.
- Final campaign write-up.
- **No production weight traces exist yet**: only schedules + pilot traces.

## Open user decisions

1. **Q5, where to generate**: Stokes (needs SSH alias + node-helper name from
   user) vs generating directly on DeltaAI into the destination.
2. **6 prosperity infeasibles**, all A08 `vgg16_cifar10_loas_T32` layers
   01-06: accept the gaps vs revise the prosperity mapspace (hash cache
   limits re-solve to prosperity's 151 pairs). The decision stands - fewer
   gaps, same question.
3. **PTB T: 64 vs 32** (review flag in mapspaces/ptb.yaml).

## Inputs reference

8 captures under `/work/nvme/bebv/yyu9/input_trace_delta/`, all n_samples 500:
A02/spikformer_4_384_cifar100_T4, A04/sdt_2_512_cifar100_T4,
A07/spikinglm_t4_T4 (72-layer spiking LM), A08/vgg16_cifar10_loas_T32,
B09/loas_vgg16_T4, B09/loas_resnet19_T4, C01/sma_azo_vgg_cifar10_dvs_T10,
C01/sma_azo_vgg_dvs128_gesture_T16.

## Operating constraints to carry into any new session

- User email is private; never share externally.
- Workers/subagents get git read-only (no checkout/restore/reset/clean/stash);
  never `git add -A`; commits only when the user asks, only by the manager.
- Long jobs via `setsid`, stopped by process group; never signal processes you
  did not start.
