#!/usr/bin/env python3
"""Run the loas L2-prefetch comparison while retaining cache statistics."""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cachesim.grid import full_grid, load_sweep, write_grid  # noqa: E402
from util import data_root  # noqa: E402

import pipeline  # noqa: E402
from pipeline import join_results, resolve_layers, run_all  # noqa: E402


RESULT_FIELDS = (
    "bench", "trace_dir", "layer", "sample", "config",
    "layout", "line_size_bytes", "l2_banks", "prefetch_policy",
    "prefetch_distance", "l2_prefetch_policy", "l2_prefetch_distance",
    "nocsim_total_cycles", "wcache_total_cycles", "speedup_vs_nocsim",
    "stall_total", "fetch_latency_sum", "hidden_latency", "hidden_fraction",
    "l1_hits", "l1_accesses", "l1_hit_rate", "l2_hits", "l2_accesses",
    "l2_hit_rate", "dram_accesses", "dram_bytes", "l2_pf_issued",
    "l2_pf_timely", "l2_pf_late", "l2_pf_wasted", "l2_pf_coverage",
)

RAW_FIELDS = tuple(field for field in RESULT_FIELDS if field not in {
    "bench", "trace_dir", "layer", "sample", "config",
    "nocsim_total_cycles", "wcache_total_cycles", "speedup_vs_nocsim",
})


def _mean(rows, field):
    return sum(float(row[field]) for row in rows) / len(rows)


def _geomean(rows, field):
    return pipeline.geomean([float(row[field]) for row in rows])


def _grid(path):
    sweep = load_sweep(path)
    return pathlib.Path(path).stem, full_grid(sweep=sweep)


def _summary_rows(rows):
    groups = {}
    for row in rows:
        key = (row["layer"], row["prefetch_policy"], row["prefetch_distance"],
               row["l2_banks"])
        groups.setdefault(key, {}).setdefault(row["l2_prefetch_policy"], []).append(row)

    out = []
    for (layer, prefetch, distance, banks), arms in groups.items():
        baseline = arms.get("none")
        enhanced_names = [name for name in arms if name != "none"]
        if not baseline or len(enhanced_names) != 1:
            raise ValueError(f"summary group {layer}/{prefetch}/{banks} lacks one baseline "
                             "and one enhanced L2 arm")
        enhanced_name = enhanced_names[0]
        enhanced = arms[enhanced_name]
        out.append({
            "layer": layer,
            "prefetch_policy": f"{prefetch}@{distance}",
            "l2_banks": banks,
            "samples": len(baseline),
            "enhanced_policy": enhanced_name,
            "baseline_cycles": _mean(baseline, "wcache_total_cycles"),
            "enhanced_cycles": _mean(enhanced, "wcache_total_cycles"),
            "cycle_delta_enhanced_minus_baseline": (
                _mean(enhanced, "wcache_total_cycles") -
                _mean(baseline, "wcache_total_cycles")
            ),
            "baseline_l2_hit_rate": _mean(baseline, "l2_hit_rate"),
            "enhanced_l2_hit_rate": _mean(enhanced, "l2_hit_rate"),
            "l2_hit_rate_delta": (
                _mean(enhanced, "l2_hit_rate") - _mean(baseline, "l2_hit_rate")
            ),
            "baseline_speedup_vs_nocsim": _geomean(baseline, "speedup_vs_nocsim"),
            "enhanced_speedup_vs_nocsim": _geomean(enhanced, "speedup_vs_nocsim"),
        })
    return out


def write_summary(path, args, layers, grid_name, rows, commands, seconds):
    summary_rows = _summary_rows(rows)
    lines = [
        f"# L2 prefetch comparison: {args.bench}", "",
        f"Layers: {', '.join(f'{d}/{l}' for d, l in layers)}; samples "
        f"{args.sample_start}..{args.sample_start + args.sample_count - 1}; "
        f"grid {grid_name}; {len(rows)} rows; {seconds:.0f} s.", "",
        "Cycle and hit-rate columns are arithmetic means over the samples in each "
        "group; speedups are geomeans. The cycle delta is enhanced minus baseline.", "",
        "| layer | L1 prefetch | L2 banks | samples | enhanced policy | baseline cycles | "
        "enhanced cycles | cycle delta | baseline L2 hit rate | enhanced L2 hit rate | "
        "hit-rate delta | baseline speedup | enhanced speedup |",
        "|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['layer']} | {row['prefetch_policy']} | {row['l2_banks']} | "
            f"{row['samples']} | {row['enhanced_policy']} | "
            f"{row['baseline_cycles']:.2f} | {row['enhanced_cycles']:.2f} | "
            f"{row['cycle_delta_enhanced_minus_baseline']:.2f} | "
            f"{row['baseline_l2_hit_rate']:.6f} | {row['enhanced_l2_hit_rate']:.6f} | "
            f"{row['l2_hit_rate_delta']:.6f} | "
            f"{row['baseline_speedup_vs_nocsim']:.6f} | "
            f"{row['enhanced_speedup_vs_nocsim']:.6f} |"
        )
    lines += [
        "", "## Commands", "",
        f"Run as: {json.dumps([sys.executable, *sys.argv])}. Every command below ran "
        f"with cwd {ROOT} and PYTHONPATH={pipeline.ENV['PYTHONPATH']}, in this order "
        "(commands in one group ran in parallel).", "", "```",
    ]
    lines += [json.dumps(command) for command in commands] + ["```", ""]
    path.write_text("\n".join(lines))


def compare(args):
    t0 = time.time()
    layers = resolve_layers(args.bench, args.layers)
    samples = range(args.sample_start, args.sample_start + args.sample_count)
    problems = pipeline.check_inputs(args.bench, layers, samples)
    missing = pipeline.missing_schedules(pipeline.SCHEDULES, args.bench, layers)
    if missing and not pipeline.can_solve():
        problems += [
            "gurobipy does not import, so this schedule cannot be solved: "
            f"{path}" for path in missing
        ]
    if problems:
        raise SystemExit("cannot run the L2 prefetch comparison:\n  " + "\n  ".join(problems))

    grid_name, grid = _grid(args.grid)
    out = pathlib.Path(args.out or data_root() / "demo_l2pf" / args.bench).resolve()
    out.mkdir(parents=True, exist_ok=True)
    commands = []
    schedule_root = pipeline.schedules_for(args.bench, layers, out, commands)

    builds = [
        ["make", "-C", str(ROOT / "src/cachesim/native"), "MODE=release", "apps"],
        ["make", "-C", str(ROOT / "src/nocsim/eventsim")],
    ]
    if (ROOT / "src/weight_trace_gen" / args.bench / "Makefile").is_file():
        builds.append(["make", "-C", str(ROOT / "src/weight_trace_gen" / args.bench)])
    run_all(builds, commands, 1)

    gen = [
        sys.executable, "-m", "weight_trace_gen", "gen", "--arch", args.bench,
        "--trace-root", str(pipeline.INPUT_TRACE / args.bench),
        "--schedule-cache", str(schedule_root), "--workers", "1",
    ]
    streams = {
        (trace_dir, layer, sample): out / "streams" / trace_dir /
        f"{layer}_s{sample:05d}.wcts"
        for trace_dir, layer in layers for sample in samples
    }
    for stream in streams.values():
        stream.parent.mkdir(parents=True, exist_ok=True)
    run_all(
        [
            gen + [
                "--trace-dir", trace_dir, "--layer", layer,
                "--out-dir", str(out / "weight_traces"),
                "--sample-start", str(args.sample_start),
                "--sample-count", str(args.sample_count), "--force",
            ] for trace_dir, layer in layers
        ] + [
            gen + [
                "--trace-dir", trace_dir, "--layer", layer, "--stream",
                "--sample-start", str(sample), "--sample-count", "1",
                "--dump-trace", str(stream),
            ] for (trace_dir, layer, sample), stream in streams.items()
        ],
        commands,
        args.jobs,
    )

    nocsim_commands = []
    for trace_dir, layer in layers:
        schedule = schedule_root / args.bench / trace_dir / f"{layer}.json"
        layer_yaml = out / "layers" / trace_dir / f"{layer}.yaml"
        layer_yaml.parent.mkdir(parents=True, exist_ok=True)
        layer_yaml.write_text(
            pipeline.yaml.safe_dump(json.loads(schedule.read_text())["workload"], sort_keys=False)
        )
        for sample in samples:
            output = out / "nocsim" / trace_dir / f"{layer}_s{sample:05d}.csv"
            output.parent.mkdir(parents=True, exist_ok=True)
            nocsim_commands.append([
                sys.executable, "-m", "nocsim", "--schedule", str(schedule),
                "--layer", str(layer_yaml), "--arch", str(pipeline.NOCSIM_ARCH[args.bench]),
                "--weight-trace", str(
                    out / "weight_traces" / args.bench / trace_dir / layer /
                    f"sample_{sample:05d}.json.gz"
                ),
                "--out", str(output), "--simulate",
            ])

    grid_files = [
        (grid_file, [
            f"{grid_name}_{index:02d}" for index, point in enumerate(grid)
            if point.get("cin_block") == cin_block
        ])
        for cin_block, grid_file in write_grid(out / "grid", grid, grid_name).items()
    ]
    wcache_work = [
        (trace_dir, layer, sample, grid_file, names)
        for trace_dir, layer, sample in streams
        for grid_file, names in grid_files
    ]
    wcache_commands = [
        [
            sys.executable, "-m", "cachesim", "sweep",
            "--config-grid", str(grid_file), "--trace", str(streams[(trace_dir, layer, sample)]),
            "--arm", "cache", "--tier", grid_name,
            "--run-id", f"l2pf-{layer}-s{sample}-{grid_file.stem}", "--header",
        ]
        for trace_dir, layer, sample, grid_file, _ in wcache_work
    ]

    nocsim = {}
    for (trace_dir, layer, sample), stdout in zip(
            list(streams), run_all(nocsim_commands, commands, args.jobs, capture=True)):
        got = [line for line in stdout.splitlines() if line.startswith("total_cycles")]
        if not got:
            raise SystemExit(
                f"nocsim printed no total_cycles for {trace_dir}/{layer} s{sample}:\n"
                f"{stdout[-2000:]}"
            )
        nocsim[(trace_dir, layer, sample)] = int(got[0].split(":")[1])

    wcache_rows = []
    for (trace_dir, layer, sample, _, names), stdout in zip(
            wcache_work, run_all(wcache_commands, commands, args.jobs, capture=True)):
        got = list(csv.DictReader(stdout.splitlines()))
        if len(got) != len(names):
            raise SystemExit(
                f"cachesim_sweep gave {len(got)} rows for {len(names)} configs "
                f"({trace_dir}/{layer} s{sample})"
            )
        for name, raw in zip(names, got):
            wcache_rows.append({
                "trace_dir": trace_dir,
                "layer": layer,
                "sample": sample,
                "config": name,
                **{field: raw[field] for field in RAW_FIELDS},
                "total_cycles": raw["total_cycles"],
            })

    joined = join_results(nocsim, wcache_rows)
    rows = [{field: args.bench if field == "bench" else row[field]
             for field in RESULT_FIELDS} for row in joined]
    with (out / "results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    write_summary(out / "summary.md", args, layers, grid_name, rows, commands,
                  time.time() - t0)
    print(f"{len(rows)} rows -> {out / 'results.csv'}  ({time.time() - t0:.0f}s)")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench", default="loas")
    parser.add_argument("--layers", nargs="+", default=list(pipeline.TAGS),
                        help="trace_dir/layer, a tag such as V8, or all")
    parser.add_argument("--sample-start", type=int, default=0)
    parser.add_argument("--sample-count", type=int, default=5)
    parser.add_argument("--jobs", type=int, default=pipeline.DEFAULT_JOBS)
    parser.add_argument("--out", help="default $NEURO_CACHE_DATA/demo_l2pf/<bench>")
    parser.add_argument("--grid", default=str(ROOT / "configs/cache/l2pf_demo.json"),
                        help="sweep JSON (default: configs/cache/l2pf_demo.json)")
    args = parser.parse_args()
    if args.sample_count < 1 or args.jobs < 1:
        parser.error("--sample-count and --jobs must be at least 1")
    if args.sample_start < 0:
        parser.error("--sample-start must be at least 0")
    return compare(args)


if __name__ == "__main__":
    sys.exit(main())
