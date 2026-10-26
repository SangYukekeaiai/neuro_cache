# Untracked run outputs

On 2026-10-25 these two directories were removed from git (`git rm --cached`)
and added to the root .gitignore. History was not rewritten.

| path (under stage3_nocsim/outputs/) | files | bytes |
|---|---|---|
| weight_traces_single_node/loas/single_node/{vgg16,resnet19}_T4_n5/*/sample_0000{0..4}.json.gz | 20 | 286,166,832 |
| tc/{V8,V9,R9,R16}_s0000{0..4}.csv | 20 | 24,704,980 |

Total 310,871,812 bytes (about 311 MB). The files exist only in the working
copy at /home/ya867177/neuro_cache-wcache, at the same relative paths. Other
checkouts and fresh clones do not have them. No code in the repo reads them.

Get them back from history (commit d2a9de8, the last commit that tracks them):

    git checkout d2a9de8 -- profiling/0823_stagewise_verify/stage3_nocsim/outputs/tc
    git show d2a9de8:<path> > <path>

`git checkout` also stages them again; run `git rm -r --cached <dir>` after it
to keep them untracked.

Regenerate (from the repo root; use a Python env with numpy and PyYAML, e.g.
.baseline/venv/bin/python in this checkout):

- weight_traces_single_node/: run `make -C src/archmodels/loas` first (the
  loasgen binary is gitignored). Then run the generator directly, once per
  (trace dir, layer) in its COMBOS. Do not use `stage3_nocsim/run_armS_stage12.py`:
  it re-solves with Gurobi and overwrites the tracked schedules that the
  reference case uses.

      PYTHONPATH=src <python> scripts/generate_weight_traces.py --arch loas \
        --trace-root input_trace/loas --trace-dir vgg16_T4_n5 --layer layer_08_features_27 \
        --schedule-cache profiling/0823_stagewise_verify/stage3_nocsim/inputs/schedules_single_node \
        --out-dir profiling/0823_stagewise_verify/stage3_nocsim/outputs/weight_traces_single_node \
        --combo-tag single_node --sample-start 0 --sample-count 5 --workers 1

  The other combos are vgg16_T4_n5/layer_09_features_30,
  resnet19_T4_n5/layer_09_layer2_0_conv2 and resnet19_T4_n5/layer_16_layer3_0_conv2.
  Existing samples are skipped unless `--force` is given. The decompressed JSON
  matches the stored file (checked on vgg16 layer_08 sample 0; the .gz header
  timestamp differs).
- tc/: run `stage3_nocsim/run_stage3.py`, after `stage2_weight_trace/run_stage2.py`
  has written `stage2_weight_trace/outputs/weight_traces/` (run_stage2.py reads
  the tracked Stage 1 schedules and does not call the solver). Needs the
  eventsim binary (`make -C src/nocsim/eventsim`) and the loasgen bridge
  (`make -C src/archmodels/loas`). Both runners also rewrite tracked files
  (their inputs/ manifests, schedules or layer yamls, logs and result JSONs).
