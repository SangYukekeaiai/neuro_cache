"""Authorized sample-0-only 3x3 validation using the S3 count helper."""
import argparse
import csv
import json
import resource
import subprocess
import tempfile
import time
from pathlib import Path

import prosperity_counts as prosperity
import spinalflow_counts as spinal


def cpu_seconds():
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    spinal.cap_threads(1)
    import numpy as np
    root = spinal.ROOT
    here = Path(__file__).resolve().parent
    manifest_path = root / "zoo/wt500_fig3cfg/outputs/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    rows = [r for r in manifest["schedules"] if r["arch"] == "prosperity"
            and r["solver_status"] != "INFEASIBLE" and r["workload"]["problem"]["KH"] == 3]
    # Largest estimated mask/sort workload first gives a conservative timing pilot.
    rows.sort(key=lambda r: -np.prod([r["workload"]["problem"][k] for k in ("CIN", "HO", "WO", "T")]))
    output = here / "prosperity_sample0_records.csv"
    completed = prosperity.load_records(output) if output.exists() else {}
    anchors = prosperity.digest_anchors(root / "zoo/wt500_fig3cfg/stokes/s3_digest.md")
    bounds = {}
    for line in (root / "zoo/wt500_fig3cfg/stokes/s3_digest.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 14 and cells[1] == "prosperity":
            bounds[(cells[2], cells[3])] = (int(cells[11].replace(",", "")), int(cells[12].replace(",", "")))
    source = root / "zoo/wt500_fig3cfg/stokes/prosperity_count.cpp"
    binary = Path(tempfile.gettempdir()) / "fig12_prosperity_count"
    if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
        subprocess.run(["g++", "-O3", "-std=c++17", str(source), "-o", str(binary)], check=True)
    initial_cpu, initial_wall = cpu_seconds(), time.monotonic()
    reports = []
    mode = "a" if completed else "w"
    with output.open(mode, newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("capture", "layer", "sample", "R_p"))
        if mode == "w":
            writer.writeheader()
        for row in rows:
            key = (row["trace_dir"], row["layer"], 0)
            if key in completed:
                continue
            before = cpu_seconds()
            artifact = json.loads((manifest_path.parent / row["schedule_path"]).read_text())
            tile = prosperity.schedule_tile(row, artifact)
            trace_path = Path("/work/nvme/bebv/yyu9/input_trace_delta") / row["trace_relative_dir"] / (row["layer"] + ".npy")
            trace = np.load(trace_path, mmap_mode="r")
            with tempfile.TemporaryDirectory(prefix="fig12_prosperity_s0_") as temporary:
                sample_path = Path(temporary) / "sample0.npy"
                sample = np.ascontiguousarray(trace[:, :1])
                np.save(sample_path, sample)
                result = subprocess.check_output([str(binary), str(sample_path), "3", "3",
                                                  *[str(tile[k]) for k in ("HO", "WO", "CIN", "T", "COUT")]], text=True)
            values = result.splitlines()
            assert len(values) == 1, "helper must count sample 0 only"
            cout = row["workload"]["problem"]["COUT"]
            records = int(values[0]) * (cout // tile["COUT"])
            low, high = bounds[key[:2]]
            assert low <= records <= high, (key, records, low, high)
            if key in anchors:
                assert records == anchors[key], (key, records, anchors[key])
            # This check validates only accesses; output density is not used or emitted.
            counts = prosperity.count_sample(sample, 0, cout=cout, kernel=3, tile=tile, records=records, d_out=0.0)
            assert counts["A_p"] == records * tile["COUT"]
            writer.writerow({"capture": row["trace_relative_dir"], "layer": row["layer"], "sample": 0, "R_p": records})
            stream.flush()
            reports.append({"capture": row["trace_relative_dir"], "layer": row["layer"], "records": records,
                            "cpu_seconds": cpu_seconds() - before})
            print(json.dumps(reports[-1]), flush=True)
            if args.limit and len(reports) >= args.limit:
                break
            if cpu_seconds() - initial_cpu >= 1800:
                raise RuntimeError("login-node 30 CPU-minute budget exhausted; resume on Slurm")
    report = {"selected_3x3_pairs": len(rows), "completed_pairs": len(completed) + len(reports),
              "cpu_seconds": cpu_seconds() - initial_cpu, "wall_seconds": time.monotonic() - initial_wall,
              "worst_measured_pair_projection_cpu_seconds": max((r["cpu_seconds"] for r in reports), default=0) * len(rows),
              "pairs": reports}
    (here / ("prosperity_sample0_timing.json" if args.limit else "prosperity_sample0_validation.json")).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "pairs"}), flush=True)


if __name__ == "__main__":
    main()
