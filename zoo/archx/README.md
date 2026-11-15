# Archx

An event-based cost-modeling framework for computer-system design-space exploration, built around the **A-Graph** abstraction.

## Overview

Archx represents a system by:
1. building a directed acyclic graph (A-Graph) of **events** and hardware **modules** connected by **subevent** edges,
2. populating each hardware module with costs, queried from a pluggable hardware **interface**.
3. running user-supplied Python **performance models** that set per-edge event counts, and
4. metric aggregation to report results of the resulting application on the target architecture.

Archx models across the system stack, separating into four levels. Each level is described by one of the four inputs to a run, detailed under [Configuration](#configuration).

| level | what it describes | input |
|---|---|---|
| **Application** | a workload (LLM, signal processing, error correction, ...), defined with parameters to sweep through multiple configurations | workload (`-w`) |
| **Software** | an event graph decomposing the application into architecture events, each with an isolated Python performance model that translates the workload configuration into per-subevent call counts | event (`-e`) |
| **Architecture** | the micro-architecture blocks that build the overall architecture, at any granularity | architecture (`-a`) |
| **Circuit** | the physical costs of each module: area, power, energy, cycle count, runtime, or any user-defined quantity, supplied per module by a hardware interface | metric (`-m`) |

For the package layout, the seven pipeline stages, and how caching works, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Requirements

- [Anaconda](https://www.anaconda.com/) to manage the environment.
- The [Rust toolchain](https://rustup.rs/) for a source installation only, to compile the Rust extension via [Maturin](https://www.maturin.rs/). Installing from PyPI needs no Rust.

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"   # add cargo/rustc to PATH in the current shell
rustc --version             # verify
```

## Installation

Both methods provide the `archx` CLI command and the `import archx` Python module.

### Option 1: conda + pip install from PyPI (recommended)

Installs all dependencies via conda and the Archx package from PyPI.

```bash
conda env create -f environment.yaml   # edit `name: archx` to rename
conda activate archx
pip install archx
```

### Option 2: source installation (developer mode)

Editable install from source: live code changes are reflected without reinstalling.

```bash
git clone https://github.com/UnaryLab/archx.git && cd archx
conda env create -f environment.yaml   # edit `name: archx` to rename
conda activate archx
pip install -e . --no-deps             # editable install; Rust extension is compiled here
```

After editing any Rust source under `src/archx/rust-core/`, rerun `pip install -e . --no-deps` to recompile; Python changes are live without reinstalling.

### Validate

```bash
archx -h
python -c "import archx"
```

## Quick start

Run one design and query a metric from the result.

```bash
archx -r <run_dir> \
      -a arch.yaml -m metric.yaml -w workload.yaml -e event.yaml \
      -c <run_dir>/graph.json \
      [-t] [-s] [-d] [-l DEBUG] [-p <dir>]
```

- `-c` is the checkpoint the populated A-Graph is saved to (must end in `.json`).
- `-t` mirrors the log to the terminal (a logfile is always written into the run dir).
- `-s` also dumps the parsed architecture/metric/workload/event dicts as YAML into the run dir.
- `-d` deletes the run dir first if it exists.
- `-p` adds a directory to `sys.path` so performance models can import local helpers.

Load the checkpoint and aggregate any metric at any event:

```python
from archx.event import load_event_graph
from archx.metric import create_metric_dict, aggregate_event_metric

event_graph = load_event_graph('<run_dir>/graph.json')
metric_dict = create_metric_dict('metric.yaml')

result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict,
                                metric='dynamic_energy', workload='gemm', event='gemm')
# -> OrderedDict({'value': ..., 'unit': 'nJ'})
```

`aggregate_tag_metric` aggregates over all modules sharing an architecture `tag`, and `query_module_metric` reads a single module's raw metrics.

For runnable designs with all four inputs written out, see [`examples/README.md`](examples/README.md).

## Reproducing results

### Design-space sweeps

A Python *description file* defining a `description(path)` function, built on `archx.programming` which uses OR-Tools CP-SAT to enumerate valid configurations under constraints, drives batch exploration:

```bash
archx -r <run_dir> -compile description.py        # generate configurations.csv
archx -r <run_dir> -extract configurations.csv    # csv -> runs.txt
archx -r <run_dir> -f configurations.csv          # Tkinter GUI to filter -> runs.txt
archx -r <run_dir> -x runs.txt                    # execute all runs in parallel
```

`-compile ... -full` chains all of the above in one command (add `-ff` to insert the GUI filter step). `-x` fans the runs out across all CPU cores; failing runs are collected in `failed_runs.txt` inside the `-r` run directory. `-x` (and `-compile ... -full`) exits `2` when the batch ran but some runs failed, and `0` when all succeeded.

### Writing a description file

A description file builds the same four inputs as a single run, but programmatically, and declares which parameters to sweep. Any list-valued `instance` or `query` entry, and any workload parameter added with `sweep=True`, becomes a sweep axis; constraints prune invalid combinations before anything is written to disk.

```python
from archx.programming.graph.agraph import AGraph


def description(path):
    agraph = AGraph(path=path)
    architecture = agraph.architecture
    event = agraph.event
    metric = agraph.metric
    workload = agraph.workload

    # Architecture: list values become sweep axes.
    architecture.add_attributes(technology=[45], frequency=400, interface='csv_cmos')
    pe = architecture.add_module(name='pe', instance=[[16, 16], [32, 32], [64, 64]], tag=['onchip', 'compute'], query={'class': 'mac'})
    sram = architecture.add_module(name='sram', instance=[1], tag=['memory'], query={'interface': 'cacti7', 'class': 'sram', 'bank': [32, 64, 128], 'width': 16, 'depth': [512, 1024, 2048]})

    # Events: the A-Graph structure, same as the event YAML.
    event.add_event(name='gemm', subevent=['mac_array', 'sram_rd', 'sram_wr'], performance='performance.py')
    event.add_event(name='mac_array', subevent=['pe'], performance='performance.py')
    event.add_event(name='sram_rd', subevent=['sram'], performance='performance.py')
    event.add_event(name='sram_wr', subevent=['sram'], performance='performance.py')

    # Metrics.
    metric.add_metric(name='area', unit='mm^2', aggregation='module')
    metric.add_metric(name='dynamic_energy', unit='nJ', aggregation='summation')
    metric.add_metric(name='runtime', unit='ms', aggregation='specified')

    # Workloads: sweep=True parameters become sweep axes.
    gemm = workload.add_configuration(name='gemm')
    gemm.add_parameter(parameter_name='m', parameter_value=[256, 512, 1024], sweep=True)
    gemm.add_parameter(parameter_name='k', parameter_value=512)
    gemm.add_parameter(parameter_name='n', parameter_value=512)

    # Constraints prune the cross product of all axes.
    # direct_constraint: the listed parameters sweep together by index
    # (the i-th PE shape only pairs with the i-th bank count).
    agraph.direct_constraint([pe['instance'], sram['query']['bank']])
    # conditional_constraint: keep only combinations whose actual values
    # satisfy an arbitrary condition (here: SRAM capacity capped at 4 Mib).
    agraph.conditional_constraint(a=sram['query']['bank'], b=sram['query']['depth'], condition=lambda bank, depth: bank * depth * 16 <= 2**22)

    agraph.generate()
    return agraph
```

The handles returned by `add_module` index into the swept parameters (`pe['instance']`, `sram['query']['bank']`); passing a list of names (e.g. `name=['isram', 'wsram']`) creates several identically-parameterized modules, indexed as `srams['wsram']['query']['bank']`. `agraph.generate()` solves the constraint model and writes the per-configuration YAML files (`architecture/`, `workload/`, `event/`, `metric/`) plus `configurations.csv` into the run directory; `-extract` then turns the CSV into one `archx` command line per configuration in `runs.txt`.

For a complete real-world description (multi-module arrays, partition and multi-variable conditional constraints), see [`zoo/chiplet4ai/llama/description.py`](zoo/chiplet4ai/llama/description.py).

### Batch runs

```bash
bash src/archx/bin/run_archx.sh runs.txt
```

### Tests

```bash
pytest
```

`tests/test_numerical_equivalence.py` pins the Rust aggregation engine against hand-derived values. Tests touching SRAM run CACTI7, which ships a binary per host as `cacti-<system>-<machine>` and is built from source when the matching one is absent.

## Configuration

A run is described by four YAML files plus one or more Python performance models.

### Architecture (`-a`)

The hardware: a flattened set of named modules. `attribute` holds global defaults (technology, frequency, default interface) that are merged into each module's `query`; the `query` dict is what gets sent to the hardware interface to price the module. Modules can `path:` to other architecture YAML files for hierarchical descriptions, carry `tag:` lists for group queries, and `instance:` lists for arrays of identical units.

```yaml
architecture:
  attribute:
    technology: 45        # nm
    frequency: 400        # MHz
    interface: csv_cmos   # default hardware interface
  module:
    mac_array:
      path: mac_array.architecture.yaml   # include another file
    sram:
      tag: [memory, onchip]
      query:
        interface: cacti7
        class: sram
        bank: 32
        width: 64          # bits
        depth: 1024
```

### Metric (`-m`)

The metrics to compute. Each metric declares a `unit` and an `aggregation` mode:

| mode | meaning | typical metrics |
|---|---|---|
| `module` | sum once over distinct modules | area, leakage power |
| `summation` | sum scaled by per-edge call counts (default) | dynamic energy |
| `specified` | taken directly from a performance-model output | cycle count, runtime |

```yaml
metric:
  area:
    unit: mm^2
    aggregation: module
  dynamic_energy:
    unit: nJ                # aggregation defaults to summation
  runtime:
    unit: ms
    aggregation: specified
```

### Workload (`-w`)

One workload per file: a `name` and a `configuration` dict of knobs the performance models read. A file may instead `path:` to another workload file, which is followed recursively.

```yaml
workload:
  name: llama_3_70b
  configuration:
    batch_size: 32
    dim: 8192
    layers: 80
```

### Event (`-e`)

The A-Graph structure: each event lists its `subevent`s (other events, or leaf hardware modules from the architecture) and the Python file holding its performance model.

```yaml
event:
  gemm:
    subevent: [mac_array, sram_rd, sram_wr]
    performance: performance/example.performance.py
  sram_rd:
    subevent: [sram]
    performance: performance/example.performance.py
```

### Performance models

For each event, a Python function with the same name as the event:

```python
def gemm(architecture_dict, workload_dict=None):
    cfg = workload_dict['configuration']
    macs = cfg['m'] * cfg['k'] * cfg['n']
    return OrderedDict({
        'subevent': OrderedDict({
            'mac_array': OrderedDict({'count': macs / array_size}),
            'sram_rd':   OrderedDict({'count': reads}),
        }),
    })
```

It receives the parsed architecture and workload dicts and returns, per subevent, the call `count` (and optionally an `operation` such as `read`/`write` for multi-operation modules like SRAM). It may also return `specified` metrics directly (e.g. `{'cycle_count': {'value': 1., 'unit': 'cycles'}}`). See `examples/mac_1_cycle/input/performance/example.performance.py` for a complete model.

### Hardware interfaces

Interfaces are the pluggable cost models that price each module, under `src/archx/interface/`:

| interface | costs |
|---|---|
| `cacti7` | SRAM/DRAM area, power, and energy via the CACTI7 memory model (bundled C++ source, one binary per host) |
| `csv_cmos` | logic modules at 45 nm and 7 nm, interpolated from CMOS synthesis and place-and-route CSVs |
| `csv_cmos_32nm` | the same lookup over a 32 nm library |
| `csv_cmos_asplos_2026_ae` | the same lookup over a second 45 nm library |
| `chiplet_cmos` | CMOS CSV costs for chiplet-based designs |
| `csv_sc` | stochastic-computing modules |
| `csv_h200` | measured H200 power and runtime per GPU kernel |
| `csv_riscv` | per-stage RISC-V energy |

A module selects one with the `interface:` key in its `query`, or inherits the architecture's global `attribute`. Register, unregister, or copy an interface with:

```bash
archx -ireg  -iname <name> -idir <dir>   # register a new hardware interface
archx -iureg -iname <name>               # unregister
archx -icopy -iname <name> -idir <dir>   # copy an installed interface out
```

See [`src/archx/interface/README.md`](src/archx/interface/README.md) for the query contract and how to add your own.

<!-- ## Citation

Not yet published. -->

## License

MIT. See [LICENSE](LICENSE).
