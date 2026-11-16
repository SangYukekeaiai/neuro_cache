# T100 reproduction log

Target: LoAS-only, multi-node campaign mapping, count/cycle comparison with Sparseloop. Tier B/C require GATE V release. All generated files and dependencies remain in this task directory.

## Source pins

- MICRO’22 artifact: `vendor/micro22-sparseloop-artifact` (exact clone commit recorded in the environment manifest).
- Its infrastructure: `4a958cf1311609765179c1f5500ae19d44f0432f`.
- Timeloop: `1eb0fd0a62fea1f3df4580a1b6c7ae6238772fbb`, including `real-data` density support.
- Accelergy: `34df8e87a889ae55cecba58992d4573466b40565` (0.3).

The newer infrastructure was inspected but is not the selected backend: its density factory omits real-data. See `docs/O2_actual_data.md`.

## Ingest

`src/ingest.py` takes external roots only for S0. `inputs/snapshot_manifest.json` records source digests, copied-file digests, selected samples and all resulting files. Retained rows are LoAS/spad only; NG45 energies are discarded. Lossless spike subsets support later mask generation without external reads. The scoped runtime source snapshot supports later nocsim execution without importing another zoo task.

The first ingest encountered CSV cycles formatted as `103485.0`; its log is retained in `outputs/self_checks/ingest_csv_integer_failure.log`. Parsing with Decimal preserves exact comparison against the integer nocsim value. No simulation was rerun.

## Installation

`bash src/install_stokes.sh` on Stokes creates `vendor/envs/tlv`, installs the paper-pinned Accelergy through pip and builds paper-pinned Timeloop with `scons -j2 --accelergy`. Conda supplies dependencies instead of the Dockerfile's root apt commands. The upstream PAT symlink follows its Dockerfile. No model-source edits are intended.

## Current checks

S0 verifies 545 snapshot files locally and on Stokes. The pinned Stokes backend passes its shipped DSTC example; 299 backend source files match their recorded hashes. The logic-only Accelergy check reproduces 0.00855238 pJ for five additions exactly. Full campaign mappings and the memory ERT await the decisions in `docs/open_mapping_questions.md`. No Tier B/C runs have started.

## Installation evidence

The first Stokes compile completed C++ compilation but linking failed with `cannot find -lstdc++`: system GCC8.5 lacks its static runtime. The failed log and objects are retained under `outputs/install_gcc8_link_failure.log` and `outputs/build_gcc8/` on Stokes. The rebuild loads the existing `gcc/gcc-11.2.0` module, whose static runtime exists. No Timeloop model-source change is involved.

GCC11 treats an upstream `assert(total_counts = ...)` assignment as a fatal parentheses warning under the project's `-Werror`. That failed log/build is retained as `outputs/install_gcc11_warning_failure.log` / `outputs/build_gcc11/`. The selected toolchain is the available GCC9.1 module, closer to the artifact's original environment. The assertion is not changed, and no warning-suppression or numerical patch is applied.

The LoAS-only cycles layout is in `docs/validation_mock.{pdf,png}`. Values are explicitly synthetic; error annotations remain pending. This is a layout review artifact, not experimental evidence. Its prior version is retained in `outputs/archive/layout_before_loas_only.tar.gz`.

GCC9 compiled the backend but the initial Conda YAML0.7 binary required `GLIBCXX_3.4.29`, newer than GCC9's static runtime. `src/pin_build_dependencies.sh` pins YAML0.6.3 and libconfig1.7.2 to the artifact-era dependency API and rebuilds only `build/timeloop-model` (no mapper search is needed). The ABI failure log remains in `outputs/install_gcc9_dependency_failure.log`. This is environment reconstruction, not a model patch.

The dependency downgrade completed, but reloading the already-loaded Anaconda module in a nested shell entered a `conda deactivate` loop. The owned installer process group was verified and terminated; its log is `outputs/install_module_reload_failure.log`. The installer now checks `module is-loaded` before loading each module. No shared module configuration was changed.

After downgrading YAML, cached objects still referenced YAML0.7 symbols. Their build tree and log are retained as `outputs/build_gcc9_yaml07/` and `outputs/install_stale_yaml_objects.log`. A clean rebuild against YAML0.6.3 is required because the upstream build does not invalidate all objects for headers provided through the environment include path.

## Completed installation check

The clean GCC9.1 build against YAML0.6.3 passes the unchanged shipped example. `outputs/env_manifest.json` records the executable SHA, source pins, command, and seven output hashes; `outputs/conda_explicit.txt` and `outputs/smoke/pip_freeze.txt` record the environment. Run `bash src/run_smoke_stokes.sh` inside the Stokes task directory to repeat the check. This example establishes installation functionality, not LoAS model agreement. `outputs/self_checks/ert_logic/verification.json` records the separate logic-only ERT conversion check.
