#!/usr/bin/env python3
"""Phase D scratchpad-vs-cache driver: one pipeline pair per unit, one atomic
per-unit CSV, resume by result, merge at the end.

A unit of work is one trace read once by one `wcache_sweep` process running
every configuration of one LAYOUT against it in broadcast lockstep. One mapper
serves a whole sweep, so a grid that varies `cin_block`, `cout_block` or
`weight_bytes` is several sweeps, each over its own pass of the stream
(`sweep.cpp:55-61`). The 180-configuration cache grid is therefore three
sweeps of 60, one per line size, not one sweep of 180.

The pipe belongs here rather than to a shell: the producer and the consumer are
both children of this process, so the atomic result cache wraps the whole pair.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXAMPLES = ROOT / "src/wcache/examples"
GENERATOR = ROOT / "scripts/generate_weight_traces.py"
# `make apps` writes build/fixture, `make MODE=release lib apps` build/release.
# Release first: a campaign wants -O2, and a machine that only ever ran
# `make apps` still works.
BUILD_DIRS = ("release", "fixture")
# The layout knobs a mapper is built from, in the order wcache_sweep reports
# them in its layout-mismatch message.
LAYOUT_KEYS = ("cin_block", "cout_block", "weight_bytes")


def sweep_binary() -> pathlib.Path:
    for mode in BUILD_DIRS:
        path = ROOT / "src/wcache/native/build" / mode / "wcache_sweep"
        if path.exists():
            return path
    raise FileNotFoundError(
        f"no wcache_sweep in {' or '.join(BUILD_DIRS)}; run `make apps` in "
        f"{ROOT / 'src/wcache/native'}")


def git_commit() -> str:
    """The binary must not shell out, so the driver fills the column."""
    try:
        done = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        print("run_sweep: no git commit available, the column stays empty", file=sys.stderr)
        return ""
    return done.stdout.strip()


# --- the grid document ----------------------------------------------------
#
# A driver grid is NOT a wcache_sweep grid: it also carries the unit list and
# the expected counts, and wcache_sweep refuses unknown keys. The driver
# expands it and writes each layout group out as a plain array of complete
# configurations, which is the grid form the binary already accepts.

DOC_KEYS = {"comment", "expected_configs", "arm", "base", "axes", "configs",
            "units", "fixtures"}


def load_grid(path: pathlib.Path) -> dict:
    doc = json.loads(path.read_text())
    unknown = set(doc) - DOC_KEYS
    if unknown:
        raise ValueError(f"{path}: unknown key(s) {sorted(unknown)}")
    if ("units" in doc) == ("fixtures" in doc):
        raise ValueError(f"{path}: give exactly one of `units` and `fixtures`")
    if ("axes" in doc) == ("configs" in doc):
        raise ValueError(f"{path}: give exactly one of `axes` and `configs`")
    return doc


def cross(axes: dict) -> list[dict]:
    """The cross product of the axes, first axis varying slowest, which is
    wcache_sweep's own order (`wcache_sweep --help`). An axis value is either a
    scalar for its own key or an object merged whole, which is how knobs that
    must move together are declared: `prefetch_policy` and `prefetch_distance`
    are one axis, because next_burst at distance 0 is refused (config.cpp:504).
    """
    names = list(axes)
    points = []
    for values in itertools.product(*(axes[name] for name in names)):
        point = {}
        for name, value in zip(names, values):
            point.update(value if isinstance(value, dict) else {name: value})
        points.append(point)
    return points


def expand_configs(doc: dict) -> list[dict]:
    base = doc.get("base", {})
    overrides = doc["configs"] if "configs" in doc else cross(doc["axes"])
    configs = [dict(base, **override) for override in overrides]
    expected = doc.get("expected_configs")
    if expected is not None and len(configs) != expected:
        raise ValueError(f"grid expands to {len(configs)} configurations, "
                         f"but `expected_configs` says {expected}")
    return configs


def layout_of(config: dict) -> tuple:
    # The defaults are RunConfig's own (config.h:28-30); a grid that omits a
    # layout knob is one layout, not none.
    defaults = {"cin_block": 1, "cout_block": 16, "weight_bytes": 1}
    return tuple(config.get(key, defaults[key]) for key in LAYOUT_KEYS)


def layout_groups(configs: list[dict]) -> list[tuple[tuple, list[dict]]]:
    groups: dict[tuple, list[dict]] = {}
    for config in configs:
        groups.setdefault(layout_of(config), []).append(config)
    return sorted(groups.items())


def layout_tag(layout: tuple) -> str:
    cin, cout, weight_bytes = layout
    return f"cin{cin}_cout{cout}_wb{weight_bytes}"


# --- units ----------------------------------------------------------------
#
# A trace unit is either a checked-in examples/ slice (local demo and smoke
# runs) or one (arch, trace_dir, layer, sample) the generator streams. Stream
# mode materializes nothing, so resume tests the RESULT, never the input.

def expand_traces(doc: dict) -> list[dict]:
    if "fixtures" in doc:
        return [{"kind": "fixture", "key": name, "fixture": name}
                for name in doc["fixtures"]]
    traces = []
    for unit in cross(doc["units"]):
        # A value the campaign has not pinned yet (§11 Q3, the deep-layer picks)
        # is spelled CONFIRM_<what> so it still counts as a unit and still gets a
        # distinct key, but cannot silently run under a guessed name.
        unconfirmed = [key for key, value in unit.items()
                       if isinstance(value, str) and value.startswith("CONFIRM")]
        parts = [unit["arch"], unit["trace_dir"], unit["layer"]]
        if "n_cores" in unit:
            parts.append(f"c{unit['n_cores']}")
        parts.append(f"s{unit['sample']:05d}")
        traces.append({"kind": "stream", "unit": unit, "unconfirmed": unconfirmed,
                       "key": "__".join(str(part) for part in parts)})
    return traces


def build_tasks(doc: dict, results_dir: pathlib.Path, tier: str,
                trace_root: pathlib.Path | None) -> list[dict]:
    groups = layout_groups(expand_configs(doc))
    tasks = []
    for trace in expand_traces(doc):
        for layout, configs in groups:
            key = f"{trace['key']}__{layout_tag(layout)}"
            tasks.append({
                **trace, "configs": configs, "unit_key": key,
                "arm": doc.get("arm", "cache"), "tier": tier,
                "trace_root": str(trace_root) if trace_root else None,
                "out_path": str(results_dir / tier / f"{key}.csv"),
            })
    return tasks


def producer_argv(task: dict) -> list[str]:
    if task["kind"] == "fixture":
        # This file, re-entered: the fixture path then has the same shape as
        # the campaign path, one producer process piped into one consumer.
        return [sys.executable, str(pathlib.Path(__file__).resolve()),
                "--emit-fixture-stream", task["fixture"]]
    unit = task["unit"]
    argv = [sys.executable, str(GENERATOR), "--stream",
            "--arch", unit["arch"], "--trace-dir", unit["trace_dir"],
            "--layer", unit["layer"],
            "--sample-start", str(unit["sample"]), "--sample-count", "1",
            # --stream is serial by construction: N producers cannot share one
            # stdout pipe, so parallelism is N pipeline PAIRS, never N workers.
            "--workers", "1"]
    if task["trace_root"]:
        argv += ["--trace-root", task["trace_root"]]
    if unit.get("schedule_cache"):
        argv += ["--schedule-cache", unit["schedule_cache"]]
    return argv


def emit_fixture_stream(name: str) -> None:
    """One examples/ slice as a WCTS stream on stdout, as tests/sweep_cli.sh
    writes it. tracegen's stream writers need only `struct`; the module's
    top-level archmodels.trace import drags in numpy, which the wire format has
    no part in, so it is stubbed."""
    import types
    sys.path.insert(0, str(ROOT / "src"))
    stub = types.ModuleType("archmodels.trace")
    stub.build_workload_from_trace = None
    sys.modules.setdefault("archmodels.trace", stub)
    from tracegen import (CoreEntry, LayerWeightTrace, TickEntry, TileWeightTrace,
                          stream_weight_trace)

    doc = json.loads((EXAMPLES / f"{name}.json").read_text())
    n_cores = json.loads((EXAMPLES / "manifest.json").read_text())["slice"]["n_cores"]
    tiles = [TileWeightTrace(
        dram_i=t["dram_i"], noc_i=t["noc_i"], mac_cycles=t["mac_cycles"],
        lif_cycles=t.get("lif_cycles"),
        ticks=[TickEntry(tick=k["tick"],
                         cores=[CoreEntry(core_id=c["core_id"],
                                          weight_addresses=c["weight_addresses"])
                                for c in k["cores"]])
               for k in t["ticks"]]) for t in doc["tiles"]]
    trace = LayerWeightTrace(
        arch=doc["arch"], trace_dir=doc["trace_dir"], layer_name=doc["layer_name"],
        sample_idx=doc["sample_idx"], workload_dims=doc["workload_dims"],
        dram_num_steps=doc["dram_num_steps"], noc_num_steps=doc["noc_num_steps"],
        tiles=tiles)
    # Dim 3 is the one spatial factor every checked-in slice unrolls over,
    # matching tests/sweep_cli.sh.
    stream_weight_trace(trace, sys.stdout.buffer, n_cores=n_cores,
                        spatial_factors={3: n_cores})


# --- one unit -------------------------------------------------------------

def run_unit(task: dict) -> str:
    out_path = pathlib.Path(task["out_path"])
    if out_path.exists():
        return f"skip (cached): {task['unit_key']}"
    if task.get("unconfirmed"):
        raise ValueError(f"{task['unit_key']}: unit field(s) {task['unconfirmed']} are "
                         f"still CONFIRM placeholders (campaign question Q3)")

    tmp = out_path.with_name(f".{out_path.name}.{os.getpid()}.tmp")
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory() as scratch:
            grid_path = pathlib.Path(scratch) / "grid.json"
            grid_path.write_text(json.dumps(task["configs"]))
            consumer = [str(sweep_binary()), "--config-grid", str(grid_path),
                        "--trace", "-", "--out", str(tmp),
                        "--arm", task["arm"], "--tier", task["tier"],
                        "--git-commit", task["git_commit"]]
            producer = subprocess.Popen(producer_argv(task), stdout=subprocess.PIPE)
            try:
                sweep = subprocess.Popen(consumer, stdin=producer.stdout)
            finally:
                producer.stdout.close()  # the sweep owns the read end now
            sweep_code = sweep.wait()
            producer.wait()
            if producer.returncode != 0:
                raise RuntimeError(f"{task['unit_key']}: the producer exited "
                                   f"{producer.returncode}")
            if sweep_code != 0:
                raise RuntimeError(f"{task['unit_key']}: wcache_sweep exited {sweep_code}")

        with tmp.open(newline="") as handle:
            n_rows = sum(1 for _ in csv.DictReader(handle))
        if n_rows != len(task["configs"]):
            raise RuntimeError(f"{task['unit_key']}: {n_rows} rows for "
                               f"{len(task['configs'])} configurations")
        os.replace(tmp, out_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return (f"done: {task['unit_key']} ({len(task['configs'])} configs, "
            f"{time.monotonic() - started:.1f}s)")


# --- merge ----------------------------------------------------------------

def merge_results(results_dir: pathlib.Path, out_path: pathlib.Path,
                  tier: str | None) -> int:
    subdirs = [results_dir / tier] if tier else sorted(
        path for path in results_dir.iterdir() if path.is_dir())
    paths = [path for subdir in subdirs for path in sorted(subdir.glob("*.csv"))]
    if not paths:
        raise ValueError(f"no unit CSVs under {results_dir}")

    # The header comes from the unit files themselves, so the driver never
    # holds a column list of its own and cannot drift from the binary's schema.
    header: list[str] | None = None
    rows: list[list[str]] = []
    for path in paths:
        with path.open(newline="") as handle:
            unit = list(csv.reader(handle))
        if not unit or len(unit) < 2:
            raise ValueError(f"{path}: no data rows")
        if header is None:
            header = unit[0]
        elif unit[0] != header:
            raise ValueError(f"{path}: CSV header differs from {paths[0]}")
        rows.extend(unit[1:])

    tmp = out_path.with_name(f".{out_path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        os.replace(tmp, out_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    print(f"merged {len(paths)} unit file(s), {len(header)} columns")
    return len(rows)


# --- CLI ------------------------------------------------------------------

def print_preview(doc: dict, tasks: list[dict], grid_path: pathlib.Path,
                  results_dir: pathlib.Path, out_path: pathlib.Path) -> None:
    groups = layout_groups(expand_configs(doc))
    n_traces = len(expand_traces(doc))
    print(f"grid: {grid_path}")
    if doc.get("comment"):
        print(f"  {doc['comment']}")
    print(f"configurations: {sum(len(c) for _, c in groups)} in "
          f"{len(groups)} layout group(s); one group is one pass of the stream")
    for layout, configs in groups:
        cin, cout, weight_bytes = layout
        print(f"  {layout_tag(layout)}: {len(configs)} configs, "
              f"line {cin * cout * weight_bytes} B")
    print(f"units: {n_traces} trace(s) x {len(groups)} layout group(s) = {len(tasks)} units")
    print(f"rows: {sum(len(task['configs']) for task in tasks)}")
    print(f"arm: {doc.get('arm', 'cache')}")
    print(f"unit results: {results_dir}")
    print(f"merged results: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true",
                        help="execute the sweep; without this flag, print the preview only")
    parser.add_argument("--workers", type=int, default=1,
                        help="parallel pipeline pairs, not parallel producers (default: 1)")
    parser.add_argument("--unit-index", type=int, default=None,
                        help="run one deterministic unit index, for a Slurm array")
    parser.add_argument("--merge-only", action="store_true",
                        help="validate and merge the cached unit results, run nothing")
    parser.add_argument("--dry-run-units", action="store_true",
                        help="print the unit keys, one per line, and exit")
    parser.add_argument("--grid", type=pathlib.Path,
                        help="the tier definition; required unless --merge-only")
    parser.add_argument("--tier", help="the `tier` column and the results subdirectory "
                                       "(default: the grid file's stem)")
    parser.add_argument("--trace-root", type=pathlib.Path, default=None,
                        help="passed to the generator; without it the generator's "
                             "own default trace root applies")
    parser.add_argument("--results-dir", type=pathlib.Path, default=HERE / "results")
    parser.add_argument("--out", type=pathlib.Path, default=HERE / "spad_vs_cache.csv")
    parser.add_argument("--emit-fixture-stream", metavar="NAME",
                        help="internal: write one examples/ slice to stdout as a WCTS "
                             "stream, which is how a fixture unit gets its producer")
    args = parser.parse_args()

    if args.emit_fixture_stream:
        emit_fixture_stream(args.emit_fixture_stream)
        return
    if args.workers <= 0:
        parser.error("--workers must be positive")
    if args.merge_only:
        n_rows = merge_results(args.results_dir, args.out, args.tier)
        print(f"merged and validated {n_rows:,} rows -> {args.out}")
        return
    if args.grid is None:
        parser.error("--grid is required unless --merge-only")

    doc = load_grid(args.grid)
    tier = args.tier or args.grid.stem
    tasks = build_tasks(doc, args.results_dir, tier, args.trace_root)

    if args.dry_run_units:
        for task in tasks:
            print(task["unit_key"])
        return
    if args.unit_index is not None and not 0 <= args.unit_index < len(tasks):
        parser.error(f"--unit-index must be between 0 and {len(tasks) - 1}")

    print_preview(doc, tasks, args.grid, args.results_dir, args.out)
    if not args.run:
        return

    (args.results_dir / tier).mkdir(parents=True, exist_ok=True)
    commit = git_commit()
    for task in tasks:
        task["git_commit"] = commit

    if args.unit_index is not None:
        print(run_unit(tasks[args.unit_index]), flush=True)
        return

    pending = [task for task in tasks if not pathlib.Path(task["out_path"]).exists()]
    # Largest last, so the long units are not the ones a pool waits on at the end.
    pending.sort(key=lambda task: len(task["configs"]))
    print(f"running {len(pending)} not-yet-cached unit(s) with {args.workers} worker(s)",
          flush=True)
    failures = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_unit, task): task for task in pending}
        for future in as_completed(futures):
            task = futures[future]
            try:
                print(future.result(), flush=True)
            except BaseException as error:
                failures.append(error)
                print(f"FAILED: {task['unit_key']}: {error}", flush=True)
    if failures:
        raise RuntimeError(f"{len(failures)} unit(s) failed; rerun to resume")

    n_rows = merge_results(args.results_dir, args.out, tier)
    print(f"merged and validated {n_rows:,} rows -> {args.out}")


if __name__ == "__main__":
    main()
