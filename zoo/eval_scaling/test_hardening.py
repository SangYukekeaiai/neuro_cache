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


@pytest.mark.parametrize("omitted, weight_total", [((4, 5), 20), ((), 20), ((), 30)])
def test_batch_completeness_before_any_nocsim(
    tmp_path, monkeypatch, omitted, weight_total
):
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
        tc_csv = Path(command[command.index("--out") + 1])
        tc_csv.write_text("0,0,2,1,0,,\n")
        return ("total_cycles: 20\nunicast_cycles: 1\nmulticast_cycles: 2\n"
                "count_cycles: 10\ndram_cycles: 3\n"
                "weight unicast_hops=0 multicast_hops=0 dram_cost=1 dram_bytes=33\n"
                "psum unicast_hops=0 multicast_hops=0 dram_cost=1 dram_bytes=3\n"
                "vmem unicast_hops=0 multicast_hops=0 dram_cost=1 dram_bytes=4\n")

    monkeypatch.setattr(runner, "run", run)
    def fake_weight_only(tc_csv, schedule, layer_yaml, arch_yaml, repo, log_path):
        assert tc_csv.is_file()
        return {"total_cycles": weight_total}, 0.001
    monkeypatch.setattr(runner, "run_weight_only", fake_weight_only)
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
        assert all(row["weight_makespan"] == str(weight_total) for row in rows)
        expected_violation = max(0, weight_total - 20)
        assert all(
            int(row["weight_gate_violation"]) == expected_violation for row in rows
        )
        assert all(float(row["weight_only_seconds"]) == pytest.approx(0.001) for row in rows)
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
                    "weight_makespan": 1000 if index == 1 else 200,
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


@pytest.mark.parametrize("git_status", [
    "", " M unrelated.py\n", "?? scratch/\n",
    " M src/lays/nocsim/core/generator.py\n M zoo/eval_scaling/aggregate.py\n?? unrelated/\n",
])
def test_bytes_and_provenance_use_consumed_inputs(tmp_path, monkeypatch, git_status):
    aggregate = load("aggregate")
    out, paths = case_inputs(tmp_path, aggregate)
    monkeypatch.setattr(aggregate, "OUT", out)
    original = {str(p): (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths}

    def git_commit(command, **kwargs):
        assert kwargs["cwd"] == aggregate.HERE.parents[1]
        if command == ["git", "status", "--porcelain"]:
            return git_status
        assert command == ["git", "rev-parse", "HEAD"]
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
        assert float(row["counted_dram_bytes_mean"]) == 145.5
        assert float(row["counted_dram_bytes_ci95"]) == pytest.approx(
            aggregate.critical_value(2) * 48.5
        )
        assert float(row["counted_traffic_norm"]) == 1
        assert float(row["analytic_traffic_bytes"]) == 9
    provenance = json.loads((out / "provenance.json").read_text())
    assert provenance["repo_commit"] == "test-commit" + ("-dirty" if git_status else "")
    assert provenance["dirty_paths"] == git_status.splitlines()
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


def test_dedup_identity_gate_checks_one_real_skipped_point_per_arch_side(tmp_path):
    dedup = load("dedup")
    s4 = tmp_path / "s4"
    s4.mkdir()
    entries = []
    for arch, side in (("loas", "single"), ("ptb", "multi")):
        representative = f"{arch}_{side}_x1"
        skipped = f"{arch}_{side}_x2"
        entries.append({
            "arch": arch,
            "arm": dedup.SPAD_ARM,
            "side": side,
            "layer": "layer_01",
            "multiplier": 1,
            "point": representative,
            "representative": representative,
            "deduped_from": None,
        })
        entries.append({
            "arch": arch,
            "arm": dedup.SPAD_ARM,
            "side": side,
            "layer": "layer_01",
            "multiplier": 2,
            "point": skipped,
            "representative": representative,
            "deduped_from": representative,
        })
        rows = []
        for point in (representative, skipped):
            rows.append({
                "point": point,
                "layer": "layer_01",
                "sample": "0",
                "total_cycles": "17",
                "weight_makespan": "13",
                "dram_bytes_weight": "11",
                "dram_bytes_psum": "2",
                "dram_bytes_vmem": "3",
            })
        with (s4 / f"{arch}_{side}.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    dedup_path = tmp_path / "dedup_map.json"
    dedup_path.write_text(json.dumps({"entries": entries}))
    checked = dedup.verify_identity_gate(dedup_path, s4, seed=0)
    assert {(item["arch"], item["side"]) for item in checked} == {
        ("loas", "single"), ("ptb", "multi")
    }


def test_cache_rows_are_never_reexpanded_from_a_representative(tmp_path):
    aggregate = load("aggregate")
    rows = {
        ("loas_cache_x1", "layer_01"): [{
            "point": "loas_cache_x1",
            "layer": "layer_01",
            "sample": "0",
        }]
    }
    bad_map = {
        "entries": [{
            "arch": "loas",
            "arm": aggregate.CACHE_ARM,
            "side": "multi",
            "layer": "layer_01",
            "multiplier": 2,
            "point": "loas_cache_x2",
            "representative": "loas_cache_x1",
        }]
    }
    with pytest.raises(ValueError, match="cache row"):
        aggregate.expand_dedup_rows(rows, bad_map)


def test_reexpand_preserves_real_rows_missing_from_dedup_map():
    aggregate = load("aggregate")
    rows = {
        ("loas_single_x1", "layer_01"): [{"point": "loas_single_x1"}],
        ("loas_cache_x4", "layer_01"): [{"point": "loas_cache_x4"}],
    }
    dedup_map = {
        "entries": [{
            "arch": "loas", "arm": aggregate.SPAD_ARM, "side": "single",
            "layer": "layer_01", "multiplier": 1,
            "point": "loas_single_x1", "representative": "loas_single_x1",
        }]
    }
    expanded = aggregate.expand_dedup_rows(rows, dedup_map)
    assert ("loas_cache_x4", "layer_01") in expanded


def test_reexpand_does_not_duplicate_existing_or_identity_rows():
    aggregate = load("aggregate")
    representative = [{"point": "loas_multi_x1", "sample": "0", "total_cycles": "500"}]
    rows = {
        ("loas_multi_x1", "layer_01"): representative,
        ("loas_multi_x2", "layer_01"): [
            {"point": "loas_multi_x2", "sample": "0", "total_cycles": "500"}
        ],
    }
    dedup_map = {
        "entries": [
            {
                "arch": "loas", "arm": aggregate.SPAD_ARM, "side": "multi",
                "layer": "layer_01", "multiplier": 1, "point": "loas_multi_x1",
                "representative": "loas_multi_x1",
            },
            {
                "arch": "loas", "arm": aggregate.SPAD_ARM, "side": "multi",
                "layer": "layer_01", "multiplier": 2, "point": "loas_multi_x2",
                "representative": "loas_multi_x1", "deduped_from": "loas_multi_x1",
            },
        ]
    }
    expanded = aggregate.expand_dedup_rows(rows, dedup_map)
    assert len(expanded[("loas_multi_x1", "layer_01")]) == len(representative)
    assert len(expanded[("loas_multi_x2", "layer_01")]) == len(representative)


def test_aggregate_uses_weight_metrics_for_both_arms(tmp_path, monkeypatch):
    aggregate = load("aggregate")
    out, _ = case_inputs(tmp_path, aggregate)
    cache_dir = out / "s4c"
    cache_dir.mkdir()
    rows = []
    for sample in (0, 1):
        for layer in ("layer_1", "layer_2"):
            rows.append({
                "point": "loas_cache_x1", "layer": layer, "sample": sample,
                "total_cycles": "300", "tick_base_total": "250",
                "dram_bytes": str(10 * (sample + 1)),
            })
    with (cache_dir / "loas_cache_x1.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(aggregate, "OUT", out)
    monkeypatch.setattr(
        aggregate.subprocess,
        "check_output",
        lambda command, **kwargs: "test-commit\n" if command[0] == "git" and command[1] == "rev-parse" else "",
    )
    aggregate.main()
    with (out / "aggregate.csv").open() as handle:
        result = {row["point"]: row for row in csv.DictReader(handle)}
    assert float(result["single_x1"]["counted_dram_bytes_mean"]) == 145.5
    assert float(result["loas_cache_x1"]["counted_dram_bytes_mean"]) == 30.0
    assert float(result["loas_cache_x1"]["perf_norm"]) == pytest.approx(2.0)


def test_dedup_identity_gate_rejects_missing_or_mismatched_bytes():
    dedup = load("dedup")
    representative = [{
        "sample": "0",
        "total_cycles": "17",
        "weight_makespan": "13",
        "dram_bytes_weight": "11",
    }]
    missing = [{"sample": "0", "total_cycles": "17", "weight_makespan": "13"}]
    mismatch = [{
        "sample": "0",
        "total_cycles": "17",
        "weight_makespan": "13",
        "dram_bytes_weight": "12",
    }]
    with pytest.raises(AssertionError, match="dram_bytes_weight"):
        dedup.assert_exact_identity(representative, missing)
    with pytest.raises(AssertionError, match="dram_bytes_weight"):
        dedup.assert_exact_identity(representative, mismatch)


def test_dedup_case_producer_keeps_one_skipped_point_per_arch_side(tmp_path, monkeypatch):
    dedup = load("dedup")
    monkeypatch.setattr(dedup, "OUT", tmp_path / "outputs")
    entries = []
    for arch, side in (("loas", "single"), ("ptb", "multi")):
        rep = f"{arch}_{side}_x1"
        skipped = f"{arch}_{side}_x2"
        entries.extend([
            {
                "arch": arch, "arm": dedup.SPAD_ARM, "side": side,
                "layer": "layer_01", "multiplier": 1, "point": rep,
                "representative": rep, "deduped_from": None,
            },
            {
                "arch": arch, "arm": dedup.SPAD_ARM, "side": side,
                "layer": "layer_01", "multiplier": 2, "point": skipped,
                "representative": rep, "deduped_from": rep,
            },
        ])
    entries.append({
        "arch": "loas", "arm": dedup.CACHE_ARM, "side": "multi",
        "layer": "layer_01", "multiplier": 1, "point": "loas_cache_x1",
        "representative": "loas_cache_x1", "deduped_from": None,
    })
    dedup.write_outputs({"entries": entries})
    cases = (tmp_path / "outputs" / "cases.txt").read_text().splitlines()
    identity = (tmp_path / "outputs" / "identity_cases.txt").read_text().splitlines()
    assert len(identity) == 2
    assert {line.split()[0] for line in identity} <= {
        "loas_single_x2", "ptb_multi_x2"
    }
    assert "loas_cache_x1 layer_01" in cases
    assert all(
        any(line.startswith(f"{point} ") for line in cases)
        for point in ("loas_single_x1", "ptb_multi_x1")
    )


def test_dedup_main_refuses_empty_schedule_corpus(tmp_path, monkeypatch):
    dedup = load("dedup")
    monkeypatch.setattr(dedup, "OUT", tmp_path / "outputs")
    monkeypatch.setattr(dedup, "CONFIGS", tmp_path / "configs")
    with pytest.raises(RuntimeError, match="no schedules"):
        dedup.main([])
