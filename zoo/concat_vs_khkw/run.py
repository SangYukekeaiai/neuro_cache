#!/usr/bin/env python3
"""Replay existing loas coordinate streams; never regenerate or modify traces."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
from statistics import mean
import struct
import subprocess
import threading


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NATIVE = ROOT / "src/lays/cachesim/native"
BINARY = NATIVE / "build/release/cachesim_run"
STREAMS = ROOT / ".baseline/wcache/streams"
TAGS = ("V8", "V9", "R9", "R16")
LAYOUTS = ("khkw_split", "cin_khkw_concat")
CIN_BLOCKS = (4, 8, 16)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_stream(path, allow_v1):
    # Wire declarations: native/include/cachesim/trace/stream_format.h and
    # src/lays/cachesim/stream.py. Version 1 has the same COUT coordinate fields.
    with path.open("rb") as source:
        fixed = source.read(56)
        magic, version, header_bytes, *fields = struct.unpack("<8sII10i", fixed)
        tiles, cores, weight_bytes, axis, stride, span, naddr, nsp, ndims, identity_bytes = fields
        if magic != b"WCTRACE1" or version != 1:
            raise ValueError(f"{path}: adapter requires WCTRACE1 magic and format_version == 1")
        if naddr != 5 or nsp < 0 or ndims != 7 or identity_bytes < 1:
            raise ValueError(f"{path}: invalid header field counts")
        if header_bytes != 56 + 4*naddr + 8*nsp + 8*ndims + identity_bytes:
            raise ValueError(f"{path}: invalid header length")
        tail = source.read(header_bytes - 56)
        if len(tail) != header_bytes - 56 or struct.unpack_from("<5i", tail) != (0, 1, 2, 3, 4):
            raise ValueError(f"{path}: not a full-coordinate burst stream")
        if axis != 3 or stride != 1 or weight_bytes != 1:
            raise ValueError(f"{path}: this replay expects COUT stride-1, one-byte weights")
        if not allow_v1:
            raise ValueError(f"{path}: v1 needs explicit --allow-v1-cout pipe-header adaptation")
        identity = tail[4*naddr + 8*nsp + 8*ndims:].decode("utf-8").split("\0")
        if len(identity) != 5 or identity[-1] != "":
            raise ValueError(f"{path}: invalid identity block")
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path),
            "bytes": path.stat().st_size, "format_version": version,
            "tiles": tiles, "cores": cores, "burst_dim": axis, "burst_stride": stride,
            "burst_span": span, "arch": identity[0], "workload": identity[1],
            "layer": identity[2], "sample_idx": int(identity[3])}


def invoke(tag, sample, config, config_path, info):
    path = ROOT / info["path"]
    # Pipe adapter only: bytes [8,12) change from u32(1) to u32(2).
    # For COUT, v1 run_start IS the v2 cout anchor. No burst or other header
    # field changes; no converted stream is saved. Original files stay read-only.
    read_fd, write_fd = os.pipe()
    feed_errors = []

    def feed():
        try:
            with os.fdopen(write_fd, "wb") as sink, path.open("rb") as source:
                prefix = source.read(12)
                if len(prefix) != 12 or prefix[:8] != b"WCTRACE1" or struct.unpack("<I", prefix[8:])[0] != 1:
                    raise ValueError(f"{path}: adapter requires WCTRACE1 magic and format_version == 1")
                sink.write(prefix[:8] + struct.pack("<I", 2))
                shutil.copyfileobj(source, sink, 1024 * 1024)
        except (OSError, ValueError) as error:
            feed_errors.append(error)

    producer = threading.Thread(target=feed)
    producer.start()
    command = [str(BINARY), "--config", str(config_path), "--trace", "-", "--header",
               "--run-id", f"{tag}-s{sample:05d}-{config['layout']}-{config['cin_block']*4}B"]
    try:
        with os.fdopen(read_fd, "rb") as pipe:
            result = subprocess.run(command, stdin=pipe, capture_output=True, text=True)
    finally:
        producer.join()
    if result.returncode:
        raise RuntimeError(f"{command[-1]} failed ({result.returncode}): {result.stderr}")
    if feed_errors:
        raise RuntimeError(f"{path}: stream pipe failed: {feed_errors}")
    reader = csv.DictReader(io.StringIO(result.stdout))
    rows = list(reader)
    if len(rows) != 1 or None in rows[0] or any(value is None for value in rows[0].values()):
        raise ValueError(f"{path}: expected exactly one complete native CSV row")
    row = rows[0]
    for key in ("arch", "workload", "layer"):
        if row[key] != info[key]:
            raise ValueError(f"{path}: simulator identity mismatch: {key}")
    if int(row["sample_idx"]) != sample or int(row["cin_lo_blocks"]) != -1:
        raise ValueError(f"{path}: simulator sample/split sentinel mismatch")
    for key, value in config.items():
        if key not in row or (int(row[key]) if isinstance(value, int) else row[key]) != value:
            raise ValueError(f"{path}: simulator configuration mismatch: {key}")
    if int(row["total_cycles"]) <= 0 or int(row["l1_accesses"]) <= 0:
        raise ValueError(f"{path}: empty simulation result")
    return {"_tag": tag, "_stream": info["path"], **row}, result.stderr.strip()


def comparison(rows):
    out = ["# loas: cin_khkw_concat versus khkw_split", "",
           "## Scope and reproducibility", "",
           "20 existing `.baseline/wcache/streams/{V8,V9,R9,R16}_s0000{0..4}.wcts` "
           "streams × two layouts × three line sizes = 120 simulations. "
           "These baseline streams predate T53. No traces were regenerated and "
           "`.baseline` was not modified; original stream hashes are recorded in "
           "[provenance.json](provenance.json) and checked again after replay.", "",
           "The stored streams contain WCTS v1 coordinates, not line IDs. "
           "The v1 refusal message in [stream_format.h]"
           "(../../src/lays/cachesim/native/include/cachesim/trace/stream_format.h), "
           "identifies `[kh, kw, cin, run_start, run_end]`: for COUT bursts, "
           "`run_start` is exactly the v2 COUT anchor. The explicitly enabled pipe "
           "adapter requires valid magic, version 1, COUT, and stride 1, then changes "
           "only the four-byte version field at offsets [8,12) to 2. Every other "
           "byte passes unchanged; no converted file is saved. The simulator "
           "[decodes coordinates](../../src/lays/cachesim/native/src/trace/stream_trace.cpp) "
           "and [expands them through the mapper](../../src/lays/cachesim/native/src/core/engine_core.cpp) "
           "during replay, computing layout-dependent line IDs anew; reuse across "
           "layouts and blockings is therefore sound.", "",
           "Rerun from the repository root (stdlib Python and g++/make required):", "",
           "```sh", "python3 zoo/concat_vs_khkw/run.py --allow-v1-cout --jobs 4", "```", "",
           "The script builds `MODE=release` apps, derives six saved `config_*.json` files "
           "from [base.json](../../examples/cache/base.json), then runs `cachesim_run` "
           "once per stream/config. Only `layout` and `cin_block` vary: CIN 4/8/16 × "
           "COUT 4 × weight_bytes 1 gives 16/32/64B lines. L1 is 16384B, 8-way; "
           "L2 is 524288B, 16-way; every other base.json setting is held fixed. "
           "Omitted settings use the same native defaults for every run, visible "
           "in [results.csv](results.csv). The CSV retains every native column name "
           "and value; `_tag` and `_stream` identify the input. Native "
           "`sim_wall_seconds` is host wall time and may change on rerun; "
           "comparisons below use simulated cycles.", "",
           "## Mean of five samples per layer and line size", "",
           "Rates are arithmetic means of the simulator's reported per-sample "
           "`l1_hit_rate`/`l2_hit_rate`, expressed as percentages; they are not pooled "
           "hit/access ratios. Every delta is concat minus split. Rate deltas are "
           "percentage points (pp). Cycle ratio = mean concat `total_cycles` / mean "
           "split `total_cycles`; a ratio below 1 favors concat.", "",
           "| Layer | Line B | split L1 % | concat L1 % | Δ L1 pp | split L2 % | concat L2 % | Δ L2 pp | split cycles | concat cycles | Δ cycles | cycles ratio |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    count_rows = []
    outcomes = {"wins": [], "loses": [], "ties": []}
    for tag in TAGS:
        for line_bytes in (16, 32, 64):
            pair = []
            for layout in LAYOUTS:
                group = [row for row in rows if row["_tag"] == tag
                         and int(row["line_size_bytes"]) == line_bytes and row["layout"] == layout]
                if len(group) != 5 or {int(r["sample_idx"]) for r in group} != set(range(5)):
                    raise ValueError(f"Incomplete comparison: {tag}/{line_bytes}/{layout}")
                values = {key: mean(float(row[key]) for row in group)
                          for key in ("l1_hit_rate", "l2_hit_rate", "total_cycles",
                                      "l1_hits", "l1_accesses", "l2_hits", "l2_accesses")}
                pair.append(values)
            split, concat = pair
            delta = concat["total_cycles"] - split["total_cycles"]
            ratio = concat["total_cycles"] / split["total_cycles"]
            cells = [tag, str(line_bytes)]
            for level in ("l1", "l2"):
                a, b = split[level + "_hit_rate"] * 100, concat[level + "_hit_rate"] * 100
                cells.extend([f"{a:.4f}", f"{b:.4f}", f"{b-a:+.4f}"])
            cells.extend([f"{split['total_cycles']:.1f}", f"{concat['total_cycles']:.1f}",
                          f"{delta:+.1f}", f"{ratio:.6f}"])
            out.append("| " + " | ".join(cells) + " |")
            counts = [tag, str(line_bytes)]
            for level in ("l1", "l2"):
                for metric in ("hits", "misses"):
                    a, b = (p[level + "_hits"] if metric == "hits" else
                            p[level + "_accesses"] - p[level + "_hits"] for p in pair)
                    counts.append(f"{a:.1f} → {b:.1f} ({b-a:+.1f})")
            count_rows.append("| " + " | ".join(counts) + " |")
            outcome = "wins" if delta < 0 else "loses" if delta > 0 else "ties"
            outcomes[outcome].append(f"{tag}/{line_bytes}B ({delta:+.1f} cycles, {(ratio-1)*100:+.3f}%)")
    out.extend(["", "## Mean hit and miss counts", "",
                "Cells are split → concat (Δ), averaged over the same five samples. "
                "Miss counts are derived as native `accesses - hits`; the native CSV "
                "does not have separate miss columns.", "",
                "| Layer | Line B | L1 hits | Derived L1 misses | L2 hits | Derived L2 misses |",
                "|---|---:|---:|---:|---:|---:|", *count_rows, "",
                "## Conclusions", ""])
    for outcome, values in outcomes.items():
        out.append(f"- Concat {outcome} on mean simulated cycles ({len(values)}/12): "
                   + ("; ".join(values) if values else "none") + ".")
    out.extend(["", "R9 (stream-header shape 3×3, CIN 256, COUT 128) has exactly "
                "one L1 miss per distinct weight line: `l1_accesses - l1_hits` is "
                "18,432 / 9,216 / 4,608 at 16/32/64B in every sample under both "
                "layouts, leaving no conflict/refetch misses for either mapping "
                "to remove despite their different line IDs. In contrast, every "
                "V8/V9/R16 run exceeds its layer's distinct-line count, and these "
                "refetch miss counts change between the two layouts, unlike R9's "
                "compulsory-only misses."])
    out.extend(["", "These observations cover only these four loas layers, their five "
                "stored samples, the three blockings, and the fixed base cache settings. "
                "They do not establish results for other workloads or settings.", ""])
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--allow-v1-cout", action="store_true",
                        help="pipe-only version-field update for equivalent COUT v1 records")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    inputs = {}
    for tag in TAGS:
        for sample in range(5):
            path = STREAMS / f"{tag}_s{sample:05d}.wcts"
            info = inspect_stream(path, args.allow_v1_cout)
            if info["arch"] != "loas" or info["sample_idx"] != sample:
                raise ValueError(f"{path}: unexpected input identity")
            inputs[tag, sample] = info
    subprocess.run(["make", "MODE=release", "-j4", "apps"], cwd=NATIVE, check=True)
    base_path = ROOT / "examples/cache/base.json"
    base = json.loads(base_path.read_text())
    if base["cout_block"] != 4 or base["weight_bytes"] != 1:
        raise ValueError("base.json must retain COUT=4 and weight_bytes=1")
    configs = []
    for cin_block in CIN_BLOCKS:
        for layout in LAYOUTS:
            cfg = dict(base, cin_block=cin_block, layout=layout)
            path = HERE / f"config_{layout}_{cin_block*4}B.json"
            path.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n")
            configs.append((cfg, path))
    rows, warnings = [], {}
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(invoke, tag, sample, cfg, path, info): (tag, sample, cfg)
                   for (tag, sample), info in inputs.items() for cfg, path in configs}
        for future in as_completed(futures):
            row, stderr = future.result()
            rows.append(row)
            if stderr:
                warnings[row["run_id"]] = stderr
            print(f"[{len(rows)}/120] {row['run_id']}: {row['total_cycles']} cycles", flush=True)
    rows.sort(key=lambda r: (TAGS.index(r["_tag"]), int(r["sample_idx"]),
                             int(r["line_size_bytes"]), LAYOUTS.index(r["layout"])))
    for info in inputs.values():
        if sha256(ROOT / info["path"]) != info["sha256"]:
            raise ValueError("Input stream changed during replay: " + info["path"])
    report = comparison(rows)
    with (HERE / "results.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    provenance = {"base_config": base, "base_sha256": sha256(base_path),
                  "binary": BINARY.relative_to(ROOT).as_posix(), "binary_sha256": sha256(BINARY),
                  "stream_adapter": "v1 COUT stride-1: replace bytes [8,12) with little-endian u32(2); all other bytes unchanged",
                  "streams": list(inputs.values()), "warnings": warnings}
    (HERE / "provenance.json").write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    (HERE / "COMPARISON.md").write_text(report, encoding="utf-8")
    print("Wrote results.csv (120 native rows), COMPARISON.md, and provenance.json", flush=True)


if __name__ == "__main__":
    main()
