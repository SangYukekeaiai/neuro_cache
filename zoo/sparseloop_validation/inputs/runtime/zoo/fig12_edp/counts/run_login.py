"""Run the measured, authorized login-node count job in 50-sample chunks."""
import csv
import json
import resource
import time
from pathlib import Path

import spinalflow_counts as counts


def main():
    root = Path("/work/nvme/bebv/yyu9/input_trace_delta")
    output = Path(__file__).with_name("spinalflow_counts.csv")
    started = time.monotonic()
    expected = set()
    for capture in counts._capture_dirs(root):
        meta = json.loads((capture / "meta.json").read_text())
        for layer in counts._valid_layers(meta):
            expected.update((capture.relative_to(root).as_posix(), layer, sample)
                            for sample in range(meta["layers"][layer][1]))
    max_samples = max(key[2] for key in expected) + 1
    for sample in range(0, max_samples, 50):
        rc = counts.main(["--trace-root", str(root), "--output", str(output),
                          "--sample-start", str(sample), "--sample-count", "50",
                          "--threads", "4", "--resume"])
        if rc:
            return rc
        usage = resource.getrusage(resource.RUSAGE_SELF)
        cpu = usage.ru_utime + usage.ru_stime
        print(f"through sample {sample + 49}: cpu_seconds={cpu:.3f}", flush=True)
        if cpu > 1800:
            raise RuntimeError("30 CPU-minute login budget reached; resume through Slurm")
    with output.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    observed = [(row["capture"], row["layer"], int(row["sample"])) for row in rows]
    if len(observed) != len(set(observed)) or set(observed) != expected:
        raise ValueError("CSV coverage or uniqueness check failed")
    for row in rows:
        if (int(row["A"]) != int(row["S_win"]) * int(row["COUT"])
                or int(row["R"]) * int(row["cout_n"]) != int(row["A"])
                or int(row["O"]) != int(row["HO"]) * int(row["WO"]) * int(row["COUT"]) * int(row["T"])):
            raise ValueError(f"count identity failed: {row}")
    report = {"rows": len(rows), "captures": len({key[0] for key in expected}),
              "layers": len({key[:2] for key in expected}), "coverage": "pass",
              "wall_seconds": time.monotonic() - started, "cpu_seconds": cpu,
              "threads_cap": 4, "chunk_samples": 50, "gpu_hours": 0}
    output.with_name("counts_validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
