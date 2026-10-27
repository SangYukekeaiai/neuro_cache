#!/usr/bin/env python3
"""Per-layer wcache profiling over every layer of a benchmark, one layer per
Slurm array task (scripts/slurm/profile_all_layers.slurm).

A task is one (trace_dir, layer): every trace dir under --trace-root that has a
meta.json, in sorted order, and every valid layer of it in meta.json order. A
task takes the tracked schedule (or solves one into <out>/schedules when
gurobipy imports), generates the version-2 WCTS stream of each of samples
0..N-1, runs cachesim_sweep over the config grid on it, deletes the stream, and
writes <out>/layers/<trace_dir>/<layer>.csv. --merge joins the per-layer CSVs
in task order into <out>/all_layers.csv.

The default grid is the 0823 stage 4 khkw grid (run_khkw_sweep.grid_for).
--grid takes a JSON array of wcache configs instead.

  python scripts/profile_all_layers.py --bench loas --dry-run     one line per task
  python scripts/profile_all_layers.py --count                    number of tasks
  python scripts/profile_all_layers.py --task-index I [--dry-run] run (or print) task I
  python scripts/profile_all_layers.py --layer vgg16_T4_n5/layer_08_features_27   the same, by name
  python scripts/profile_all_layers.py --merge
"""
import argparse
import concurrent.futures as cf
import csv
import json
import os
import pathlib
import shlex
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import wcache_baseline as wb  # noqa: E402  (puts profiling/ and stage4 on sys.path)
from wcache_baseline import sweep  # noqa: E402
from demo import DEFAULT_JOBS, load_grid  # noqa: E402
from subset_input_traces import DEFAULT_SRC as FULL_CAPTURE  # noqa: E402
from weight_trace_gen.trace import valid_layer_names  # noqa: E402
from util import data_root  # noqa: E402


def tasks(trace_root):
    """[(trace_dir, layer)]: the array task index is the list index."""
    out = []
    for meta in sorted(pathlib.Path(trace_root).glob("*/meta.json")):
        out += [(meta.parent.name, l) for l in valid_layer_names(json.loads(meta.read_text()))]
    return out


def grid_groups(grid_name, grid):
    """[(config names, points)] per cin_block: cachesim_sweep gives one mapper to a
    whole grid, so points that differ in cin_block go to separate invocations."""
    groups = {}
    for i, p in enumerate(grid):
        names, points = groups.setdefault(p.get("cin_block"), ([], []))
        names.append(f"{grid_name}_{i:02d}")
        points.append(p)
    return list(groups.values())


def schedule_root(bench, trace_dir, layer, out):
    """(schedule cache root, whether the layer's schedule is already in it)."""
    if (wb.SCHEDULES / bench / trace_dir / f"{layer}.json").is_file():
        return wb.SCHEDULES, True
    cache = out / "schedules"
    return cache, (cache / bench / trace_dir / f"{layer}.json").is_file()


def solve_schedule(bench, trace_root, trace_dir, layer, cache):
    try:
        import gurobipy  # noqa: F401
    except ImportError:
        sys.exit(f"no schedule for {trace_dir}/{layer} under {wb.SCHEDULES} or {cache}, "
                 "and gurobipy does not import, so it cannot be solved")
    import solve_schedules as ss
    from snn_scheduler.artifact import solve_and_cache_schedule
    meta = json.loads((trace_root / trace_dir / "meta.json").read_text())
    solve_and_cache_schedule(bench, ss.DEFAULT_ARCH_YAML[bench], ss.DEFAULT_DATAFLOW_YAML[bench],
                             trace_dir, layer, meta, cache)


def sample_commands(a, sched, trace_dir, layer, s, stream, grid_files):
    """The stream generation command, then one cachesim_sweep command per grid file."""
    gen = [sys.executable, str(ROOT / "scripts/generate_weight_traces.py"), "--arch", a.bench,
           "--trace-root", str(a.trace_root), "--schedule-cache", str(sched), "--workers", "1",
           "--trace-dir", trace_dir, "--layer", layer, "--stream", "--sample-start", str(s),
           "--sample-count", "1", "--dump-trace", str(stream)]
    return [gen] + [[str(sweep.BIN), "--config-grid", str(g), "--trace", str(stream), "--arm", "cache",
                     "--tier", a.grid_name, "--run-id", f"profile-{layer}-s{s}-{g.stem}", "--header"]
                    for g in grid_files]


def run(cmd, capture=False):
    r = subprocess.run(cmd, cwd=ROOT, text=True, stderr=subprocess.PIPE,
                       stdout=subprocess.PIPE if capture else subprocess.DEVNULL)
    if r.returncode != 0:
        sys.exit(f"command failed (rc {r.returncode}): {shlex.join(cmd)}\n{r.stderr[-3000:]}")
    return r.stdout


def layer_csv(out, trace_dir, layer):
    return out / "layers" / trace_dir / f"{layer}.csv"


def run_task(a, i, all_tasks):
    if not 0 <= i < len(all_tasks):
        sys.exit(f"task index {i} out of range: {a.trace_root} has {len(all_tasks)} layers")
    d, l = all_tasks[i]
    have = json.loads((a.trace_root / d / "meta.json").read_text())["layers"][l][1]
    if a.n_samples > have:
        sys.exit(f"{d}/{l} has {have} samples, asked for {a.n_samples} samples")
    sched, solved = schedule_root(a.bench, d, l, a.out)
    groups = grid_groups(a.grid_name, a.grid)
    # Per layer, so array tasks never write a file another task is reading.
    grid_files = [a.out / "grid" / d / l / f"{a.grid_name}_{k}.json" for k in range(len(groups))]
    streams = a.out / "streams" / d
    work = [(s, sample_commands(a, sched, d, l, s, streams / f"{l}_s{s:05d}.wcts", grid_files))
            for s in range(a.n_samples)]
    dest = layer_csv(a.out, d, l)
    if a.dry_run:
        print(f"# task {i}: {d}/{l}, schedule {'in ' + str(sched) if solved else 'to solve into ' + str(sched)}")
        for _, cmds in work:
            print("\n".join(shlex.join(c) for c in cmds))
        print(f"# rows -> {dest}")
        return 0
    if not solved:
        solve_schedule(a.bench, a.trace_root, d, l, sched)
    for g, (_, points) in zip(grid_files, groups):
        g.parent.mkdir(parents=True, exist_ok=True)
        g.write_text(json.dumps(points, indent=1))
    streams.mkdir(parents=True, exist_ok=True)

    def one(item):
        s, (gen, *sweeps) = item
        run(gen)
        rows = []
        for (names, _), cmd in zip(groups, sweeps):
            got = list(csv.reader(run(cmd, capture=True).splitlines()))
            if len(got) - 1 != len(names):
                sys.exit(f"cachesim_sweep gave {len(got) - 1} rows for {len(names)} configs ({d}/{l} s{s})")
            rows += [(name, got[0], r) for name, r in zip(names, got[1:])]
        pathlib.Path(gen[-1]).unlink()
        return sorted(rows, key=lambda r: int(r[0].rsplit("_", 1)[1]))

    # Rows in sample order (pool.map keeps it), then grid order within a sample.
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as pool:
        rows = [r for got in pool.map(one, work) for r in got]
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["config"] + rows[0][1])
        w.writerows([name] + r for name, _, r in rows)
    os.replace(tmp, dest)
    print(f"task {i}: {len(rows)} rows -> {dest}")
    return 0


def merge(out, all_tasks):
    """Write <out>/all_layers.csv from the per-layer CSVs that exist; 1 if any is missing."""
    header, rows, missing = None, [], []
    for d, l in all_tasks:
        p = layer_csv(out, d, l)
        if not p.is_file():
            missing.append(f"{d}/{l}")
            continue
        with open(p, newline="") as f:
            got = list(csv.reader(f))
        if header is not None and got[0] != header:
            sys.exit(f"{p}: header differs from the first layer CSV's")
        header = got[0]
        rows += got[1:]
    dest = out / "all_layers.csv"
    if header is not None:
        with open(dest, "w", newline="") as f:
            csv.writer(f).writerows([header] + rows)
    print(f"merged {len(all_tasks) - len(missing)} of {len(all_tasks)} layers, {len(rows)} rows -> {dest}")
    if missing:
        print("missing layer CSVs: " + ", ".join(missing))
    return 1 if missing else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--bench", default="loas")
    p.add_argument("--n-samples", type=int, default=500, help="samples 0..N-1 of each layer")
    p.add_argument("--grid", help="JSON array of wcache configs (default: the 0823 khkw grid)")
    p.add_argument("--trace-root", type=pathlib.Path, default=FULL_CAPTURE,
                   help="input traces, one dir per capture with meta.json (default: the full "
                        "capture, %(default)s; the 5-sample subset is input_trace/loas)")
    p.add_argument("--out", type=pathlib.Path, help="default $NEURO_CACHE_DATA/profiling/<bench>")
    p.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                   help="samples run in parallel (default %(default)s; each can use several GB)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--task-index", type=int, help="run one array task (one layer)")
    mode.add_argument("--layer", metavar="TRACE_DIR/LAYER", help="run the task of this layer")
    mode.add_argument("--merge", action="store_true", help="join the per-layer CSVs")
    mode.add_argument("--count", action="store_true", help="print the number of tasks")
    p.add_argument("--dry-run", action="store_true", help="print commands instead of running them")
    a = p.parse_args(argv)
    for name in ("n_samples", "jobs"):
        if getattr(a, name) < 1:
            p.error(f"--{name.replace('_', '-')} must be at least 1")
    a.out = (a.out or data_root() / "profiling" / a.bench).resolve()
    grid_path = a.grid and str(pathlib.Path(a.grid).resolve())
    a.grid_name, a.grid = load_grid(grid_path)
    a.trace_root = a.trace_root.resolve()
    all_tasks = tasks(a.trace_root)
    if not all_tasks:
        sys.exit(f"no meta.json with a valid layer under {a.trace_root}/*/")
    if a.count:
        print(len(all_tasks))
        return 0
    if a.merge:
        return merge(a.out, all_tasks)
    if a.layer is not None:
        if tuple(a.layer.split("/", 1)) not in all_tasks:
            sys.exit(f"unknown layer {a.layer!r}: give trace_dir/layer, one of "
                     + ", ".join(f"{d}/{l}" for d, l in all_tasks))
        a.task_index = all_tasks.index(tuple(a.layer.split("/", 1)))
    if a.task_index is not None:
        return run_task(a, a.task_index, all_tasks)
    if not a.dry_run:
        p.error("give --task-index, --layer, --merge, --count or --dry-run")
    base = [sys.executable, str(pathlib.Path(__file__).resolve()), "--bench", a.bench,
            "--n-samples", str(a.n_samples), "--trace-root", str(a.trace_root), "--out", str(a.out)]
    base += ["--grid", grid_path] if grid_path else []
    for i, (d, l) in enumerate(all_tasks):
        print(f"task {i} {d}/{l}: {shlex.join(base + ['--task-index', str(i)])}")
    print(f"{len(all_tasks)} tasks: sbatch --array=0-{len(all_tasks) - 1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
