# Rented-host staging checklist

These are preparation instructions, not an executed rental or cloud launch.
Do not rebuild shared Delta sources or binaries while T84 runs. The native
build commands below run **only in the separate rented-host checkout**.

1. Choose CPU/RAM and storage from measurements. The pause log measured about
   63 GiB RSS for one near-worst sample and extrapolated 140–200 GiB for the
   worst. Giant workers must be serial. `rented.example.json` reserves up to
   224 GiB for one giant, four small workers at most, and 4 GiB for the driver,
   within a 240 GiB configured budget. A machine needs additional OS headroom;
   measure available RAM and adjust the budget/tiers rather than assuming all
   advertised RAM is free. Some conservative estimates exceed 224 GiB and
   will be explicitly skipped, not called complete. No GPU or Slurm is needed.

2. Transfer one consistent `neuro_cache_wcache/` checkout, including its
   vendored `zoo/archx/` backend and `zoo/archx/zoo/snn_edp/` model/table, plus the capture tree (~33 GB),
   production cache configs from `zoo/fig12_edp/configs/`, and release schedule archive. For example,
   from Delta after setting `RENTED` to the chosen host (not executed here):

   ```bash
   rsync -a --exclude=.git --exclude='__pycache__' \
     --exclude='zoo/wt500_fig3cfg/outputs' --exclude='zoo/wt500_fig3cfg/stokes' \
     --exclude='zoo/fig12_edp/demo/all_bench/cases' --exclude='zoo/fig12_edp/demo/vgg16_full/cases' \
     --exclude='zoo/fig12_edp/run_ec2/mini_output' --exclude='zoo/fig12_edp/run_ec2/test_tmp' \
     /u/yyu9/projects/neuro_cache_wcache/ "$RENTED:~/neuro_cache_wcache/"
   rsync -a --info=progress2 /work/nvme/bebv/yyu9/input_trace_delta/ \
     "$RENTED:/data/input_trace_delta/"
   ```

   This reads Delta inputs; it does not modify captures, Stokes or protected
   outputs. Pause transfer or use a consistent source snapshot if shared source
   is being edited. `record_estimates.json` travels with T71, so no Stokes tree
   is needed on the rented host.

3. On the rented host, verify the release archive's supplied checksum, inspect
   members, and extract into a fresh staging directory, not protected outputs:

   ```bash
   cd ~/neuro_cache_wcache/zoo/wt500_fig3cfg
   sha256sum -c release/s2_schedules.tar.gz.sha256
   tar -tzf release/s2_schedules.tar.gz
   mkdir -p /data/fig12-schedules
   tar -xzf release/s2_schedules.tar.gz -C /data/fig12-schedules
   ```

   Set `manifest` to `/data/fig12-schedules/manifest.json`. The runner preflight
   verifies every feasible schedule SHA256 against the manifest, requires
   exactly 749 feasible plus six infeasible rows, and checks the explicit
   architecture YAML against the solved schedule hash. It hashes selected
   capture, next-density capture and metadata contents, not just timestamps.

4. On the rented host, install the environment. Conda is the primary path:

   ```bash
   cd ~/neuro_cache_wcache
   conda create -n fig12-archx python=3.12 numpy pyyaml matplotlib pytest
   conda run -n fig12-archx python -m pip install -e . --no-build-isolation
   ```

   Install the bundled backend from local source, with Rust/Cargo available:

   ```bash
   CARGO_BUILD_JOBS=1 conda run -n fig12-archx python -m pip install -e ./zoo/archx
   ```

   No archx source is fetched or transferred separately. See
   [VENDOR.md](../../archx/VENDOR.md) for build prerequisites. The model defaults
   to `zoo/archx/zoo/snn_edp`; `SNN_EDP_MODEL_ROOT` is an explicit override.
   Both entry points pin `zoo/archx/src` as their backend. Update the configured
   `energy_table` to `zoo/archx/zoo/snn_edp/energy_table.json`.

   Set `plot_command` to `["conda","run","--no-capture-output","-n",
   "fig12-archx","python","-B"]`. An existing Python 3.12 venv is also supported:
   create it on the rented host, install numpy/PyYAML/matplotlib/pytest and the
   editable repo there, use its absolute interpreter to launch `run.py`, and
   set `plot_command` to that interpreter plus `-B`. Delta checks use only
   `fig12-archx` (plots in `gurobi`); no environment installation was done here.

5. **On the rented host only**, force native rebuilds; executable bits do not
   prove ABI compatibility. Install a C++17 compiler and GNU make first.

   ```bash
   cd ~/neuro_cache_wcache
   for arch in spinalflow ptb loas gustavsnn prosperity; do
     make -B -j1 -C "src/lays/weight_trace_gen/$arch"
   done
   make -B -j1 -C src/lays/nocsim/eventsim
   make -B -j1 -C src/lays/cachesim/native MODE=release \
     BUILDDIR="$PWD/zoo/fig12_edp/run_ec2/native_build" \
     "$PWD/zoo/fig12_edp/run_ec2/native_build/cachesim_run"
   ```

   Recreate the tiny two-sample configuration with rented-host paths and run
   it under the same 4 GiB constraints before a full campaign. This exercises
   binary loading and simulation, not just `test -x`. Do not reuse Delta
   campaign fingerprints after rebuilding different native binaries.

6. Check actual storage and memory before launching:

   ```bash
   findmnt -T /mnt/nvme
   findmnt -T /data
   lsblk -d -o NAME,MODEL,ROTA,TRAN
   df -h /mnt/nvme /data
   free -h
   ```

   Use local NVMe for `scratch`, including native TMPDIR; avoid `/dev/shm`
   because its pages consume the memory budget. Use a persistent separate tree
   for `output`. The example requires 150 GiB of scratch free before each
   worker launch. Native temporary output measured ~89 bytes/record, and raw
   WCTS ~20.6 bytes/record, so the worst samples need tens of GiB of scratch.
   Do not materialize the full ~23-TB compressed trace campaign. Durable
   outputs retain NoC traffic CSVs and simulator/count metadata; estimate
   persistent capacity from measured per-case sizes before the rental. It is
   not safe to assume they total only a few GB across 374,500 cases.

7. Copy `rented.example.json` to `rented.json` under this folder and set every
   machine path, budget and plotting command. Confirm A is unchanged L1 d4,
   L2 d1, min_touches9, and B matches its pinned SHA256. Run preflight, which
   creates only manifests/configuration, then review the reported memory:

   ```bash
   conda run -n fig12-archx python -B zoo/fig12_edp/run_ec2/run.py \
     --config zoo/fig12_edp/run_ec2/rented.json --preflight
   ```

8. After host selection and validation, launch the command in README.md.
   Sample 0 finishes attempts across the full selected grid and emits its
   CSV/figure checkpoint before sample 1. Never treat `case_limit>0` or a
   nonempty `case_keys` subset as all-benchmark completion. The known
   Prosperity zero-MAC/native rejection remains a shared-source blocker;
   this runner reports it as a failure and does not change its semantics.

9. Return durable results without touching the active Delta demo:

   ```bash
   rsync -a --partial --info=progress2 "$RENTED:/data/fig12-results/" \
     /u/yyu9/projects/neuro_cache_wcache/zoo/fig12_edp/run_ec2/returned/
   ```

   Transfer `campaign.json`, configs, selection, checkpoints, events and case
   folders together. Keep the rented output until return checksums validate.
   Rebuilding/changing scientific inputs requires a new output root; do not
   silently merge incompatible campaigns or use a mini checkpoint as full.
