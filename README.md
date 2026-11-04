# lays

## Overview

lays simulates spiking neural network (SNN) accelerators on captured spike
traces with four components. The **SNN scheduler** solves a mapping schedule per
layer with Gurobi (`src/lays/scheduler/cli.py:99-127`). The **weight-trace generator**
replays the captured spikes against that schedule through each architecture's native
model and writes per-step cycle counts and the weight-address stream
(`src/lays/weight_trace_gen/cli.py:1-6`). The **NoC simulator** turns the schedule and
the cycle counts into NoC/DRAM transactions and a cycle total (`src/lays/nocsim/sim.py:384-393`).
The **cache simulator** runs the weight-address stream through a cache hierarchy over a
grid of configurations (`src/lays/cachesim/cli.py:15-25`). `scripts/pipeline.py` runs the
four and joins their cycle totals (`scripts/pipeline.py:68-79`).

```
src/lays/scheduler/          SNN scheduler            python -m lays.scheduler {solve,enumerate,solve-trace}
src/lays/weight_trace_gen/   weight-trace generator   python -m lays.weight_trace_gen gen
src/lays/nocsim/             NoC simulator            python -m lays.nocsim
src/lays/cachesim/           cache simulator          python -m lays.cachesim {grid,sweep,run}
src/lays/parsers/, src/lays/util.py                   YAML parsers, shared helpers
scripts/                     pipeline.py (end to end)
examples/                    arch/ node_mapspace/ cache/ schedules/ workloads/
examples/cachesim/           WCTS fixtures + to_stream.py
examples/input_trace/loas/   5-sample spike captures: meta.json + one .npy per layer
zoo/demo_l2pf/               L2-prefetch demo campaign: config, driver, committed results
tests/                       pytest suite
```

## Installation

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install -e .
make build
```

`make build` compiles the cache simulator, the NoC event simulator and the loas
replay binary (`Makefile:5-8`). Gurobi is needed only to solve schedules: `solve-trace`,
or the pipeline for a layer `examples/schedules/` lacks (`scripts/pipeline.py:322-325`).
Point `GRB_LICENSE_FILE` at your license file.

## Quick start

`make demo` runs `scripts/pipeline.py` with its defaults (`Makefile:10-11`): loas layers
V8, V9, R9, R16 (`scripts/pipeline.py:47`, `scripts/pipeline.py:453`), samples 0..4 (`scripts/pipeline.py:457-458`),
the 48-config cache grid (`examples/cache/khkw_sweep.json:2-4`), written to
`data/demo/loas/` (`scripts/pipeline.py:312-313`, `src/lays/util.py:23-24`). `make test` runs the tests.

## Reproducing results

Each module alone on R9 (resnet19_T4_n5/layer_09_layer2_0_conv2, sample 0), after `make demo`:
```
OUT=data/demo/loas; mkdir -p $OUT/cachesim
python -m lays.scheduler solve-trace --arch loas --trace-root examples/input_trace/loas --trace-dirs resnet19_T4_n5 --layers layer_09_layer2_0_conv2 --cache-dir $OUT/schedules
python -m lays.weight_trace_gen gen --arch loas --trace-root examples/input_trace/loas --trace-dir resnet19_T4_n5 --layer layer_09_layer2_0_conv2 --schedule-cache examples/schedules --sample-start 0 --sample-count 1 --out-dir $OUT/weight_traces
python -m lays.nocsim --schedule examples/schedules/loas/resnet19_T4_n5/layer_09_layer2_0_conv2.json --layer $OUT/layers/resnet19_T4_n5/layer_09_layer2_0_conv2.yaml --arch examples/arch/loas_inst16_node32kb.yaml --weight-trace $OUT/weight_traces/loas/resnet19_T4_n5/layer_09_layer2_0_conv2/sample_00000.json.gz --out $OUT/nocsim/resnet19_T4_n5/layer_09_layer2_0_conv2_s00000.csv --simulate
python -m lays.cachesim grid --out $OUT/grid && python -m lays.cachesim sweep --config-grid $OUT/grid/khkw_0.json --trace $OUT/streams/resnet19_T4_n5/layer_09_layer2_0_conv2_s00000.wcts --out $OUT/cachesim/R9_s0_khkw_0.csv
```

Inputs, outputs and the full pipeline: `docs/REPRODUCE.md`. The code: `docs/atlas/README.md`.
