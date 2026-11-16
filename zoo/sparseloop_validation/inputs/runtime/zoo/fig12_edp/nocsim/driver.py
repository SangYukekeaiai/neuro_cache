"""Replay a solved Fig12 schedule with one already-generated sample."""

import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

import yaml

from lays.nocsim.combine import combine
from lays.nocsim.schedule.buf_spatial import BufSpatial
from lays.nocsim.schedule.decode import schedule_from_strategy
from lays.nocsim.schedule.steps import StepInfo
from lays.nocsim.sim import run_eventsim
from lays.nocsim.step_cycles import load_step_cycles
from lays.parsers.arch import SNNArch
from lays.parsers.bitwidths import SNNBitwidths
from lays.parsers.layer import SNNProb
from lays.scheduler.artifact import read_artifact

from .energycounts import DRAM_BURST_BYTES, GB_WORD_BYTES, parse_tc_csv
from .wcts import load_wcts_cycles

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FREQUENCY_HZ = 500_000_000
DEFAULT_EVENTSIM = ROOT / "src/lays/nocsim/eventsim/eventsim"


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_hash():
    paths = list(Path(__file__).parent.glob("*.py"))
    for folder in ("nocsim", "parsers"):
        paths.extend((ROOT / "src/lays" / folder).rglob("*.py"))
    paths.extend((ROOT / "src/lays/nocsim/eventsim").glob("*.h"))
    paths.extend(ROOT / p for p in (
        "src/lays/scheduler/artifact.py", "src/lays/scheduler/constants.py",
        "src/lays/weight_trace_gen/__init__.py", "src/lays/cachesim/stream.py",
    ))
    return hashlib.sha256(json.dumps({str(p.relative_to(ROOT)): _sha256(p)
                                     for p in sorted(paths)
                                     if not p.name.startswith("test_")}, sort_keys=True).encode()).hexdigest()


def _sync(path):
    with Path(path).open("rb") as stream:
        os.fsync(stream.fileno())


def run_case(schedule_path, arch_name, trace_path=None, output_dir=None, *,
             wcts_path=None, steps_path=None, arch_path=None,
             eventsim_binary=None, frequency_hz=DEFAULT_FREQUENCY_HZ):
    """Return a flat NoC counts/latency dict and atomically save result.json.

    Exactly one of trace_path, wcts_path, steps_path is required. trace_path
    accepts either an uncompressed native WCTS or generated step JSON(.gz).
    These are reused artifacts, NOT raw spike captures: this function never
    regenerates a trace. schedule_path is a saved ScheduleArtifact. arch_path
    defaults to its result.configs.arch (relative paths are repo-relative).
    Supply arch_path explicitly when a stored config path is no longer valid.

    Resume requires matching schedule, sample, arch YAML, source, binary and
    frequency hashes/values, plus the saved tc.csv checksum. Stale results
    raise ValueError; choose a new output_dir for a different case/config.
    """
    sources = [p for p in (trace_path, wcts_path, steps_path) if p is not None]
    if len(sources) != 1 or output_dir is None:
        raise ValueError("supply exactly one trace_path/wcts_path/steps_path and output_dir")
    if not math.isfinite(frequency_hz) or frequency_hz <= 0:
        raise ValueError("frequency_hz must be finite and positive")
    schedule_path, sample_path = Path(schedule_path).resolve(), Path(sources[0]).resolve()
    artifact = read_artifact(schedule_path)
    if artifact.arch != arch_name or not artifact.result.get("has_solution"):
        raise ValueError("schedule arch differs from arch_name or schedule has no solution")
    config = arch_path or artifact.result.get("configs", {}).get("arch")
    if not config:
        raise ValueError("schedule has no arch config; supply arch_path")
    config = Path(config)
    config = (ROOT / config).resolve() if not config.is_absolute() else config.resolve()
    binary = Path(eventsim_binary or DEFAULT_EVENTSIM).resolve()
    with sample_path.open("rb") as stream:
        is_wcts = stream.read(8) == b"WCTRACE1"
    if (wcts_path is not None and not is_wcts) or (steps_path is not None and is_wcts):
        raise ValueError("sample format disagrees with wcts_path/steps_path")
    inputs = {name: {"path": str(p), "sha256": _sha256(p)} for name, p in (
        ("schedule", schedule_path), ("sample", sample_path),
        ("arch_config", config), ("eventsim", binary),
    )}
    if artifact.arch_yaml_sha256 and artifact.arch_yaml_sha256 != inputs["arch_config"]["sha256"]:
        raise ValueError("arch YAML hash differs from the schedule's arch_yaml_sha256")
    inputs.update(arch_name=arch_name, frequency_hz=frequency_hz,
                  source_sha256=_source_hash(), schema="fig12_noc_v1")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result_path, tc_path = output / "result.json", output / "tc.csv"
        if result_path.exists():
            previous = json.loads(result_path.read_text())
            if previous.get("inputs") != inputs:
                raise ValueError("resume input hashes/config changed; use a new output_dir")
            if not tc_path.exists() or _sha256(tc_path) != previous.get("tc_sha256"):
                raise ValueError("resume tc.csv missing or checksum changed")
            return previous
        with tempfile.TemporaryDirectory(prefix=".run-", dir=output) as temporary:
            temporary = Path(temporary)
            workload_path = temporary / "workload.yaml"
            workload_path.write_text(yaml.safe_dump(artifact.workload))
            prob, arch, widths = SNNProb(workload_path), SNNArch(config), SNNBitwidths(config)
            schedule = schedule_from_strategy(artifact.result["strategy"], prob)
            if schedule.dram_num_steps != artifact.dram_num_steps:
                raise ValueError("schedule artifact dram_num_steps differs from strategy")
            si = StepInfo(schedule, prob)
            free = {name: getattr(si, name) for name in (
                "is_psum_gb_free", "is_vmem_gb_free", "is_psum_dram_free", "is_vmem_dram_free")}
            if not all(free.values()):
                raise ValueError(f"Fig12 requires free psum/vmem GB/DRAM boundaries: {free}")
            if arch.single_node and math.prod(schedule.spatial_factors.values()) != 1:
                raise ValueError("single_node config disagrees with spatial schedule")
            cycles = (load_wcts_cycles(sample_path, artifact, schedule) if is_wcts
                      else load_step_cycles(sample_path))
            cycles.check_against(artifact, schedule)
            expected = {(d, n) for d in range(schedule.dram_num_steps)
                        for n in range(schedule.noc_num_steps)}
            if set(cycles.by_step) != expected:
                raise ValueError("step keys do not cover the schedule")
            for c in cycles.by_step.values():
                if (type(c.mac_cycles) is not int or c.mac_cycles < 0
                        or (c.lif_cycles is not None
                            and (type(c.lif_cycles) is not int or c.lif_cycles < 0))):
                    raise ValueError("step cycles must be nonnegative integers")
            gen = combine(schedule, BufSpatial(schedule, prob), si, prob, widths,
                          arch=arch, cycles_by_step=cycles.by_step)
            staged_tc = temporary / "tc.csv"
            gen.to_file(staged_tc)
            noc = gen.noc
            topology = dict(X=noc.X, Y=noc.Y, gb_port=noc.gb_port, dram_port=noc.dram_port)
            del gen
            counts = parse_tc_csv(staged_tc, **topology)
            latency = run_eventsim(staged_tc, noc.X, noc.Y, noc.dram_port,
                                   widths.dram_latency, binary=binary)
            if type(latency.get("total_cycles")) is not int or latency["total_cycles"] < 0:
                raise ValueError("eventsim returned invalid total_cycles")
            result = {**counts, "total_cycles": latency["total_cycles"],
                      "frequency_hz": frequency_hz,
                      "time_seconds": latency["total_cycles"] / frequency_hz,
                      "arch": arch_name, "trace_dir": artifact.trace_dir,
                      "layer_name": artifact.layer_name, "sample_idx": cycles.sample_idx,
                      "eventsim": latency, "topology": topology,
                      "free_boundaries": free, "inputs": inputs,
                      "tc_sha256": _sha256(staged_tc),
                      "units": {"gb_access_bytes": GB_WORD_BYTES,
                                "dram_burst_bytes": DRAM_BURST_BYTES},
                      "cycle_source": {"format": "wcts" if is_wcts else "step_cycles",
                                       "steps": len(cycles.by_step), "mac_reduction": "max_over_cores",
                                       "lif_none_means": "zero_extra_count_cycles"}}
            staged_result = temporary / "result.json"
            staged_result.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            _sync(staged_tc)
            _sync(staged_result)
            os.replace(staged_tc, tc_path)
            os.replace(staged_result, result_path)
            directory = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule", required=True)
    parser.add_argument("--arch", required=True, help="architecture name in the schedule")
    parser.add_argument("--trace", required=True, help="existing WCTS or step JSON(.gz)")
    parser.add_argument("--out", required=True, help="per-case output directory")
    parser.add_argument("--arch-path")
    parser.add_argument("--eventsim-binary")
    parser.add_argument("--frequency-hz", type=float, default=DEFAULT_FREQUENCY_HZ)
    args = parser.parse_args()
    result = run_case(args.schedule, args.arch, args.trace, args.out,
                      arch_path=args.arch_path, eventsim_binary=args.eventsim_binary,
                      frequency_hz=args.frequency_hz)
    print(json.dumps(result, sort_keys=True))
