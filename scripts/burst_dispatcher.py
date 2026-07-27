#!/usr/bin/env python3
"""Opportunistically dispatch weight-trace combos onto Delta's GPU
*-interactive partitions whenever they have real free capacity right now.

Batch partitions (gpuA100x4, gpuA40x4, gpuA100x8, gpuH200x8) were seeing
15-28h estimated queue waits; the -interactive variants get separate,
faster scheduling (1h MaxTime each) and empirically had free slots when
the batch partitions did not. This probes them the same way that was
verified by hand: submit the real burst job via sbatch (no --immediate
flag on this Slurm version, so this IS the test), check after ~12s
whether it actually started RUNNING, and cancel-and-try-the-next-config
if not.

This script is the SOLE authority for whether a combo needs a job right
now -- it does not trust a job to resubmit itself. `run_burst_interactive.
slurm` still has a best-effort self-resubmit for the case where a combo
finishes within one burst window (harmless, saves a dispatcher cycle),
but that resubmit line sits after the python3 call, and when Slurm's
1h MaxTime kills a job, it tears down the WHOLE job -- wrapping bash
script included, not just the Python subprocess -- so the resubmit code
never runs on a TIMEOUT (confirmed: every combo's burst chain went
silent once its first TIMEOUT hit, 2026-07-21 ~19:15-20:02). Re-dispatch
must therefore be driven from outside the killable job, on a timer, by
checking ground truth (samples on disk + live squeue state) -- which is
what this script does every pass, not just for combos it has never
touched.

One (re)dispatch per invocation (not a burst of many at once, to avoid
spamming the scheduler); run this on a timer (see the wrapping loop) to
keep probing as capacity opens/closes and chains die/finish over time.

State:
  outputs/schedules/burst_complete.txt -- combos confirmed at
    10000/10000 samples; never re-checked or re-dispatched once here
    (avoids re-globbing a 10000-file directory every pass).
  outputs/schedules/burst_jobs.csv -- arch,trace_dir,layer,job_id for the
    most recently dispatched job per combo, so this script can tell
    "already has a live job" (skip) from "chain died, needs redispatch"
    (eligible) via a real squeue lookup, not assumed state.
"""

from __future__ import annotations

import csv
import pathlib
import subprocess
import time

PROJECT_ROOT = pathlib.Path("/u/yyu9/projects/neuro_cache")
JOBS_FILE = PROJECT_ROOT / "outputs/schedules/jobs.txt"
COMPLETE_FILE = PROJECT_ROOT / "outputs/schedules/burst_complete.txt"
JOBS_STATE_FILE = PROJECT_ROOT / "outputs/schedules/burst_jobs.csv"
BURST_SCRIPT = "scripts/slurm/run_burst_interactive.slurm"
OUT_DIR = pathlib.Path("/work/hdd/bebv/yyu9/neuro_cache_outputs/weight_traces")
TARGET_SAMPLES = 10000

# Already running via the very first manual burst, before this script's
# job-state tracking existed -- treated as a live job with unknown ID;
# left alone here, its own self-resubmit chain (or a manual check) covers it.
ALREADY_RUNNING = {("gustavsnn", "resnet19_T4_all", "layer_19_layer3_1_conv2")}

# (partition, mem_per_core_GB, [core counts to try, largest first])
# Cost-ordered cheapest-first (TRESBillingWeights CPU rate): MI100x8 (31.25),
# A40x4 (62.5), A100x4 (125), A100x8 (187.5), H200x8 (500).
PARTITIONS = [
    ("gpuMI100x8-interactive", 1, [96, 64, 32, 16]),
    ("gpuA40x4-interactive", 3, [48, 32, 16, 8]),
    ("gpuA100x4-interactive", 3, [48, 32, 16, 8]),
    ("gpuA100x8-interactive", 1, [96, 64, 32, 16]),
    ("gpuH200x8-interactive", 1, [72, 48, 24, 8]),
]

PROBE_WAIT_S = 12


def load_combos() -> list[tuple[str, str, str]]:
    with open(JOBS_FILE, newline="") as fh:
        return [tuple(row) for row in csv.reader(fh) if row]


def load_complete() -> set[tuple[str, str, str]]:
    if not COMPLETE_FILE.exists():
        return set()
    with open(COMPLETE_FILE, newline="") as fh:
        return {tuple(row) for row in csv.reader(fh) if row}


def record_complete(combo: tuple[str, str, str]) -> None:
    with open(COMPLETE_FILE, "a", newline="") as fh:
        csv.writer(fh).writerow(combo)


def load_job_state() -> dict[tuple[str, str, str], str]:
    if not JOBS_STATE_FILE.exists():
        return {}
    with open(JOBS_STATE_FILE, newline="") as fh:
        return {(r[0], r[1], r[2]): r[3] for r in csv.reader(fh) if r}


def save_job_state(state: dict[tuple[str, str, str], str]) -> None:
    with open(JOBS_STATE_FILE, "w", newline="") as fh:
        writer = csv.writer(fh)
        for (arch, trace_dir, layer), job_id in state.items():
            writer.writerow([arch, trace_dir, layer, job_id])


def sample_count(combo: tuple[str, str, str]) -> int:
    arch, trace_dir, layer = combo
    d = OUT_DIR / arch / trace_dir / layer
    if not d.exists():
        return 0
    return sum(1 for _ in d.glob("sample_*.json.gz"))


def job_is_live(job_id: str) -> bool:
    if not job_id:
        return False
    out = subprocess.run(
        ["squeue", "-j", job_id, "-h", "-o", "%T"],
        capture_output=True, text=True,
    ).stdout.strip()
    return out in ("PENDING", "RUNNING")


def next_combo(all_combos, complete, job_state) -> tuple[str, str, str] | None:
    """Eligible = not yet confirmed complete AND has no currently-live job.
    Among eligible combos, picks from whichever arch has the FEWEST
    complete-or-live combos so far (keeps all 5 archs progressing
    together instead of one arch hogging every dispatch), then biases
    toward the END of that arch's layer list (the queued full-arch
    arrays start from index 0, so the opposite end reduces, without
    guaranteeing, overlap with them once they start).
    """
    by_arch: dict[str, list[tuple[str, str, str]]] = {}
    for combo in all_combos:
        by_arch.setdefault(combo[0], []).append(combo)

    def progressed_count(arch: str) -> int:
        n = 0
        for c in by_arch[arch]:
            if c in complete or c in ALREADY_RUNNING:
                n += 1
            elif job_is_live(job_state.get(c, "")):
                n += 1
        return n

    for arch in sorted(by_arch, key=progressed_count):
        for combo in reversed(by_arch[arch]):
            if combo in complete or combo in ALREADY_RUNNING:
                continue
            if job_is_live(job_state.get(combo, "")):
                continue
            return combo
    return None


def try_dispatch(combo: tuple[str, str, str]) -> str | None:
    """Returns the live job_id on success, None if nothing landed immediately."""
    arch, trace_dir, layer = combo
    for partition, mem_per_core, core_options in PARTITIONS:
        for cores in core_options:
            mem = f"{cores * mem_per_core}G"
            job_name = f"weight_trace_burst_{arch}"
            cmd = [
                "sbatch", "--parsable",
                f"--partition={partition}",
                f"--cpus-per-task={cores}",
                f"--mem={mem}",
                f"--job-name={job_name}",
                BURST_SCRIPT, arch, trace_dir, layer,
            ]
            result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"  submit failed on {partition}@{cores}c: {result.stderr.strip()}")
                continue
            job_id = result.stdout.strip()
            time.sleep(PROBE_WAIT_S)
            state = subprocess.run(
                ["squeue", "-j", job_id, "-h", "-o", "%T"],
                capture_output=True, text=True,
            ).stdout.strip()
            if state == "RUNNING":
                print(f"  DISPATCHED {arch}/{trace_dir}/{layer} -> {partition}@{cores}c (job {job_id})")
                return job_id
            subprocess.run(["scancel", job_id], capture_output=True)
            print(f"  {partition}@{cores}c: not immediate (state={state or 'gone'}), cancelled job {job_id}")
    return None


def main() -> int:
    all_combos = load_combos()
    complete = load_complete()
    job_state = load_job_state()

    # Ground-truth sweep: anything not yet known-complete gets its disk
    # count checked; newly-complete combos get recorded once and never
    # re-globbed again.
    for combo in all_combos:
        if combo in complete:
            continue
        if sample_count(combo) >= TARGET_SAMPLES:
            record_complete(combo)
            complete.add(combo)
            job_state.pop(combo, None)
            print(f"  newly complete: {'/'.join(combo)}")

    combo = next_combo(all_combos, complete, job_state)
    if combo is None:
        print("No eligible combos right now (all complete or all have live jobs).")
        save_job_state(job_state)
        return 0

    print(f"Probing partitions for {'/'.join(combo)} ...")
    job_id = try_dispatch(combo)
    if job_id:
        job_state[combo] = job_id
    else:
        print(f"  no immediate capacity anywhere for {'/'.join(combo)} this pass")
    save_job_state(job_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
