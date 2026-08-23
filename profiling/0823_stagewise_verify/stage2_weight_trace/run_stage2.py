#!/usr/bin/env python3
"""Stage 2 of the 2026-08-23 stagewise verification: weight-trace generation.

Loads the Stage 1 schedules (no re-solving, no Gurobi), reconstructs the five
committed sample images against them through the LoAS native bridge, and
reports what the input spikes and the emitted weight trace actually contain.

Everything this stage reads is copied into inputs/ first, and everything it
produces lands in outputs/. Stage 3's inputs are not prepared here.

    conda run -n base python profiling/0823_stagewise_verify/stage2_weight_trace/run_stage2.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import time

import numpy as np

STAGE = pathlib.Path(__file__).resolve().parent
ROOT = STAGE.parents[2]
IN, OUT = STAGE / "inputs", STAGE / "outputs"
STAGE1 = STAGE.parent / "stage1_mip_solver"

sys.path.insert(0, str(ROOT / "src"))
import tracegen  # noqa: E402

ARCH = "loas"
COMBO_TAG = "noc2MiB_node32kb"
GENERATOR = ROOT / "scripts/generate_weight_traces.py"
SRC_TRACE_ROOT = ROOT / "input_trace/loas"
BRIDGE = ROOT / "src/archmodels/loas/loasgen"

# (stage-1 trace_dir, stage-2 trace_dir, layer)
COMBOS = [
    ("vgg16_T4_all", "vgg16_T4_n5", "layer_09_features_30"),
    ("resnet19_T4_all", "resnet19_T4_n5", "layer_16_layer3_0_conv2"),
]
SAMPLE_START, SAMPLE_COUNT = 0, 5


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def stage_inputs() -> dict:
    """Copy Stage 1's schedules and the two spike traces into inputs/."""
    sched_root = IN / "schedules" / ARCH
    trace_root = IN / "input_trace"
    manifest = {"stage": "2_weight_trace", "arch": ARCH, "combo_tag": COMBO_TAG,
                "schedules": {}, "input_traces": {}, "samples": {}}

    for src_dir, dst_dir, layer in COMBOS:
        src = STAGE1 / "outputs/schedules/pe16" / ARCH / src_dir / f"{layer}.json"
        dst = sched_root / dst_dir / f"{layer}.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        doc = json.loads(src.read_text())
        # The schedule is shape-derived, so it transfers to the 5-sample subset
        # unchanged; only the recorded directory name needs to follow.
        doc["trace_dir"] = dst_dir
        dst.write_text(json.dumps(doc, indent=1) + "\n")
        manifest["schedules"][f"{dst_dir}/{layer}"] = {
            "path": str(dst.relative_to(STAGE)),
            "from": str(src.relative_to(ROOT)),
            "trace_dir_rewritten_from": src_dir,
            "dram_num_steps": doc["dram_num_steps"],
            "mode": doc["mode"],
            "noc_spatial": doc["result"]["strategy"]["NoCLevel"]["spatial_splitting"]["order"],
            "noc_temporal": doc["result"]["strategy"]["NoCLevel"]["temporal_permutation"]["order"],
            "dram_temporal": doc["result"]["strategy"]["DRAM"]["temporal_permutation"]["order"],
            "sha256_16": sha(dst),
        }

        # Only the two .npy files this stage reads, plus their meta.json.
        sm = trace_root / dst_dir
        sm.mkdir(parents=True, exist_ok=True)
        meta_src = SRC_TRACE_ROOT / dst_dir / "meta.json"
        npy_src = SRC_TRACE_ROOT / dst_dir / f"{layer}.npy"
        shutil.copy2(meta_src, sm / "meta.json")
        shutil.copy2(npy_src, sm / f"{layer}.npy")
        meta = json.loads((sm / "meta.json").read_text())
        arr = np.load(sm / f"{layer}.npy", mmap_mode="r")
        manifest["input_traces"][f"{dst_dir}/{layer}"] = {
            "npy": str((sm / f"{layer}.npy").relative_to(STAGE)),
            "from": str(npy_src.relative_to(ROOT)),
            "shape_T_B_Cin_Hin_Win": list(arr.shape),
            "dtype": str(arr.dtype), "bytes": int(arr.nbytes),
            "sha256_16": sha(sm / f"{layer}.npy"),
        }
        manifest["samples"][dst_dir] = {
            "array_indices": list(range(SAMPLE_START, SAMPLE_START + SAMPLE_COUNT)),
            "cifar10_indices": meta["subset"]["sample_indices"],
            "selected_by": meta["subset"]["selected_by"],
            "seed": meta["subset"]["seed"],
        }

    manifest["bridge"] = {
        "binary": str(BRIDGE.relative_to(ROOT)),
        "built": time.strftime("%Y-%m-%d %H:%M", time.localtime(BRIDGE.stat().st_mtime)),
        "sha256_16": sha(BRIDGE),
    }
    manifest["generator"] = {
        "script": str(GENERATOR.relative_to(ROOT)),
        "sample_start": SAMPLE_START, "sample_count": SAMPLE_COUNT, "workers": 1,
    }
    (IN / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def run_generator(dst_dir: str, layer: str, extra: list, tag: str,
                  binary_stdout: bool = False) -> float:
    cmd = [sys.executable, str(GENERATOR),
           "--arch", ARCH,
           "--trace-root", str(IN / "input_trace"),
           "--trace-dir", dst_dir,
           "--layer", layer,
           "--schedule-cache", str(IN / "schedules"),
           "--workers", "1"] + extra
    env = {**dict(__import__("os").environ), "PYTHONPATH": str(ROOT / "src")}
    t0 = time.time()
    if binary_stdout:
        # --stream writes raw WCTS bytes to stdout; the dump file is the copy
        # we keep, so stdout is discarded rather than decoded as text.
        r = subprocess.run(cmd, cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, text=True)
        out_text = "<binary WCTS stream, discarded; see the .wcts dump>"
    else:
        r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
        out_text = r.stdout
    dt = time.time() - t0
    (OUT / "logs" / f"{tag}.log").write_text(
        "$ " + " ".join(cmd) + "\n\n--- stdout ---\n" + out_text +
        "\n--- stderr ---\n" + (r.stderr or ""))
    if r.returncode != 0:
        raise RuntimeError(f"{tag} failed rc={r.returncode}\n{r.stderr[-2000:]}")
    return dt


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------
def input_trace_stats(npy: pathlib.Path, n_samples: int) -> list:
    """Per-sample spike statistics of the raw input tensor [T, B, Cin, Hin, Win]."""
    arr = np.load(npy, mmap_mode="r")
    T, _B, Cin, Hin, Win = arr.shape
    rows = []
    for s in range(n_samples):
        a = np.asarray(arr[:, s])                      # [T, Cin, Hin, Win]
        spikes = int(a.sum())
        elems = T * Cin * Hin * Win
        # A channel is silent when it never fires at any (t, hin, win).
        per_channel = a.sum(axis=(0, 2, 3))            # [Cin]
        silent = int((per_channel == 0).sum())
        # A (cin, hin, win) site is silent when it never fires across T; this
        # is the quantity LoASGen.h:81-89 actually tests.
        per_site = a.sum(axis=0)                       # [Cin, Hin, Win]
        silent_sites = int((per_site == 0).sum())
        rows.append({
            "sample": s, "spikes": spikes, "elements": elems,
            "density": spikes / elems,
            "silent_channels": silent, "channels": Cin,
            "silent_sites": silent_sites, "sites": Cin * Hin * Win,
            "site_fire_rate": 1.0 - silent_sites / (Cin * Hin * Win),
        })
    return rows


def weight_trace_stats(path: pathlib.Path, kh: int, kw: int, cin: int) -> dict:
    """Per-sample statistics of one generated weight trace.

    A LayerWeightTrace tile is one (dram_i, noc_i) pair with every core merged
    inside it, so len(tiles) == dram_num_steps * noc_num_steps. The
    NodeTileSpec list the reconstruction walked is larger by the core count.
    """
    with gzip.open(path, "rt") as fh:
        doc = json.load(fh)
    tiles = doc["tiles"]
    ceiling = kh * kw * cin          # rows one core could emit for one tile
    rows_per_tile, rows_per_core, cores_per_tile, ticks_per_tile = [], [], [], []
    total_rows = 0
    for t in tiles:
        n_tile = 0
        seen_cores = set()
        for tick in t["ticks"]:
            for core in tick["cores"]:
                seen_cores.add(core["core_id"])
                n_tile += len(core["weight_addresses"])
        rows_per_tile.append(n_tile)
        cores_per_tile.append(len(seen_cores))
        ticks_per_tile.append(len(t["ticks"]))
        if seen_cores:
            rows_per_core.append(n_tile / len(seen_cores))
        total_rows += n_tile
    n = len(tiles)
    return {
        "tiles": n,
        "cores_per_tile_min": min(cores_per_tile) if n else 0,
        "cores_per_tile_max": max(cores_per_tile) if n else 0,
        "ticks_per_tile_min": min(ticks_per_tile) if n else 0,
        "ticks_per_tile_max": max(ticks_per_tile) if n else 0,
        "total_rows": total_rows,
        "rows_per_tile_min": min(rows_per_tile) if n else 0,
        "rows_per_tile_max": max(rows_per_tile) if n else 0,
        "rows_per_tile_mean": (total_rows / n) if n else 0.0,
        "rows_per_core_mean": (sum(rows_per_core) / len(rows_per_core)) if rows_per_core else 0.0,
        "per_core_ceiling_KHxKWxCIN": ceiling,
        "emitted_over_possible": (
            (sum(rows_per_core) / len(rows_per_core)) / ceiling) if rows_per_core else 0.0,
        "mac_cycles_total": sum(t.get("mac_cycles", 0) for t in tiles),
        "dram_num_steps": doc["dram_num_steps"],
        "noc_num_steps": doc["noc_num_steps"],
        "file_bytes": path.stat().st_size,
    }


def main() -> int:
    for d in ["logs", "weight_traces", "stream"]:
        (OUT / d).mkdir(parents=True, exist_ok=True)
    manifest = stage_inputs()
    print("inputs staged\n", flush=True)

    report = {"combos": {}}
    for _src, dst_dir, layer in COMBOS:
        key = f"{dst_dir}/{layer}"
        print(f"=== {key}", flush=True)

        # Pass A: the five sample_NNNNN.json.gz artifacts.
        dt = run_generator(dst_dir, layer, [
            "--out-dir", str(OUT / "weight_traces"),
            "--combo-tag", COMBO_TAG,
            "--sample-start", str(SAMPLE_START),
            "--sample-count", str(SAMPLE_COUNT),
        ], tag=f"passA_{layer}")
        print(f"  pass A: 5 samples in {dt:.1f}s", flush=True)

        # Pass B: the raw WCTS stream, full for sample 0 plus a 4-tile excerpt.
        dt_full = run_generator(dst_dir, layer, [
            "--stream", "--sample-start", "0", "--sample-count", "1",
            "--dump-trace", str(OUT / "stream" / f"{layer}_s00000.wcts"),
        ], tag=f"passB_full_{layer}", binary_stdout=True)
        dt_short = run_generator(dst_dir, layer, [
            "--stream", "--sample-start", "0", "--sample-count", "1",
            "--dump-trace", str(OUT / "stream" / f"{layer}_s00000_first4tiles.wcts"),
            "--dump-trace-tiles", "4",
        ], tag=f"passB_short_{layer}", binary_stdout=True)
        print(f"  pass B: stream dumped in {dt_full:.1f}s / {dt_short:.1f}s", flush=True)

        # Statistics.
        npy = IN / "input_trace" / dst_dir / f"{layer}.npy"
        in_stats = input_trace_stats(npy, SAMPLE_COUNT)

        sched = json.loads((IN / "schedules" / ARCH / dst_dir / f"{layer}.json").read_text())
        p = sched["workload"]["problem"]
        layer_out = OUT / "weight_traces" / ARCH / COMBO_TAG / dst_dir / layer
        wt_stats = []
        for s in range(SAMPLE_START, SAMPLE_START + SAMPLE_COUNT):
            wt_stats.append({"sample": s, **weight_trace_stats(
                layer_out / f"sample_{s:05d}.json.gz", p["KH"], p["KW"], p["CIN"])})

        report["combos"][key] = {
            "problem": p,
            "dram_num_steps": sched["dram_num_steps"],
            "cifar10_indices": manifest["samples"][dst_dir]["cifar10_indices"],
            "input_trace": in_stats,
            "weight_trace": wt_stats,
            "stream_bytes_full": (OUT / "stream" / f"{layer}_s00000.wcts").stat().st_size,
            "stream_bytes_first4": (OUT / "stream" / f"{layer}_s00000_first4tiles.wcts").stat().st_size,
        }
        for a, b in zip(in_stats, wt_stats):
            print(f"  s{a['sample']}  spikes={a['spikes']:>6} dens={a['density']:.4f} "
                  f"silent_ch={a['silent_channels']:>3}/{a['channels']}  "
                  f"tiles={b['tiles']:>5} rows={b['total_rows']:>8} "
                  f"rows/tile={b['rows_per_tile_mean']:.1f} "
                  f"emit={b['emitted_over_possible']:.4f}", flush=True)
        print(flush=True)

    (OUT / "stage2_report.json").write_text(json.dumps(report, indent=1) + "\n")
    print("wrote", OUT / "stage2_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
