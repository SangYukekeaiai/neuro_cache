#!/usr/bin/env python3
"""One-command demo: nocsim and wcache on the same layers and samples of one
benchmark, joined into one table.

Steps: check the inputs under input_trace/<bench>/; take the tracked schedules
(or solve them when gurobipy imports); build the native tools; generate the
nocsim weight traces and the version-2 WCTS streams; run nocsim
(`python -m nocsim.sim --simulate`) and cachesim_sweep over a config grid; write
<out>/results.csv (one row per layer, sample and config) and <out>/summary.md
(geomean speedup per config, and every command run).

The default grid is the 0823 stage 4 khkw grid (run_khkw_sweep.grid_for).
--grid takes a JSON array of wcache configs instead.

  python scripts/demo.py [--bench loas] [--layers V8 R9 ...] [--jobs N]
  python scripts/demo.py --verify-baseline [DIR]   check <out>/results.csv
                                                   against DIR (.baseline/after)
  python scripts/demo.py --check-bench BENCH       check input_trace/BENCH (or a
                                                   directory) against the input
                                                   contract in docs/REPRODUCE.md
"""
import argparse
import concurrent.futures as cf
import csv
import json
import math
import os
import pathlib
import shutil
import subprocess
import sys
import time

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "profiling/0823_stagewise_verify/stage3_nocsim")]
import wcache_baseline as wb  # noqa: E402  (puts profiling/ and stage4 on sys.path)
from wcache_baseline import sweep  # noqa: E402
import run_stage3  # noqa: E402
from weight_trace_gen import ARCH_NATIVE_BRIDGES  # noqa: E402
from weight_trace_gen.trace import exclusion_reason, layer_params, valid_layer_names  # noqa: E402
from snn_scheduler.artifact import check_schedule_matches_trace  # noqa: E402
from common import INPUT_TRACE, tags  # noqa: E402
from util import data_root  # noqa: E402

# The nocsim arch each benchmark is simulated on; only loas has one in the repo.
NOCSIM_ARCH = {"loas": run_stage3.ARCH_YAML}
# Config columns of the wcache output copied into results.csv.
KEY_FIELDS = ("layout", "line_size_bytes", "l2_size_bytes", "l2_banks",
              "prefetch_policy", "prefetch_distance")
ENV = {**os.environ, "PYTHONPATH": os.pathsep.join(
    p for p in (str(ROOT / "src"), os.environ.get("PYTHONPATH")) if p)}
# Commands run in parallel can each hold several GB (in make demo the largest
# single command peaked at 14 GB RSS), so the default stays below the core count.
DEFAULT_JOBS = min(8, os.cpu_count() or 1)


def speedup(nocsim_cycles, wcache_cycles):
    return nocsim_cycles / wcache_cycles


def geomean(xs):
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def join_results(nocsim, wcache_rows):
    """One results row per wcache row; `nocsim` maps (trace_dir, layer, sample)
    to total_cycles, and a wcache row without a nocsim run is a KeyError."""
    out = []
    for w in wcache_rows:
        r = {k: v for k, v in w.items() if k != "total_cycles"}
        n = nocsim[(w["trace_dir"], w["layer"], w["sample"])]
        r["nocsim_total_cycles"] = n
        r["wcache_total_cycles"] = int(w["total_cycles"])
        r["speedup_vs_nocsim"] = speedup(n, r["wcache_total_cycles"])
        out.append(r)
    return out


def summarize(rows):
    """[(config, geomean speedup, row count)] in first-seen config order."""
    by = {}
    for r in rows:
        by.setdefault(r["config"], []).append(r["speedup_vs_nocsim"])
    return [(c, geomean(xs), len(xs)) for c, xs in by.items()]


def run(cmd, capture=False):
    r = subprocess.run(cmd, cwd=ROOT, env=ENV, text=True,
                       stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                       stderr=subprocess.PIPE)
    if r.returncode != 0:
        sys.exit(f"command failed (rc {r.returncode}): {cmd}\n{r.stderr[-3000:]}")
    return r.stdout


def run_all(cmds, record, jobs, capture=False):
    record.extend(cmds)
    with cf.ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(lambda c: run(c, capture), cmds))


def resolve_layers(bench, specs):
    """(trace_dir, layer) for each spec: `trace_dir/layer`, or a tag such as V8
    of a workload under input_trace/<bench>/."""
    known = None
    out = []
    for s in specs:
        if "/" in s:
            out.append(tuple(s.split("/", 1)))
            continue
        if known is None:
            known = {t: (d, l) for t, d, l in tags(bench)}
        if s not in known:
            sys.exit(f"unknown layer {s!r} for bench {bench!r}: give trace_dir/layer "
                     f"or one of {sorted(known)}")
        out.append(known[s])
    return out


def check_inputs(bench, layers, samples):
    """Problems with the inputs for (bench, layers, samples); empty when all are present."""
    root = INPUT_TRACE / bench
    if not root.is_dir():
        return [f"no input traces: {root} does not exist"]
    problems = []
    if bench not in NOCSIM_ARCH:
        problems.append(f"no nocsim arch for bench {bench!r} (known: {sorted(NOCSIM_ARCH)})")
    for d, layer in layers:
        meta = root / d / "meta.json"
        if not meta.is_file():
            problems.append(f"missing {meta}")
            continue
        m = json.loads(meta.read_text())
        if layer not in m["layers"]:
            problems.append(f"{layer} is not a valid layer in {meta}")
            continue
        try:
            reason = exclusion_reason(m, layer)
        except ValueError as e:
            problems.append(f"{meta}: {e}")
            continue
        if reason is not None:
            problems.append(f"{d}/{layer} is excluded: {reason}")
        elif not (root / d / f"{layer}.npy").is_file():
            problems.append(f"missing {root / d / f'{layer}.npy'}")
        elif samples[-1] >= m["layers"][layer][1]:
            problems.append(f"samples {samples[0]}..{samples[-1]} out of range: {d}/{layer} "
                            f"has {m['layers'][layer][1]} samples")
    return problems


def check_bench(spec):
    """(problems, notes) for a benchmark directory against the input-trace
    contract (docs/REPRODUCE.md): `spec` is a name under input_trace/ or a
    directory path. Empty problems means every trace dir, meta.json and .npy
    is complete and the code knows the benchmark."""
    import numpy as np
    root = pathlib.Path(spec) if os.sep in spec or pathlib.Path(spec).is_dir() else INPUT_TRACE / spec
    bench = root.name
    problems, notes = [], []
    for what, path in (("arch config", ROOT / "configs/arch" / f"{bench}.yaml"),
                       ("dataflow config", ROOT / "configs/node_mapspace" / f"{bench}.yaml"),
                       ("native model", ROOT / "src/weight_trace_gen" / bench / "Makefile")):
        if not path.is_file():
            problems.append(f"no {what} for bench {bench!r}: missing {path.relative_to(ROOT)}")
    if bench not in ARCH_NATIVE_BRIDGES:
        problems.append(f"bench {bench!r} is not in weight_trace_gen.ARCH_NATIVE_BRIDGES "
                        f"(known: {sorted(ARCH_NATIVE_BRIDGES)})")
    if bench not in NOCSIM_ARCH:
        problems.append(f"no nocsim arch for bench {bench!r} in demo.NOCSIM_ARCH (known: {sorted(NOCSIM_ARCH)})")
    if not root.is_dir():
        return problems + [f"no input traces: {root} does not exist"], notes
    metas = sorted(root.glob("*/meta.json"))
    if not metas:
        return problems + [f"no trace dirs: {root} has no <trace_dir>/meta.json"], notes
    for meta_path in metas:
        d = meta_path.parent
        try:
            m = json.loads(meta_path.read_text())
        except ValueError as e:
            problems.append(f"{meta_path}: not JSON ({e})")
            continue
        layers = m.get("layers")
        if not isinstance(layers, dict) or not layers:
            problems.append(f"{meta_path}: no 'layers' dict (layer name -> [T, B, Cin, Hin, Win])")
            continue
        if m.get("dtype", "uint8") != "uint8":
            problems.append(f"{meta_path}: dtype {m['dtype']!r}, the loaders take uint8")
        shapes = {}
        for name, shape in layers.items():
            if not (isinstance(shape, list) and len(shape) == 5
                    and all(isinstance(x, int) and x > 0 for x in shape)):
                problems.append(f"{meta_path}: layer {name}: {shape!r} is not [T, B, Cin, Hin, Win]")
                continue
            shapes[name] = shape
            npy = d / f"{name}.npy"
            if not npy.is_file():
                problems.append(f"missing {npy}")
                continue
            arr = np.load(npy, mmap_mode="r")
            if arr.dtype != np.uint8:
                problems.append(f"{npy}: dtype {arr.dtype}, want uint8")
            if list(arr.shape) != shape:
                problems.append(f"{npy}: shape {tuple(arr.shape)}, meta.json says {tuple(shape)}")
        if len({s[1] for s in shapes.values()}) > 1:
            problems.append(f"{meta_path}: layers disagree on B (the sample count): "
                            + ", ".join(f"{n}={s[1]}" for n, s in shapes.items()))
        if "n_samples" not in m:
            problems.append(f"{meta_path}: no 'n_samples' (scripts/subset_input_traces.py reads it)")
        elif shapes and m["n_samples"] not in {s[1] for s in shapes.values()}:
            problems.append(f"{meta_path}: n_samples {m['n_samples']} differs from the layers' B")
        checked = {"layers": shapes, "layer_params": m.get("layer_params", {})}
        for name in list(shapes):
            try:
                layer_params(checked, name)
            except ValueError as e:
                problems.append(f"{meta_path}: {e}")
                del shapes[name]
        valid = valid_layer_names(checked)
        tracked = [l for l in valid if (wb.SCHEDULES / bench / d.name / f"{l}.json").is_file()]
        stale = []
        for l in tracked:
            try:
                check_schedule_matches_trace(wb.SCHEDULES / bench / d.name / f"{l}.json", d, l)
            except ValueError as e:
                stale.append(f"  {e}")
        notes.append(f"{root.name}/{d.name}: {len(layers)} layers, {len(valid)} usable, "
                     f"{len(tracked)} with a tracked schedule, {len(stale)} stale")
        notes += stale
        notes += [f"  excluded {n}: {exclusion_reason(checked, n)}" for n in shapes if n not in valid]
    return problems, notes


def missing_schedules(root, bench, layers):
    return [root / bench / d / f"{l}.json" for d, l in layers
            if not (root / bench / d / f"{l}.json").is_file()]


def can_solve():
    try:
        import gurobipy  # noqa: F401
    except ImportError:
        return False
    return True


def schedules_for(bench, layers, out, record):
    """The schedule root to use: the tracked one when it has every layer, else
    <out>/schedules, seeded with the tracked schedules and solved for the rest.
    Exits when a schedule was solved for another workload than meta.json gives."""
    root = wb.SCHEDULES
    if missing_schedules(root, bench, layers):
        root = out / "schedules"
        if (wb.SCHEDULES / bench).is_dir():
            shutil.copytree(wb.SCHEDULES / bench, root / bench, dirs_exist_ok=True)
        # solve_schedules.py skips schedules already in the cache.
        run_all([[sys.executable, str(ROOT / "scripts/solve_schedules.py"), "--archs", bench,
                  "--trace-root", str(INPUT_TRACE / bench),
                  "--trace-dirs", *sorted({d for d, _ in layers}), "--cache-dir", str(root)]],
                record, 1)
        # solve_schedules.py exits 0 even when a layer is infeasible or fails.
        still = missing_schedules(root, bench, layers)
        if still:
            sys.exit("solve_schedules.py did not write these schedules (see "
                     f"{root / 'summary.csv'}):\n  " + "\n  ".join(map(str, still)))
    stale = []
    for d, l in layers:
        try:
            check_schedule_matches_trace(root / bench / d / f"{l}.json", INPUT_TRACE / bench / d, l)
        except ValueError as e:
            stale.append(str(e))
    if stale:
        sys.exit("\n".join(stale))
    return root


def load_grid(path):
    """(grid name, list of wcache configs)."""
    if path is None:
        return "khkw", [p for lb in sweep.LINE_BYTES for p in sweep.grid_for(lb)]
    path = pathlib.Path(path)
    grid = json.loads(path.read_text())
    if not isinstance(grid, list) or not grid:
        sys.exit(f"--grid {path}: no configs (want a non-empty JSON array of wcache configs)")
    return path.stem, grid


def out_dir(a):
    return pathlib.Path(a.out or data_root() / "demo" / a.bench).resolve()


def demo(a):
    t0 = time.time()
    out = out_dir(a)
    layers = resolve_layers(a.bench, a.layers)
    samples = range(a.sample_start, a.sample_start + a.sample_count)
    problems = check_inputs(a.bench, layers, samples)
    missing = missing_schedules(wb.SCHEDULES, a.bench, layers)
    if missing and not can_solve():
        problems += ["gurobipy does not import, so this schedule cannot be solved: "
                     f"{p}" for p in missing]
    if problems:
        sys.exit("cannot run the demo:\n  " + "\n  ".join(problems))
    grid_name, grid = load_grid(a.grid)
    out.mkdir(parents=True, exist_ok=True)
    cmds = []
    sched_root = schedules_for(a.bench, layers, out, cmds)

    builds = [["make", "-C", str(ROOT / "src/cachesim/native"), "MODE=release", "apps"],
              ["make", "-C", str(ROOT / "src/nocsim/eventsim")]]
    if (ROOT / "src/weight_trace_gen" / a.bench / "Makefile").is_file():
        builds.append(["make", "-C", str(ROOT / "src/weight_trace_gen" / a.bench)])
    run_all(builds, cmds, 1)

    gen = [sys.executable, str(ROOT / "scripts/generate_weight_traces.py"), "--arch", a.bench,
           "--trace-root", str(INPUT_TRACE / a.bench),
           "--schedule-cache", str(sched_root), "--workers", "1"]
    streams = {(d, l, s): out / "streams" / d / f"{l}_s{s:05d}.wcts"
               for d, l in layers for s in samples}
    for p in streams.values():
        p.parent.mkdir(parents=True, exist_ok=True)
    run_all([gen + ["--trace-dir", d, "--layer", l, "--out-dir", str(out / "weight_traces"),
                    "--sample-start", str(a.sample_start), "--sample-count", str(a.sample_count),
                    "--force"] for d, l in layers]
            + [gen + ["--trace-dir", d, "--layer", l, "--stream", "--sample-start", str(s),
                      "--sample-count", "1", "--dump-trace", str(p)]
               for (d, l, s), p in streams.items()], cmds, a.jobs)

    nocsim_cmds = []
    for d, l in layers:
        sched = sched_root / a.bench / d / f"{l}.json"
        lyaml = out / "layers" / d / f"{l}.yaml"
        lyaml.parent.mkdir(parents=True, exist_ok=True)
        lyaml.write_text(yaml.safe_dump(json.loads(sched.read_text())["workload"], sort_keys=False))
        for s in samples:
            tc = out / "nocsim" / d / f"{l}_s{s:05d}.csv"
            tc.parent.mkdir(parents=True, exist_ok=True)
            nocsim_cmds.append(
                [sys.executable, "-m", "nocsim.sim", "--schedule", str(sched),
                 "--layer", str(lyaml), "--arch", str(NOCSIM_ARCH[a.bench]),
                 "--weight-trace", str(out / "weight_traces" / a.bench / d / l / f"sample_{s:05d}.json.gz"),
                 "--out", str(tc), "--simulate"])

    # cachesim_sweep gives one mapper to a whole grid, so points that differ in
    # cin_block go to separate invocations (run_khkw_sweep.py does the same).
    groups = {}
    for i, p in enumerate(grid):
        groups.setdefault(p.get("cin_block"), []).append((f"{grid_name}_{i:02d}", p))
    grid_files = []
    for k, pts in enumerate(groups.values()):
        g = out / "grid" / f"{grid_name}_{k}.json"
        g.parent.mkdir(parents=True, exist_ok=True)
        g.write_text(json.dumps([p for _, p in pts], indent=1))
        grid_files.append((g, [c for c, _ in pts]))
    wc_work = [(d, l, s, g, names) for (d, l, s) in streams for g, names in grid_files]
    wc_cmds = [[str(sweep.BIN), "--config-grid", str(g), "--trace", str(streams[(d, l, s)]),
                "--arm", "cache", "--tier", grid_name, "--run-id", f"demo-{l}-s{s}-{g.stem}", "--header"]
               for d, l, s, g, _ in wc_work]

    nocsim = {}
    for (d, l, s), stdout in zip(list(streams), run_all(nocsim_cmds, cmds, a.jobs, capture=True)):
        got = [ln for ln in stdout.splitlines() if ln.startswith("total_cycles")]
        if not got:
            sys.exit(f"nocsim printed no total_cycles for {d}/{l} s{s}:\n{stdout[-2000:]}")
        nocsim[(d, l, s)] = int(got[0].split(":")[1])

    wcache_rows = []
    for (d, l, s, _, names), stdout in zip(wc_work, run_all(wc_cmds, cmds, a.jobs, capture=True)):
        got = list(csv.DictReader(stdout.splitlines()))
        if len(got) != len(names):
            sys.exit(f"cachesim_sweep gave {len(got)} rows for {len(names)} configs ({d}/{l} s{s})")
        for name, w in zip(names, got):
            wcache_rows.append({"trace_dir": d, "layer": l, "sample": s, "config": name,
                                **{k: w[k] for k in KEY_FIELDS}, "total_cycles": w["total_cycles"]})

    rows = join_results(nocsim, wcache_rows)
    with open(out / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    write_summary(out / "summary.md", a, layers, grid_name, rows, cmds, time.time() - t0)
    print(f"{len(rows)} rows -> {out / 'results.csv'}  ({time.time() - t0:.0f}s)")
    return 0


def write_summary(path, a, layers, grid_name, rows, cmds, seconds):
    keys = {r["config"]: " ".join(f"{k}={r[k]}" for k in KEY_FIELDS) for r in rows}
    lines = [f"# Demo: {a.bench}", "",
             f"Layers: {', '.join(f'{d}/{l}' for d, l in layers)}; samples "
             f"{a.sample_start}..{a.sample_start + a.sample_count - 1}; grid {grid_name} "
             f"({len(keys)} configs); {len(rows)} rows; {seconds:.0f} s.", "",
             "speedup_vs_nocsim = nocsim total_cycles / wcache total_cycles; "
             "geomean over every (layer, sample) of the config.", "",
             "| config | geomean speedup | rows | key fields |", "|---|---|---|---|"]
    lines += [f"| {c} | {g:.4f} | {n} | {keys[c]} |" for c, g, n in summarize(rows)]
    lines += ["", "## Commands", "",
              f"Run as: {json.dumps([sys.executable, *sys.argv])}. Every command below ran "
              f"with cwd {ROOT} and PYTHONPATH={ENV['PYTHONPATH']}, in this order "
              "(commands in one group ran in parallel).", "", "```"]
    lines += [json.dumps(c) for c in cmds] + ["```", ""]
    path.write_text("\n".join(lines))


def verify(results_path, base):
    """Mismatches between results.csv and the reference wcache sweep and nocsim CSVs."""
    with open(base / "wcache/khkw_sweep.csv", newline="") as f:
        ref_w = {(r["workload"], r["layer"], r["sample_idx"], r["line_size_bytes"], r["l2_banks"],
                  r["prefetch_policy"], r["prefetch_distance"]): r["total_cycles"]
                 for r in csv.DictReader(f)}
    with open(base / "nocsim/stage3_results.csv", newline="") as f:
        ref_n = {(r["trace_dir"], r["layer"], r["sample"]): r["total_cycles"] for r in csv.DictReader(f)}
    with open(results_path, newline="") as f:
        rows = list(csv.DictReader(f))
    bad = missing = 0
    for r in rows:
        kw = (r["trace_dir"], r["layer"], r["sample"], r["line_size_bytes"], r["l2_banks"],
              r["prefetch_policy"], r["prefetch_distance"])
        for name, ref, key, col in (("wcache", ref_w, kw, "wcache_total_cycles"),
                                    ("nocsim", ref_n, kw[:3], "nocsim_total_cycles")):
            if key not in ref:
                missing += 1
                print(f"  {name} not in reference: {key}")
            elif ref[key] != r[col]:
                bad += 1
                print(f"  {name} mismatch {key}: ref {ref[key]} demo {r[col]}")
    pairs = {(r["trace_dir"], r["layer"], r["sample"]) for r in rows}
    print(f"{results_path}: {len(rows)} rows; wcache compared {len(rows)} against {len(ref_w)} "
          f"reference rows, nocsim compared {len(rows)} ({len(pairs)} distinct layer-samples) "
          f"against {len(ref_n)}; mismatches {bad}, not in reference {missing}")
    return 1 if bad or missing or not rows else 0


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--bench", default="loas")
    p.add_argument("--layers", nargs="+", default=list(sweep.TAGS),
                   help="trace_dir/layer or a tag such as V8 (default: the 4 tracked, %(default)s)")
    p.add_argument("--sample-start", type=int, default=0)
    p.add_argument("--sample-count", type=int, default=5)
    p.add_argument("--out", help="default $NEURO_CACHE_DATA/demo/<bench>")
    p.add_argument("--grid", help="JSON array of wcache configs (default: the 0823 khkw grid)")
    p.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                   help="parallel commands (default %(default)s; each can use several GB)")
    p.add_argument("--verify-baseline", nargs="?", const=str(ROOT / ".baseline/after"),
                   metavar="DIR", help="only compare <out>/results.csv with DIR's reference CSVs")
    p.add_argument("--check-bench", metavar="BENCH",
                   help="only check input_trace/BENCH (or the directory BENCH) against the input contract")
    a = p.parse_args()
    if a.check_bench:
        problems, notes = check_bench(a.check_bench)
        print("\n".join(notes + [f"{a.check_bench}: {len(problems)} problems"] + problems))
        return 1 if problems else 0
    for name in ("sample_count", "jobs"):
        if getattr(a, name) < 1:
            p.error(f"--{name.replace('_', '-')} must be at least 1")
    if a.sample_start < 0:
        p.error("--sample-start must be at least 0")
    if a.verify_baseline:
        return verify(out_dir(a) / "results.csv", pathlib.Path(a.verify_baseline))
    return demo(a)


if __name__ == "__main__":
    sys.exit(main())
