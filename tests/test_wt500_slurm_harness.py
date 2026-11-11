import csv
import json
import pathlib
import sys
import threading
import time

import pytest


REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "zoo/wt500_fig3cfg/slurm"))

import harness  # noqa: E402


def test_run_shard_streams_missing_samples_concurrently_in_order(tmp_path, monkeypatch):
    case_file = tmp_path / "cases_0000.json"
    cases = [
        {"arch": "loas", "trace_dir": "trace", "layer": "layer", "sample": sample}
        for sample in range(3)
    ]
    case_file.write_text(json.dumps({"cases": cases}))
    shard_dir = tmp_path / "shard"
    existing = shard_dir / "wcts/loas/trace/layer/sample_00000.wcts.gz"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"existing")

    active = 0
    maximum_active = 0
    lock = threading.Lock()

    def fake_cycles(command, _repo, _log_path):
        out_dir = pathlib.Path(command[command.index("--out-dir") + 1])
        output_dir = out_dir / "loas" / "trace" / "layer"
        output_dir.mkdir(parents=True)
        for sample in range(3):
            (output_dir / f"sample_{sample:05d}.json.gz").write_bytes(b"cycles")

    def fake_stream(_command, _repo, output_path, log_path):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.05)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"wcts")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("streamed")
        with lock:
            active -= 1

    monkeypatch.setattr(harness, "_run_cycles", fake_cycles)
    monkeypatch.setattr(harness, "_run_stream", fake_stream)

    assert harness.run_shard(
        case_file=case_file,
        shard_dir=shard_dir,
        repo=tmp_path,
        python="python",
        trace_root=pathlib.Path("/trace"),
        schedule_cache=pathlib.Path("/cache"),
        workers=2,
    ) == 0
    assert maximum_active == 2

    with (shard_dir / "results_0000.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [int(row["sample"]) for row in rows] == [0, 1, 2]

    command_lines = (shard_dir / "logs/commands_0000.txt").read_text().splitlines()
    assert len(command_lines) == 3  # one cycle command and two non-resumed streams
    assert "--sample-start 1" in command_lines[1]
    assert "--sample-start 2" in command_lines[2]


def test_run_shard_cancels_queued_streams_after_failure(tmp_path, monkeypatch):
    case_file = tmp_path / "cases_0000.json"
    cases = [
        {"arch": "loas", "trace_dir": "trace", "layer": "layer", "sample": sample}
        for sample in range(40)
    ]
    case_file.write_text(json.dumps({"cases": cases}))
    shard_dir = tmp_path / "shard"
    started = []
    lock = threading.Lock()

    def fake_cycles(command, _repo, _log_path):
        out_dir = pathlib.Path(command[command.index("--out-dir") + 1])
        output_dir = out_dir / "loas" / "trace" / "layer"
        output_dir.mkdir(parents=True)
        for sample in range(40):
            (output_dir / f"sample_{sample:05d}.json.gz").write_bytes(b"cycles")

    def fake_stream(command, _repo, output_path, _log_path):
        sample = int(command[command.index("--sample-start") + 1])
        with lock:
            started.append(sample)
        if sample == 0:
            raise RuntimeError("boom on sample 0")
        time.sleep(0.05)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"wcts")

    monkeypatch.setattr(harness, "_run_cycles", fake_cycles)
    monkeypatch.setattr(harness, "_run_stream", fake_stream)

    with pytest.raises(RuntimeError, match="boom on sample 0"):
        harness.run_shard(
            case_file=case_file,
            shard_dir=shard_dir,
            repo=tmp_path,
            python="python",
            trace_root=pathlib.Path("/trace"),
            schedule_cache=pathlib.Path("/cache"),
            workers=4,
        )
    assert len(started) < len(cases)
