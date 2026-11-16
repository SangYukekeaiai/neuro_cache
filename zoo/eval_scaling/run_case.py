#!/usr/bin/env python3
"""S3+S4 for one eval_scaling case group: (point, layer) x samples.

Generates the weight traces (lays.weight_trace_gen, LoAS node model) into a
scratch dir, runs nocsim --simulate per sample, parses its stdout, and writes
one results CSV. Traces are deleted afterwards (wave pattern).

Usage (one Slurm array task = one case group):
  python run_case.py --repo <repo> --trace-root <...>/input_trace_delta/B09 \
      --point single_x1 --layer layer_01_core_features_3 \
      --samples 0 --sample-count 10 --scratch $TMPDIR --out <csv>
"""

import argparse
import csv
import pathlib
import re
import shutil
import subprocess
import sys

CAPTURE = "loas_vgg16_T4_n500"
STDOUT_KEYS = ("total_cycles", "unicast_cycles", "multicast_cycles",
               "count_cycles", "dram_cycles")


def run(cmd, log_path):
    r = subprocess.run(cmd, text=True, capture_output=True)
    log_path.write_text(" ".join(map(str, cmd)) + "\n" + r.stdout + r.stderr)
    if r.returncode:
        raise RuntimeError(f"failed ({r.returncode}): {cmd}; see {log_path}")
    return r.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=pathlib.Path, required=True)
    ap.add_argument("--trace-root", required=True, help="dir containing the capture dir")
    ap.add_argument("--point", required=True, help="side_xM, e.g. multi_x4")
    ap.add_argument("--layer", required=True)
    ap.add_argument("--samples", type=int, default=0, help="first sample index")
    ap.add_argument("--sample-count", type=int, default=10)
    ap.add_argument("--scratch", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    args = ap.parse_args()

    side, mult = args.point.rsplit("_x", 1)
    es = args.repo / "zoo" / "eval_scaling"
    s1 = es / "outputs" / "s1" / args.point
    schedule = s1 / "schedules" / "loas" / CAPTURE / f"{args.layer}.json"
    layer_yaml = s1 / "workloads" / CAPTURE / f"{args.layer}.yaml"
    arch_yaml = es / "configs" / f"arch_{side}_x{mult}.yaml"
    for p in (schedule, layer_yaml, arch_yaml):
        if not p.is_file():
            raise FileNotFoundError(p)

    scratch = args.scratch / f"es_{args.point}_{args.layer}"
    scratch.mkdir(parents=True, exist_ok=True)
    logs = args.out.parent / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    # S3: one batch generation for all samples of this (point, layer)
    run([
        sys.executable, "-m", "lays.weight_trace_gen", "gen", "--arch", "loas",
        "--trace-root", args.trace_root, "--trace-dir", CAPTURE,
        "--layer", args.layer, "--schedule-cache", str(s1 / "schedules"),
        "--sample-start", str(args.samples), "--sample-count", str(args.sample_count),
        "--out-dir", str(scratch), "--force",
    ], logs / f"{args.point}_{args.layer}_gen.log")

    expected = [scratch / "loas" / CAPTURE / args.layer / f"sample_{s:05d}.json.gz"
                for s in range(args.samples, args.samples + args.sample_count)]
    missing = [str(path) for path in expected if not path.is_file()]
    if missing:
        raise RuntimeError("Batch weight-trace generator omitted requested samples: "
                           + ", ".join(missing))

    # S4: nocsim per sample
    rows = []
    for s in range(args.samples, args.samples + args.sample_count):
        gz = scratch / "loas" / CAPTURE / args.layer / f"sample_{s:05d}.json.gz"
        stdout = run([
            sys.executable, "-m", "lays.nocsim",
            "--schedule", str(schedule), "--layer", str(layer_yaml),
            "--arch", str(arch_yaml),
            "--weight-trace", str(gz),
            "--out", str(scratch / f"txn_{s:05d}.csv"), "--simulate",
        ], logs / f"{args.point}_{args.layer}_s{s:05d}_nocsim.log")
        row = {"point": args.point, "side": side, "multiplier": int(mult),
               "nodes": 1 if side == "single" else 16,
               "layer": args.layer, "sample": s}
        for key in STDOUT_KEYS:
            m = re.search(rf"^{key}\s*:\s*(\d+)\s*$", stdout, re.MULTILINE)
            if not m:
                raise ValueError(f"missing {key} for sample {s}")
            row[key] = int(m[1])
        # dram_cost_* columns are diagnostic-only and unused by aggregate.py.
        for var in ("weight", "psum", "vmem"):
            m = re.search(rf"^\s*{var}\s+.*dram_cost=(\d+(?:\.\d+)?)", stdout, re.MULTILINE)
            if not m:
                raise ValueError(f"missing dram_cost[{var}] for sample {s}")
            row[f"dram_cost_{var}"] = float(m[1])
        for var in ("weight", "psum", "vmem"):
            m = re.search(rf"^\s*{var}\s+.*dram_bytes=(\d+)\s*$", stdout, re.MULTILINE)
            if not m:
                raise ValueError(f"missing dram_bytes[{var}] for sample {s}")
            row[f"dram_bytes_{var}"] = int(m[1])
        assert row["total_cycles"] >= row["count_cycles"] / row["nodes"]
        rows.append(row)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    shutil.rmtree(scratch)
    print(f"wrote {len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
