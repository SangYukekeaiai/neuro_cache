#!/usr/bin/env python3
"""Write outputs/schedules/jobs.txt: one line per successfully-solved
(arch, trace_dir, layer) from outputs/schedules/summary.csv, in
`arch,trace_dir,layer` order. A Slurm array script indexes into this file
via `sed -n "$((SLURM_ARRAY_TASK_ID+1))p"` instead of re-deriving the
155-combo list (or its arithmetic) inside the sbatch script itself.
"""

from __future__ import annotations

import csv
import pathlib

SUMMARY_PATH = pathlib.Path("outputs/schedules/summary.csv")
JOBS_PATH = pathlib.Path("outputs/schedules/jobs.txt")


def main() -> int:
    rows = []
    with open(SUMMARY_PATH, newline="") as fh:
        for row in csv.DictReader(fh):
            if row["status"] == "OK":
                rows.append((row["arch"], row["trace_dir"], row["layer"]))

    with open(JOBS_PATH, "w") as fh:
        for arch, trace_dir, layer in rows:
            fh.write(f"{arch},{trace_dir},{layer}\n")

    print(f"Wrote {len(rows)} combo(s) to {JOBS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
