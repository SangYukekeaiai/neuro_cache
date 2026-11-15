# Fig12 NoC replay

```python
from zoo.fig12_edp.nocsim.driver import run_case

noc = run_case(schedule_path, arch_name, wcts_path, output_dir)
```

With `zoo/fig12_edp` on `sys.path`, `from nocsim.driver import run_case`
also works. The repository's `src` must be on `PYTHONPATH`.

The schedule is a saved `ScheduleArtifact` JSON. The third argument accepts
an existing uncompressed native WCTS v2/v3 or a generated per-step JSON,
including `.json.gz`. Alternatively pass `wcts_path=` or `steps_path=` and
`output_dir=`. Exactly one sample source is required. No trace generation
occurs here: generate once, then reuse that WCTS for both cache arms and
this driver. Raw spike captures are not an input to this API.

`arch_path=` overrides the schedule's `result.configs.arch`. Relative config
paths resolve against the repository. A recorded `arch_yaml_sha256`, when
present, must match. `eventsim_binary=` overrides the existing compiled
backend. `frequency_hz=` defaults to 500,000,000; it converts cycles to time
and does not change the architecture's DRAM occupancy setting.

The returned dict is also saved as `output_dir/result.json`. Its keys for
the energy join are:

| Key | Unit / meaning |
|---|---|
| `weight_packet_hops` | Packets times directed XY route/tree edges; excludes the DRAM bus |
| `chain_packet_hops` | Sum of k-chain and t-chain neighbor packet-hops; retain in **every arm** |
| `gb_reads`, `gb_writes` | 32-byte words, once per send/fill; multicast reads once |
| `l1_delivery_bytes` | Packet-padded weight bytes delivered, summed across receiving nodes |
| `dram_accesses` | 64-byte bursts, rounded up independently per DRAM transaction |
| `dram_bytes` | Physical burst bytes, exactly `64 * dram_accesses` |
| `total_cycles` | Contention-aware eventsim makespan, including stored compute cycles |

Diagnostics include `k_chain_packet_hops`, `t_chain_packet_hops`, weight
unicast/multicast packet-hop splits, `dram_transactions` (CSV row count),
`dram_payload_bytes` (before 64-byte burst rounding), `transaction_count`,
`frequency_hz`, `time_seconds`, identity, topology, free-boundary flags,
eventsim's cycle breakdown, input hashes and the transaction CSV checksum.
GB words count the actual 32-byte packets in tc.csv; extra DRAM burst
padding is charged to DRAM only. `psum_boundary_bytes` and
`vmem_boundary_bytes` are zero, guarded both by decoded schedule flags and
by rejecting unexpected boundary traffic in the parser.

`parse_tc_csv(path, *, X, Y, gb_port=None, dram_port=None)` exposes the
counts parser separately. It requires the original annotation lines.
Multicast counts use `NoC.count_hops`, the union of directed XY edges,
not the number of receivers or the latency heuristic in `TC_Generator`.

WCTS frame MAC cycles already contain the **maximum across cores**. The
reader uses that scalar unchanged and validates header identity, workload,
spatial factors, tile count/order, core block sizes, payload bounds and
trailer totals. It skips weight-address records; it does not revalidate
their semantic contents. The producer must use this schedule: WCTS has no
schedule hash or temporal-loop identity field. Generated step JSON uses
the existing `load_step_cycles` loader and identity check. Missing LIF
cycles mean no additional LIF COUNT time, as in the upstream native
generator (`mac_cycles` holds the tile's compute time). Explicit JSON LIF
cycles are preserved. No dense compute estimate is used.

Outputs are `tc.csv` and `result.json`, staged, fsynced and renamed with
the result published last. A per-directory lock serializes duplicate runs.
Resume rehashes schedule, sample, arch config, simulator binary and relevant
source, checks frequency and the saved CSV checksum, and reuses only a
matching result. Changed inputs or a damaged committed CSV raise
`ValueError`; use a fresh output directory for a different case/config.
Keep the sample available until resume checking is complete.

CLI from the repository root:

```bash
PYTHONPATH=src:. conda run -n fig12-archx python -m zoo.fig12_edp.nocsim \
  --schedule schedule.json --arch spinalflow --trace sample_00000.wcts \
  --out case_output
```

Tests run a tiny sparse sample through the existing `spinalflowgen` native
binary once per fixture, save WCTS plus per-step JSON, and compare their
actual eventsim output. They check max-over-cores, both chain types,
multicast edges, burst rounding, malformed streams, boundary rejection,
resume checks and failed-run publication. No corpus capture is needed.

```bash
mkdir -p zoo/fig12_edp/nocsim/.testtmp
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 BLIS_NUM_THREADS=1 \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. \
TMPDIR="$PWD/zoo/fig12_edp/nocsim/.testtmp" \
conda run -n fig12-archx python -m pytest -q -s -p no:cacheprovider \
  zoo/fig12_edp/nocsim/test_nocsim.py \
  --basetemp=zoo/fig12_edp/nocsim/.testtmp/pytest
```
