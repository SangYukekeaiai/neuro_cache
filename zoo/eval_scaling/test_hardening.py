"""Campaign boundaries: complete batches, byte-only joins, and consumed-input hashes."""
import csv
import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(f"eval_scaling_{name}", HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("omitted", [(4, 5), ()])
def test_batch_completeness_before_any_nocsim(tmp_path, monkeypatch, omitted):
    runner = load("run_case")
    repo = tmp_path / "repo"
    es = repo / "zoo/eval_scaling"
    point, layer = "single_x1", "layer_test"
    s1 = es / "outputs/s1" / point
    for p in (s1 / "schedules/loas" / runner.CAPTURE / f"{layer}.json",
              s1 / "workloads" / runner.CAPTURE / f"{layer}.yaml",
              es / "configs/arch_single_x1.yaml"):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")
    scratch = tmp_path / "scratch"
    out = tmp_path / "results/case.csv"
    monkeypatch.setattr(runner.sys, "argv", ["run_case", "--repo", str(repo),
        "--trace-root", "unused", "--point", point, "--layer", layer,
        "--samples", "3", "--sample-count", "3", "--scratch", str(scratch), "--out", str(out)])
    calls = []

    def run(command, log):
        calls.append(command[2])
        if command[2] == "lays.weight_trace_gen":
            trace_dir = scratch / f"es_{point}_{layer}" / "loas" / runner.CAPTURE / layer
            trace_dir.mkdir(parents=True)
            for sample in (3, 4, 5):
                if sample not in omitted:
                    (trace_dir / f"sample_{sample:05d}.json.gz").write_bytes(b"trace")
            return ""
        assert not omitted, "nocsim must not start on an incomplete batch"
        return ("total_cycles: 20\nunicast_cycles: 1\nmulticast_cycles: 2\n"
                "count_cycles: 10\ndram_cycles: 3\n"
                "weight unicast_hops=0 multicast_hops=0 dram_cost=1 dram_bytes=33\n"
                "psum unicast_hops=0 multicast_hops=0 dram_cost=1 dram_bytes=3\n"
                "vmem unicast_hops=0 multicast_hops=0 dram_cost=1 dram_bytes=4\n")

    monkeypatch.setattr(runner, "run", run)
    if omitted:
        with pytest.raises(RuntimeError) as exc:
            runner.main()
        for sample in omitted:
            assert f"sample_{sample:05d}.json.gz" in str(exc.value)
        assert "sample_00003.json.gz" not in str(exc.value)
        assert calls == ["lays.weight_trace_gen"]
        assert not out.exists()
        assert scratch.exists()
    else:
        assert runner.main() == 0
        assert calls == ["lays.weight_trace_gen"] + ["lays.nocsim"] * 3
        with out.open() as handle:
            rows = list(csv.DictReader(handle))
        assert [int(row["sample"]) for row in rows] == [3, 4, 5]
        assert all([row[f"dram_bytes_{v}"] for v in ("weight", "psum", "vmem")]
                   == ["33", "3", "4"] for row in rows)
        assert all(row["dram_cost_weight"] == "1.0" for row in rows)
        assert not (scratch / f"es_{point}_{layer}").exists()


def case_inputs(tmp_path, aggregate):
    out = tmp_path / "outputs"
    (out / "s4").mkdir(parents=True)
    paths = []
    for point in ("single_x1", "multi_x1"):
        rows = []
        for index, nodes in ((1, 2), (2, 5)):
            layer = f"layer_{index}"
            schedule = out / "s1" / point / "schedules/loas" / aggregate.CAPTURE / f"{layer}.json"
            workload = out / "s1" / point / "workloads" / aggregate.CAPTURE / f"{layer}.yaml"
            for path in (schedule, workload):
                path.parent.mkdir(parents=True, exist_ok=True)
                paths.append(path)
            schedule.write_text(json.dumps({"result": {
                "metrics": {"temporal_traffic": {"weight": index}, "util": {"weight": 3}},
                "strategy": {"NoCLevel": {"spatial_splitting": {
                    "loops": [] if point == "single_x1" else [{"size": nodes}]}}}}}))
            workload.write_text("problem: {KH: 1, KW: 1, CIN: 2, COUT: 3}\n")
            for sample in (0, 1):
                rows.append({"point": point, "layer": layer, "sample": sample,
                    "count_cycles": 100 if index == 1 else 50,
                    "total_cycles": 1000 if index == 1 else 200,
                    "nodes": 999, "dram_cost_weight": 99999, "dram_cost_psum": 99999,
                    "dram_cost_vmem": 99999,
                    "dram_bytes_weight": (33 if index == 1 else 64) * (sample + 1),
                    "dram_bytes_psum": (3 if index == 1 else 0) * (sample + 1),
                    "dram_bytes_vmem": (4 if index == 1 else 8) * (sample + 1)})
        path = out / "s4" / f"{point}.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        paths.append(path)
    return out, paths


def test_bytes_and_provenance_use_consumed_inputs(tmp_path, monkeypatch):
    aggregate = load("aggregate")
    out, paths = case_inputs(tmp_path, aggregate)
    monkeypatch.setattr(aggregate, "OUT", out)
    original = {str(p): (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths}

    def git_commit(*args, **kwargs):
        # A re-glob or re-hash here would falsely pin data not used in the result.
        for p in paths:
            p.write_text("changed after consumption")
        (out / "s4/late.csv").write_text("not consumed")
        return "test-commit\n"

    monkeypatch.setattr(aggregate.subprocess, "check_output", git_commit)
    aggregate.main()
    with (out / "aggregate.csv").open() as handle:
        rows = {r["point"]: r for r in csv.DictReader(handle)}
    assert float(rows["single_x1"]["util_mean"]) == 150 / 1200
    assert float(rows["multi_x1"]["util_mean"]) == 150 / 3000
    for row in rows.values():
        assert float(row["counted_dram_bytes_mean"]) == 168
        assert float(row["counted_dram_bytes_ci95"]) == pytest.approx(aggregate.T95 * 56)
        assert float(row["counted_traffic_norm"]) == 1
        assert float(row["analytic_traffic_bytes"]) == 9
    provenance = json.loads((out / "provenance.json").read_text())
    assert provenance["repo_commit"] == "test-commit"
    assert datetime.fromisoformat(provenance["recorded_at_utc"]).utcoffset().total_seconds() == 0
    assert {p["path"]: (p["bytes"], p["sha256"]) for p in provenance["inputs"]} == original
    assert "Weights-only" in provenance["floor"]


@pytest.mark.parametrize("defect", ["old_header", "missing_value", "invalid_value"])
def test_reject_mixed_or_incomplete_byte_csvs(tmp_path, monkeypatch, defect):
    aggregate = load("aggregate")
    out, paths = case_inputs(tmp_path, aggregate)
    monkeypatch.setattr(aggregate, "OUT", out)
    bad = out / "s4/zz_bad.csv"
    if defect == "old_header":
        bad.write_text("point,dram_cost_weight,dram_cost_psum,dram_cost_vmem\nsingle_x1,1,2,3\n")
    else:
        bad.write_text("point,dram_bytes_weight,dram_bytes_psum,dram_bytes_vmem\n"
                       + ("single_x1,1,2\n" if defect == "missing_value" else "single_x1,no,2,3\n"))
    for name in ("aggregate.csv", "provenance.json"):
        (out / name).write_text("existing product")
    with pytest.raises(ValueError) as exc:
        aggregate.main()
    assert str(bad) in str(exc.value)
    for name in ("aggregate.csv", "provenance.json"):
        assert (out / name).read_text() == "existing product"
