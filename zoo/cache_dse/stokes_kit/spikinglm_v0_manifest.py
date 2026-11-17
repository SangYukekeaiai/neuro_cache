#!/usr/bin/env python3
"""Build the T74 spikinglm V0-only cachesim manifest (72 layers x 10 samples).

Mirrors make_sweep_manifest.py for the spikinglm trace drop, whose receipts
live flat at receipts/s<SSS>_<layer>.json with fields
{layer, sample, wcts_sha256, schedule_sha256, bytes} (no status/records).
Every WCTS trailer and receipt digest is validated here, and the gate
receipt is written by this script after those checks pass: this manifest
carries exactly one variant (V0), so the sweep-level gates of run_gates.py
(baseline identity, cross-variant geometry) do not apply.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))
from make_sweep_manifest import BASE_CONFIG, atomic_json, digest, load_json, trailer  # noqa: E402

REPO_DEFAULT = KIT.parents[2]
ARCH = "loas"
WORKLOAD = "spikinglm_t4_T4_n500"
SAMPLE_COUNT = 10


def validate_traces(trace_root: Path, layers: list[str]) -> list[dict]:
    traces = []
    for sample in range(SAMPLE_COUNT):
        for layer_index, layer in enumerate(layers):
            wcts = trace_root / "wcts" / f"sample_{sample:03d}" / f"{layer}.wcts"
            receipt_path = trace_root / "receipts" / f"s{sample:03d}_{layer}.json"
            if not wcts.is_file() or not receipt_path.is_file():
                raise SystemExit(f"missing trace or receipt: {wcts}")
            _, records = trailer(wcts)
            receipt = load_json(receipt_path)
            wcts_sha = digest(wcts)
            if receipt.get("wcts_sha256") != wcts_sha:
                raise SystemExit(f"trace digest differs from receipt: {wcts}")
            if receipt.get("sample") != sample or receipt.get("layer") != layer:
                raise SystemExit(f"trace identity differs from receipt: {receipt_path}")
            if receipt.get("bytes") != wcts.stat().st_size:
                raise SystemExit(f"trace size differs from receipt: {wcts}")
            traces.append({
                "trace_index": len(traces), "sample": sample,
                "sample_name": f"sample_{sample:03d}", "layer_index": layer_index,
                "layer": layer, "path": str(wcts.resolve()), "sha256": wcts_sha,
                "records": records, "schedule_sha256": receipt.get("schedule_sha256"),
            })
    return traces


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(REPO_DEFAULT))
    parser.add_argument("--trace-root", required=True)
    parser.add_argument("--output-root")
    parser.add_argument("--binary")
    args = parser.parse_args()
    repo = Path(args.repo).expanduser().resolve()
    trace_root = Path(args.trace_root).expanduser().resolve()
    output_root = Path(args.output_root or trace_root / "cache_dse_v0").expanduser().resolve()
    binary = Path(args.binary or repo / "zoo/fig12_edp/demo/native_build/cachesim_run").expanduser().resolve()
    if not binary.is_file():
        raise SystemExit(f"cachesim binary is missing: {binary}")

    layers_file = trace_root / "layers.txt"
    layers = [line.strip() for line in layers_file.read_text().splitlines() if line.strip()]
    if len(layers) != 72:
        raise SystemExit(f"expected 72 layers in {layers_file}, found {len(layers)}")

    # V0 is BASE_CONFIG verbatim; reuse the committed config file.
    config_path = KIT / "configs" / "V0.json"
    if json.loads(config_path.read_text()) != BASE_CONFIG:
        raise SystemExit(f"configs/V0.json no longer matches BASE_CONFIG: {config_path}")
    configs = [{
        "id": "V0", "label": "cacheA", "short_label": "cacheA\n(V0)",
        "group": "base", "belady": False, "changes": {}, "removed": [],
        "config_path": str(config_path.resolve()), "config_sha256": digest(config_path),
        "l1_size_bytes": BASE_CONFIG["l1_size_bytes"],
        "l2_size_bytes": BASE_CONFIG["l2_size_bytes"],
    }]

    traces = validate_traces(trace_root, layers)
    cases = [{
        "case_index": i, "variant": "V0",
        "sample": t["sample"], "sample_name": t["sample_name"],
        "layer_index": t["layer_index"], "layer": t["layer"],
        "trace_index": t["trace_index"], "trace_path": t["path"],
        "trace_sha256": t["sha256"], "schedule_sha256": t["schedule_sha256"],
    } for i, t in enumerate(traces)]

    manifest = {
        "schema": "stokes_cache_dse_manifest/v1",
        "repo": str(repo),
        "benchmark": {"arch": ARCH, "workload": WORKLOAD, "layers": layers,
                      "sample_count": SAMPLE_COUNT, "layer_count": len(layers)},
        "trace_root": str(trace_root), "output_root": str(output_root),
        "binary": str(binary), "binary_sha256": digest(binary),
        "source_hashes": {"spikinglm_v0_manifest_sha256": digest(Path(__file__).resolve())},
        "config_count": 1, "trace_count": len(traces), "case_count": len(cases),
        "expected_rows": len(cases), "expected_variants": ["V0"],
        "configs": configs, "traces": traces, "cases": cases,
        "gates_path": str(output_root / "gates" / "gates.json"),
        "raw_root": str(output_root / "raw"), "oracle_root": str(output_root / "oracles"),
        "prepass_root": str(output_root / "prepass"),
        "aggregate_csv": str(output_root / "cache_v0.csv"),
    }
    manifest_path = output_root / "manifest.json"
    atomic_json(manifest_path, manifest)
    atomic_json(Path(manifest["gates_path"]), {
        "schema": "stokes_cache_dse_gates/v1", "status": "pass",
        "manifest_sha256": digest(manifest_path),
        "checks": ["wcts trailer marker/records", "receipt wcts_sha256",
                   "receipt identity (sample, layer)", "receipt byte size",
                   "configs/V0.json == BASE_CONFIG", "binary present+hashed"],
        "gated_by": "spikinglm_v0_manifest.py (single-variant manifest)",
    })
    print(json.dumps({"manifest": str(manifest_path), "cases": len(cases),
                      "traces": len(traces)}, sort_keys=True))


if __name__ == "__main__":
    main()
