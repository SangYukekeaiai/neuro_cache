# Three-arm simulation driver

`run.py` generates one weight stream per selected sample, saves its record count,
runs NoC/event timing and both cache configurations, then calls the mandatory
[archx energy model](../../archx/zoo/snn_edp/README.md). Three result rows are
committed before the transient stream is deleted. Pending characterization is
zero plus explicit incomplete reasons; time uses 500 MHz by default.

The manifest contains 749 feasible schedules; execution keeps the 559 pairs
selected by [workload_layer_scope.md](../docs/workload_layer_scope.md).
`--smoke` selects the smallest kept layer per architecture. Production configs
live in `../configs/production_cache_{a,b}.json`. The native simulator is
`native_build/cachesim_run`; its source-staleness guard must pass.

For a future authorized execution, use the bounded
[all-benchmark driver](all_bench/README.md). Model-only verification and
repricing need no traces or simulation; their commands and pinned fixtures
are in the model README. The parked remote deployment scripts remain under
`../run_ec2/`; their generated outputs are not retained.
