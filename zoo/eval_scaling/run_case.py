#!/usr/bin/env python3
"""Run one eval_scaling (architecture, point, layer) sample batch.

Scratchpad points use ``<arch>_<single|multi>_x<m>`` tokens.  Cache points
use ``<arch>_cache_x<m>`` and reuse the multi-node schedule while streaming
one WCTS sample directly into cachesim.

Scratchpad cases run eventsim once for the full transaction list and once with
the Q11 ``--weight-only`` ablation over the same ``tc.csv``; both makespans
and the timed second invocation are written to the result row.
"""

import argparse
import csv
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass


CAPTURE = "loas_vgg16_T4_n500"
STDOUT_KEYS = (
    "total_cycles",
    "unicast_cycles",
    "multicast_cycles",
    "count_cycles",
    "dram_cycles",
)


@dataclass(frozen=True)
class Point:
    token: str
    arch: str
    arm: str
    side: str
    multiplier: int

    @property
    def schedule_token(self) -> str:
        return f"{self.side}_x{self.multiplier}"


def parse_point(token: str) -> Point:
    """Parse new arch/arm tokens and the old LoAS-only tokens."""

    explicit = re.fullmatch(
        r"(?P<arch>[A-Za-z0-9]+)_(?P<arm>cache|spad_nocsim|spad)_"
        r"(?P<side>single|multi)_x(?P<m>\d+)",
        token,
    )
    if explicit:
        arch = explicit.group("arch")
        arm = "cache" if explicit.group("arm") == "cache" else "spad_nocsim"
        side = explicit.group("side")
        if arm == "cache" and side != "multi":
            raise ValueError("cache points use the multi-node schedule")
        return Point(token, arch, arm, side, int(explicit.group("m")))
    match = re.fullmatch(
        r"(?:(?P<arch>[A-Za-z0-9]+)_)?"
        r"(?P<kind>cache|spad_nocsim|spad|single|multi)_x(?P<m>\d+)",
        token,
    )
    if not match:
        raise ValueError(
            f"invalid point {token!r}; expected ARCH_single_xM, ARCH_multi_xM, "
            "or ARCH_cache_xM"
        )
    arch = match.group("arch") or "loas"
    kind = match.group("kind")
    multiplier = int(match.group("m"))
    if kind == "cache":
        return Point(token, arch, "cache", "multi", multiplier)
    if kind in {"single", "multi"}:
        return Point(token, arch, "spad_nocsim", kind, multiplier)
    # A bare spad token is retained as an input convenience for generated
    # case lists; it denotes the multi-node scratchpad side.
    return Point(token, arch, "spad_nocsim", "multi", multiplier)


def _thread_env() -> dict[str, str]:
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    return env


def run(cmd: list[str], log_path: pathlib.Path) -> str:
    result = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        env=_thread_env(),
    )
    log_path.write_text(" ".join(map(str, cmd)) + "\n" + result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"failed ({result.returncode}): {cmd}; see {log_path}")
    return result.stdout


def _eventsim_geometry(
    schedule: pathlib.Path,
    layer_yaml: pathlib.Path,
    arch_yaml: pathlib.Path,
) -> tuple[int, int, int, float]:
    """Return the eventsim mesh and DRAM parameters for one schedule."""

    from lays.nocsim.core.noc import NoC
    from lays.nocsim.schedule.decode import schedule_from_strategy
    from lays.parsers.bitwidths import SNNBitwidths
    from lays.parsers.layer import (
        DIM_CIN,
        DIM_COUT,
        DIM_HO,
        DIM_KH,
        DIM_KW,
        DIM_T,
        DIM_WO,
        SNNProb,
    )

    data = json.loads(schedule.read_text())
    solver_result = data.get("result", data)
    problem = SNNProb(layer_yaml)
    decoded = schedule_from_strategy(solver_result["strategy"], problem)
    factors = decoded.spatial_factors
    x = int(factors[DIM_T] * factors[DIM_WO] * factors[DIM_HO])
    y = int(factors[DIM_CIN] * factors[DIM_KW] * factors[DIM_KH] * factors[DIM_COUT])
    noc = NoC(x, y)
    return x, y, noc.dram_port, SNNBitwidths(arch_yaml).dram_latency


def run_weight_only(
    tc_csv: pathlib.Path,
    schedule: pathlib.Path,
    layer_yaml: pathlib.Path,
    arch_yaml: pathlib.Path,
    repo: pathlib.Path,
    log_path: pathlib.Path,
) -> tuple[dict[str, int], float]:
    """Run the Q11 ablation on the already-written transaction CSV."""

    binary = repo / "src" / "lays" / "nocsim" / "eventsim" / "eventsim"
    if not binary.is_file():
        raise FileNotFoundError(
            f"eventsim binary not found at {binary}; build it with make"
        )
    x, y, dram_port, dram_latency = _eventsim_geometry(
        schedule, layer_yaml, arch_yaml
    )
    started = time.perf_counter()
    stdout = run(
        [
            str(binary),
            str(tc_csv),
            "--X",
            str(x),
            "--Y",
            str(y),
            "--dram-port",
            str(dram_port),
            "--dram-latency",
            str(dram_latency),
            "--weight-only",
        ],
        log_path,
    )
    elapsed = time.perf_counter() - started
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"weight-only eventsim emitted invalid JSON: {stdout!r}") from exc
    if not isinstance(result, dict) or "total_cycles" not in result:
        raise ValueError("weight-only eventsim result has no total_cycles")
    return {key: int(value) for key, value in result.items()}, elapsed


def run_cache_stream(
    generator: list[str],
    cachesim: list[str],
    generator_log: pathlib.Path,
    cachesim_log: pathlib.Path,
) -> str:
    """Pipe one generator stream into one native cachesim row."""

    env = _thread_env()
    with generator_log.open("w") as log:
        producer = subprocess.Popen(
            generator,
            stdout=subprocess.PIPE,
            stderr=log,
            env=env,
        )
        assert producer.stdout is not None
        consumer = subprocess.run(
            cachesim,
            stdin=producer.stdout,
            text=True,
            capture_output=True,
            env=env,
        )
        producer.stdout.close()
        producer_rc = producer.wait()
    cachesim_log.write_text(
        " ".join(map(str, cachesim))
        + "\n"
        + consumer.stdout
        + consumer.stderr
    )
    if producer_rc:
        raise RuntimeError(f"stream generator failed ({producer_rc}); see {generator_log}")
    if consumer.returncode:
        raise RuntimeError(f"cachesim failed ({consumer.returncode}); see {cachesim_log}")
    return consumer.stdout


def _first_file(*paths: pathlib.Path) -> pathlib.Path:
    for path in paths:
        if path.is_file():
            return path
    raise FileNotFoundError(paths[0])


def _paths(es: pathlib.Path, point: Point, layer: str) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
    new_s1 = es / "outputs" / "s1" / point.arch / point.schedule_token
    old_s1 = es / "outputs" / "s1" / point.schedule_token
    schedule_rel = pathlib.Path("schedules") / point.arch / CAPTURE / f"{layer}.json"
    workload_rel = pathlib.Path("workloads") / CAPTURE / f"{layer}.yaml"
    schedule = _first_file(new_s1 / schedule_rel, old_s1 / schedule_rel)
    workload = _first_file(new_s1 / workload_rel, old_s1 / workload_rel)
    arch_yaml = _first_file(
        es / "configs" / f"arch_{point.arch}_{point.side}_x{point.multiplier}.yaml",
        es / "configs" / f"arch_{point.side}_x{point.multiplier}.yaml",
    )
    # The trace generator appends ``<arch>/<capture>/<layer>.json`` to this
    # directory.  Both layouts put the schedule cache at the ``schedules``
    # directory immediately above the architecture component.
    schedule_cache = schedule.parents[2]
    return schedule, workload, arch_yaml, schedule_cache


def _nocsim_row(stdout: str, point: Point, layer: str, sample: int) -> dict[str, object]:
    row: dict[str, object] = {
        "point": point.token,
        "arch": point.arch,
        "arm": point.arm,
        "side": point.side,
        "multiplier": point.multiplier,
        "nodes": 1 if point.side == "single" else 16,
        "layer": layer,
        "sample": sample,
    }
    for key in STDOUT_KEYS:
        match = re.search(rf"^{key}\s*:\s*(\d+)\s*$", stdout, re.MULTILINE)
        if not match:
            raise ValueError(f"missing {key} for sample {sample}")
        row[key] = int(match[1])
    for var in ("weight", "psum", "vmem"):
        match = re.search(
            rf"^\s*{var}\s+.*dram_cost=(\d+(?:\.\d+)?)",
            stdout,
            re.MULTILINE,
        )
        if not match:
            raise ValueError(f"missing dram_cost[{var}] for sample {sample}")
        row[f"dram_cost_{var}"] = float(match[1])
    for var in ("weight", "psum", "vmem"):
        match = re.search(
            rf"^\s*{var}\s+.*dram_bytes=(\d+)\s*$",
            stdout,
            re.MULTILINE,
        )
        if not match:
            raise ValueError(f"missing dram_bytes[{var}] for sample {sample}")
        row[f"dram_bytes_{var}"] = int(match[1])
    if row["total_cycles"] < row["count_cycles"] / row["nodes"]:
        raise AssertionError(
            f"total_cycles < count_cycles/nodes for {point.token} sample {sample}"
        )
    return row


def _cache_row(stdout: str, point: Point, layer: str, sample: int) -> dict[str, object]:
    rows = list(csv.DictReader(io.StringIO(stdout)))
    if len(rows) != 1:
        raise ValueError(f"cachesim emitted {len(rows)} rows for sample {sample}")
    row: dict[str, object] = dict(rows[0])
    row.update({
        "point": point.token,
        "arch": point.arch,
        "arm": point.arm,
        "side": point.side,
        "multiplier": point.multiplier,
        "nodes": 16,
        "layer": layer,
        "sample": sample,
    })
    try:
        if int(float(row["total_cycles"])) < int(float(row["tick_base_total"])):
            raise AssertionError(
                f"cache total_cycles < tick_base_total for {point.token} sample {sample}"
            )
    except KeyError as exc:
        raise ValueError("cachesim row has no tick_base_total") from exc
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=pathlib.Path, required=True)
    ap.add_argument("--trace-root", required=True, help="dir containing the capture dir")
    ap.add_argument("--point", required=True, help="ARCH_single_xM or ARCH_cache_xM")
    ap.add_argument("--layer", required=True)
    ap.add_argument("--samples", type=int, default=0, help="first sample index")
    ap.add_argument("--sample-count", type=int, default=10)
    ap.add_argument("--scratch", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    args = ap.parse_args(argv)

    point = parse_point(args.point)
    es = args.repo / "zoo" / "eval_scaling"
    schedule, layer_yaml, arch_yaml, schedule_cache = _paths(es, point, args.layer)
    # Keep these explicit checks close to the parser: a malformed case line
    # must not launch a generator against a different architecture.
    for path in (schedule, layer_yaml, arch_yaml):
        if not path.is_file():
            raise FileNotFoundError(path)

    logs = args.out.parent / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []

    if point.arm == "cache":
        config = es / "configs" / f"cache_x{point.multiplier}.json"
        if not config.is_file():
            raise FileNotFoundError(config)
        for sample in range(args.samples, args.samples + args.sample_count):
            generator = [
                sys.executable,
                "-m",
                "lays.weight_trace_gen",
                "gen",
                "--stream",
                "--arch",
                point.arch,
                "--trace-root",
                args.trace_root,
                "--trace-dir",
                CAPTURE,
                "--layer",
                args.layer,
                "--schedule-cache",
                str(schedule_cache),
                "--sample-start",
                str(sample),
                "--sample-count",
                "1",
            ]
            cachesim = [
                sys.executable,
                "-m",
                "lays.cachesim",
                "run",
                "--config",
                str(config),
                "--trace",
                "-",
                "--out",
                "-",
                "--arm",
                "cache",
                "--tier",
                "eval_scaling",
            ]
            stdout = run_cache_stream(
                generator,
                cachesim,
                logs / f"{point.token}_{args.layer}_s{sample:05d}_gen.log",
                logs / f"{point.token}_{args.layer}_s{sample:05d}_cache.log",
            )
            rows.append(_cache_row(stdout, point, args.layer, sample))
    else:
        scratch = args.scratch / f"es_{point.token}_{args.layer}"
        scratch.mkdir(parents=True, exist_ok=True)
        run(
            [
                sys.executable,
                "-m",
                "lays.weight_trace_gen",
                "gen",
                "--arch",
                point.arch,
                "--trace-root",
                args.trace_root,
                "--trace-dir",
                CAPTURE,
                "--layer",
                args.layer,
                "--schedule-cache",
                str(schedule_cache),
                "--sample-start",
                str(args.samples),
                "--sample-count",
                str(args.sample_count),
                "--out-dir",
                str(scratch),
                "--force",
            ],
            logs / f"{point.token}_{args.layer}_gen.log",
        )
        expected = [
            scratch
            / point.arch
            / CAPTURE
            / args.layer
            / f"sample_{sample:05d}.json.gz"
            for sample in range(args.samples, args.samples + args.sample_count)
        ]
        missing = [str(path) for path in expected if not path.is_file()]
        if missing:
            raise RuntimeError(
                "Batch weight-trace generator omitted requested samples: "
                + ", ".join(missing)
            )
        for sample, gz in zip(
            range(args.samples, args.samples + args.sample_count), expected
        ):
            tc_csv = scratch / f"txn_{sample:05d}.csv"
            stdout = run(
                [
                    sys.executable,
                    "-m",
                    "lays.nocsim",
                    "--schedule",
                    str(schedule),
                    "--layer",
                    str(layer_yaml),
                    "--arch",
                    str(arch_yaml),
                    "--weight-trace",
                    str(gz),
                    "--out",
                    str(tc_csv),
                    "--simulate",
                ],
                logs / f"{point.token}_{args.layer}_s{sample:05d}_nocsim.log",
            )
            row = _nocsim_row(stdout, point, args.layer, sample)
            weight_result, weight_seconds = run_weight_only(
                tc_csv,
                schedule,
                layer_yaml,
                arch_yaml,
                args.repo,
                logs / f"{point.token}_{args.layer}_s{sample:05d}_weight_only.log",
            )
            weight_makespan = weight_result["total_cycles"]
            row["weight_gate_violation"] = max(
                0, weight_makespan - row["total_cycles"]
            )
            if weight_makespan < row["count_cycles"] / row["nodes"]:
                raise AssertionError(
                    f"weight_makespan < count_cycles/nodes for {point.token} sample {sample}"
                )
            row["weight_makespan"] = weight_makespan
            row["weight_only_seconds"] = weight_seconds
            rows.append(row)
        shutil.rmtree(scratch)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("no samples requested")
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with args.out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
