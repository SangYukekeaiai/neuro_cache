#!/usr/bin/env python3
"""Compute the analytic SpinalFlow event counts for captured spike traces.

The input capture format is ``[T, B, CIN, Hin, Win]`` with one ``meta.json``
per capture directory.  A run is serial and mmap-backed so it is safe to use
as one bounded Slurm task; existing CSV rows are skipped with ``--resume``.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import struct
import sys
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
MAX_THREADS = 4
DEFAULT_COUT_CAP = 4
OUTPUT_FIELDS = (
    "capture",
    "layer",
    "sample",
    "source_sample",
    "T",
    "CIN",
    "Hin",
    "Win",
    "kernel",
    "stride",
    "COUT",
    "HO",
    "WO",
    "cout_n",
    "S_win",
    "A",
    "R",
    "O",
    "O_bound",
    "O_source",
    "wcts_path",
    "wcts_bursts",
    "replay_status",
    "replay_detail",
)
WCTS_SAMPLE_RE = re.compile(r"sample_(\d+)\.wcts(?:\.gz)?$")
WCTS_FIXED = struct.Struct("<IIiiiiiiiiii")
WCTS_FRAME = struct.Struct("<iiqQ")
WCTS_CORE = struct.Struct("<ii")
WCTS_RECORD = struct.Struct("<q5i")
WCTS_TRAILER = struct.Struct("<iQ")


def cap_threads(threads: int) -> None:
    """Set common math-library pools before NumPy is imported."""
    if not 1 <= threads <= MAX_THREADS:
        raise ValueError(f"threads must be in [1, {MAX_THREADS}]")
    for name in THREAD_ENV_VARS:
        os.environ[name] = str(threads)


def effective_cout_n(cout: int, cap: int = DEFAULT_COUT_CAP) -> int:
    """Return the campaign's largest COUT divisor not exceeding ``cap``."""
    if cout < 1 or cap < 1:
        raise ValueError("COUT and its cap must be positive")
    for divisor in range(min(cout, cap), 0, -1):
        if cout % divisor == 0:
            return divisor
    return 1


def _axis_coverage(input_size: int, output_size: int, kernel: int, pad: int, stride: int):
    import numpy as np

    coverage = np.zeros(input_size, dtype=np.int64)
    for output in range(output_size):
        start = output * stride - pad
        stop = start + kernel
        lo = max(0, start)
        hi = min(input_size, stop)
        if lo < hi:
            coverage[lo:hi] += 1
    return coverage


def window_coverage(hin: int, win: int, kernel: int, stride: int = 1):
    """Return the 2-D multiplicity of a padded all-ones convolution."""
    if kernel not in (1, 3) or stride != 1:
        raise ValueError("SpinalFlow counts support only 1x1/3x3 stride-1 layers")
    pad = (kernel - 1) // 2
    ho = (hin + 2 * pad - kernel) // stride + 1
    wo = (win + 2 * pad - kernel) // stride + 1
    h = _axis_coverage(hin, ho, kernel, pad, stride)
    w = _axis_coverage(win, wo, kernel, pad, stride)
    return h[:, None] * w[None, :]


def count_sample(trace: Any, sample: int, *, cout: int, kernel: int,
                 stride: int = 1, cout_n: int | None = None) -> dict[str, int]:
    """Compute ``S_win``, ``A``, ``R`` and the conservative ``O`` bound."""
    import numpy as np

    if getattr(trace, "ndim", None) != 5:
        raise ValueError(f"trace must have shape [T,B,CIN,Hin,Win], got {getattr(trace, 'shape', None)}")
    t, batch, cin, hin, win = map(int, trace.shape)
    if not 0 <= sample < batch:
        raise IndexError(f"sample {sample} is outside [0, {batch})")
    if cout < 1:
        raise ValueError("COUT must be positive")
    if stride != 1 or kernel not in (1, 3):
        raise ValueError("SpinalFlow counts support only 1x1/3x3 stride-1 layers")
    if cout_n is None:
        cout_n = effective_cout_n(cout)
    if cout_n < 1 or cout % cout_n:
        raise ValueError(f"cout_n={cout_n} must be a positive divisor of COUT={cout}")

    coverage = window_coverage(hin, win, kernel, stride)
    # Boolean conversion makes the nonzero-spike contract explicit.  The
    # einsum accumulates directly into int64 without making a padded tensor.
    active = np.asarray(trace[:, sample]) != 0
    s_win = int(np.einsum("tchw,hw->", active, coverage, dtype=np.int64, optimize=False))
    pad = (kernel - 1) // 2
    ho = (hin + 2 * pad - kernel) // stride + 1
    wo = (win + 2 * pad - kernel) // stride + 1
    accumulates = s_win * cout
    return {
        "T": t,
        "CIN": cin,
        "Hin": hin,
        "Win": win,
        "HO": ho,
        "WO": wo,
        "cout_n": int(cout_n),
        "S_win": s_win,
        "A": accumulates,
        "R": accumulates // cout_n,
        "O": ho * wo * cout * t,
    }


def _read_exact(stream: BinaryIO, size: int, what: str) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise ValueError(f"WCTS ended while reading {what}")
    return data


def _open_wcts(path: Path):
    return gzip.open(path, "rb") if path.name.endswith(".gz") else path.open("rb")


def read_wcts_summary(path: Path) -> dict[str, Any]:
    """Stream-parse a WCTS file and return its identity, dimensions and count."""
    with _open_wcts(path) as stream:
        if _read_exact(stream, 8, "magic") != b"WCTRACE1":
            raise ValueError(f"{path}: invalid WCTS magic")
        fixed = WCTS_FIXED.unpack(_read_exact(stream, WCTS_FIXED.size, "fixed header"))
        (version, header_bytes, n_tiles, n_cores, weight_bytes, burst_dim,
         burst_stride, burst_span, n_addr_fields, n_spatial, n_dims,
         identity_bytes) = fixed
        if version not in (2, 3):
            raise ValueError(f"{path}: unsupported WCTS version {version}")
        if n_tiles < 0 or n_cores < 0 or n_addr_fields < 0 or n_spatial < 0 or n_dims < 0:
            raise ValueError(f"{path}: negative WCTS header count")
        if n_addr_fields != 5 or tuple(struct.unpack(
                "<5i", _read_exact(stream, 20, "address fields"))) != (0, 1, 2, 3, 4):
            raise ValueError(f"{path}: expected the five COUT address fields")
        spatial = [struct.unpack("<ii", _read_exact(stream, 8, "spatial factor"))
                   for _ in range(n_spatial)]
        dims = dict(struct.unpack("<ii", _read_exact(stream, 8, "dimension"))
                    for _ in range(n_dims))
        identity_raw = _read_exact(stream, identity_bytes, "identity")
        identity = identity_raw.rstrip(b"\0").decode("utf-8", errors="replace").split("\0")
        if len(identity) != 4:
            raise ValueError(f"{path}: WCTS identity must contain arch/workload/layer/sample")
        expected_header_bytes = 56 + 20 + 8 * n_spatial + 8 * n_dims + identity_bytes
        if header_bytes != expected_header_bytes:
            raise ValueError(f"{path}: header_bytes={header_bytes}, expected {expected_header_bytes}")

        bursts = 0
        spans: set[int] = set()
        weights = 0
        for tile_index in range(n_tiles):
            tile, n_blocks, _mac_cycles, payload_bytes = WCTS_FRAME.unpack(
                _read_exact(stream, WCTS_FRAME.size, f"tile {tile_index} header"))
            if tile != tile_index:
                raise ValueError(f"{path}: tile index {tile}, expected {tile_index}")
            if n_blocks < 0:
                raise ValueError(f"{path}: negative core-block count in tile {tile_index}")
            consumed = 0
            previous_core = -1
            for _ in range(n_blocks):
                core_id, n_bursts = WCTS_CORE.unpack(
                    _read_exact(stream, WCTS_CORE.size, f"tile {tile_index} core block"))
                consumed += WCTS_CORE.size
                if core_id <= previous_core or core_id < 0 or core_id >= n_cores:
                    raise ValueError(f"{path}: invalid core order/id in tile {tile_index}")
                if n_bursts < 1:
                    raise ValueError(f"{path}: empty core block in tile {tile_index}")
                previous_core = core_id
                previous_tick = -1
                for _ in range(n_bursts):
                    tick, kh, kw, cin, cout_start, cout_end = WCTS_RECORD.unpack(
                        _read_exact(stream, WCTS_RECORD.size, f"tile {tile_index} burst"))
                    consumed += WCTS_RECORD.size
                    if tick < 0 or (version == 2 and tick <= previous_tick) or (version == 3 and tick < previous_tick):
                        raise ValueError(f"{path}: invalid tick order in tile {tile_index}")
                    previous_tick = tick
                    if burst_dim == 3:
                        span = cout_end - cout_start
                        if span <= 0:
                            raise ValueError(f"{path}: empty COUT burst in tile {tile_index}")
                        spans.add(span)
                        weights += span
                    elif burst_dim not in (0, 1, 2):
                        raise ValueError(f"{path}: unsupported burst dimension {burst_dim}")
                    bursts += 1
            if consumed != payload_bytes:
                raise ValueError(
                    f"{path}: tile {tile_index} payload={payload_bytes}, decoded={consumed}"
                )
        end_magic, declared_bursts = WCTS_TRAILER.unpack(
            _read_exact(stream, WCTS_TRAILER.size, "trailer"))
        if end_magic != -1 or declared_bursts != bursts:
            raise ValueError(f"{path}: trailer count {declared_bursts} != decoded {bursts}")
        if stream.read(1):
            raise ValueError(f"{path}: bytes follow the WCTS trailer")

    return {
        "path": str(path),
        "version": version,
        "n_tiles": n_tiles,
        "n_cores": n_cores,
        "weight_bytes": weight_bytes,
        "burst_dim": burst_dim,
        "burst_stride": burst_stride,
        "burst_span": burst_span,
        "arch": identity[0],
        "workload": identity[1],
        "layer": identity[2],
        "sample": int(identity[3]),
        "dims": dims,
        "spatial": spatial,
        "bursts": bursts,
        "spans": spans,
        "weights": weights,
    }


def validate_wcts(summary: Mapping[str, Any], counts: Mapping[str, int], layer: str,
                  sample: int) -> tuple[str, str]:
    """Check full-layer work, allowing a different COUT burst width.

    Partial streams cannot establish full-layer correctness and fail.
    """
    details: list[str] = []
    if summary["arch"] != "spinalflow":
        details.append(f"arch={summary['arch']}")
    if summary["layer"] != layer:
        details.append(f"layer={summary['layer']}")
    if summary["sample"] != sample:
        details.append(f"sample={summary['sample']}")
    if summary["burst_dim"] != 3:
        details.append(f"burst_dim={summary['burst_dim']}")
    if summary["burst_stride"] != 1:
        details.append(f"burst_stride={summary['burst_stride']}")
    if summary["dims"].get(3) != counts["COUT"]:
        details.append(f"COUT={summary['dims'].get(3)} expected {counts['COUT']}")
    if details:
        return "mismatch", "; ".join(details)

    observed = int(summary["bursts"])
    expected = int(counts["R"])
    if summary["weights"] != counts["A"]:
        return "mismatch", f"decoded {summary['weights']} lane operations, expected A={counts['A']}"
    if summary["spans"] == {counts["cout_n"]} and observed == expected:
        return "pass", f"decoded {observed} bursts; lane operations match A"
    return "pass_geometry", (f"decoded {observed} bursts at spans {sorted(summary['spans'])}; "
                             f"lane operations match A; campaign R={expected}")


def index_wcts(root: Path) -> dict[tuple[str, str, int], list[Path]]:
    """Index WCTS files by their capture directory, layer, and sample.

    The campaign may place an architecture directory between a capture and
    its layer (for example ``<capture>/spinalflow/<layer>/sample_*.wcts``),
    so the capture is identified by the nearest ancestor carrying
    ``meta.json`` rather than by a fixed parent depth.
    """
    index: dict[tuple[str, str, int], list[Path]] = {}
    for path in sorted(root.rglob("*.wcts")) + sorted(root.rglob("*.wcts.gz")):
        match = WCTS_SAMPLE_RE.fullmatch(path.name)
        if not match or path.parent == root:
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        parts = relative.parts
        layer = parts[-2]
        capture_parts = None
        for end in range(1, len(parts) - 1):
            if (root.joinpath(*parts[:end]) / "meta.json").is_file():
                capture_parts = parts[:end]
                break
        if capture_parts is None:
            if len(parts) < 3:
                continue
            capture_parts = parts[:-2]
        capture = Path(*capture_parts).as_posix()
        key = (capture, layer, int(match.group(1)))
        index.setdefault(key, []).append(path)
    return index


def _find_wcts(index: Mapping[tuple[str, str, int], list[Path]], capture: str,
                layer: str, sample: int) -> Path | None:
    paths = index.get((capture, layer, sample), [])
    if not paths:
        return None
    spinalflow = [p for p in paths if "spinalflow" in p.parts]
    return sorted(spinalflow or paths)[0]


def _capture_dirs(root: Path) -> list[Path]:
    captures = []
    for meta_path in sorted(root.glob("*/*/meta.json")):
        captures.append(meta_path.parent)
    return captures


def _valid_layers(meta: Mapping[str, Any], requested: Iterable[str] | None = None) -> list[str]:
    names = list(meta.get("layers", {}))
    if requested:
        wanted = list(requested)
        missing = [name for name in wanted if name not in names]
        if missing:
            raise ValueError(f"requested layer(s) absent from meta.json: {', '.join(missing)}")
        names = [name for name in names if name in wanted]
    valid = []
    for name in names:
        params = meta.get("layer_params", {}).get(name)
        if not isinstance(params, dict):
            raise ValueError(f"meta.json has no layer_params[{name!r}]")
        if params.get("stride") == 1 and params.get("kernel") in (1, 3):
            valid.append(name)
    return valid


def _sample_indices(batch: int, start: int, count: int | None, maximum: int | None) -> list[int]:
    if start < 0 or start >= batch:
        raise ValueError(f"sample-start={start} is outside batch size {batch}")
    stop = batch if count is None else min(batch, start + count)
    if count is not None and count < 1:
        raise ValueError("sample-count must be positive")
    indices = list(range(start, stop))
    if maximum is not None:
        if maximum < 1:
            raise ValueError("max-samples must be positive")
        indices = indices[:maximum]
    return indices


def _load_completed(path: Path) -> set[tuple[str, str, int]]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        missing = [field for field in OUTPUT_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"existing output is missing columns: {', '.join(missing)}")
        completed = set()
        for row in reader:
            try:
                completed.add((row["capture"], row["layer"], int(row["sample"])))
            except (KeyError, TypeError, ValueError):
                # A killed job can leave a partial final CSV row; it is not a
                # completed unit and will be recomputed on resume.
                continue
        return completed


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-root", type=Path, required=True,
                        help="capture root containing <group>/<capture>/meta.json")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).with_name("spinalflow_counts.csv"))
    parser.add_argument("--wcts-root", type=Path,
                        help="optional WCTS root for replay count checks")
    parser.add_argument("--capture", action="append", dest="captures",
                        help="relative capture directory or unique basename; repeatable")
    parser.add_argument("--layer", action="append", dest="layers",
                        help="layer name filter; repeatable")
    parser.add_argument("--sample-start", type=int, default=0)
    parser.add_argument("--sample-count", type=int)
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--max-captures", type=int)
    parser.add_argument("--max-layers", type=int)
    parser.add_argument("--cout-n", type=int,
                        help="override the effective COUT burst width; must divide COUT")
    parser.add_argument("--threads", type=int, default=1,
                        help=f"cap BLAS/OpenMP pools (default: 1, maximum: {MAX_THREADS})")
    parser.add_argument("--resume", action="store_true",
                        help="skip completed (capture, layer, sample) rows in --output")
    args = parser.parse_args(argv)
    for name in ("max_samples", "max_captures", "max_layers"):
        value = getattr(args, name)
        if value is not None and value < 1:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.sample_start < 0:
        parser.error("--sample-start must be nonnegative")
    if args.sample_count is not None and args.sample_count < 1:
        parser.error("--sample-count must be positive")
    return args


def run(args: argparse.Namespace) -> int:
    cap_threads(args.threads)
    if not args.trace_root.is_dir():
        raise ValueError(f"trace root does not exist: {args.trace_root}")
    captures = _capture_dirs(args.trace_root)
    by_id = {path.relative_to(args.trace_root).as_posix(): path for path in captures}
    if args.captures:
        selected = []
        for requested in args.captures:
            matches = [path for key, path in by_id.items()
                       if key == requested or path.name == requested]
            if len(matches) != 1:
                raise ValueError(f"capture {requested!r} matched {len(matches)} directories")
            selected.append(matches[0])
        captures = selected
    if args.max_captures is not None:
        captures = captures[:args.max_captures]
    if not captures:
        raise ValueError("no capture directories selected")

    wcts_index = index_wcts(args.wcts_root) if args.wcts_root else {}
    completed = _load_completed(args.output) if args.resume else set()
    if args.output.exists() and not args.resume and args.output.stat().st_size:
        raise ValueError(f"output exists; pass --resume to append: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.output.exists() and args.output.stat().st_size else "w"
    rows = skipped = replay_failures = unsupported = 0
    with args.output.open(mode, newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
        if mode == "w":
            writer.writeheader()
            stream.flush()
        for capture_dir in captures:
            capture_id = capture_dir.relative_to(args.trace_root).as_posix()
            meta = json.loads((capture_dir / "meta.json").read_text())
            unsupported += len(meta.get("layers", {})) - len(_valid_layers(meta))
            layers = _valid_layers(meta, args.layers)
            if args.max_layers is not None:
                layers = layers[:args.max_layers]
            for layer in layers:
                params = meta["layer_params"][layer]
                # Import the repository helper only after thread pools are capped.
                if str(SRC) not in sys.path:
                    sys.path.insert(0, str(SRC))
                from lays.weight_trace_gen.trace import load_layer_trace

                trace = load_layer_trace(capture_dir, layer, mmap=True)
                samples = _sample_indices(int(trace.shape[1]), args.sample_start,
                                          args.sample_count, args.max_samples)
                source_samples = meta.get("subset", {}).get("sample_indices", [])
                for sample in samples:
                    key = (capture_id, layer, sample)
                    if key in completed:
                        skipped += 1
                        continue
                    counts = count_sample(trace, sample, cout=int(params["cout"]),
                                          kernel=int(params["kernel"]),
                                          stride=int(params["stride"]), cout_n=args.cout_n)
                    wcts_path = _find_wcts(wcts_index, capture_id, layer, sample)
                    replay_status = "unavailable"
                    replay_detail = ""
                    wcts_bursts: int | str = ""
                    if wcts_path is not None:
                        try:
                            summary = read_wcts_summary(wcts_path)
                            replay_status, replay_detail = validate_wcts(
                                summary, {**counts, "COUT": int(params["cout"])}, layer, sample)
                            wcts_bursts = int(summary["bursts"])
                            if replay_status == "mismatch":
                                replay_failures += 1
                        except ValueError as exc:
                            replay_status = "error"
                            replay_detail = str(exc)
                            replay_failures += 1
                    row = {
                        "capture": capture_id,
                        "layer": layer,
                        "sample": sample,
                        "source_sample": source_samples[sample] if sample < len(source_samples) else sample,
                        "T": counts["T"],
                        "CIN": counts["CIN"],
                        "Hin": counts["Hin"],
                        "Win": counts["Win"],
                        "kernel": params["kernel"],
                        "stride": params["stride"],
                        "COUT": params["cout"],
                        "HO": counts["HO"],
                        "WO": counts["WO"],
                        "cout_n": counts["cout_n"],
                        "S_win": counts["S_win"],
                        "A": counts["A"],
                        "R": counts["R"],
                        "O": counts["O"],
                        "O_bound": counts["O"],
                        "O_source": "bound",
                        "wcts_path": str(wcts_path) if wcts_path else "",
                        "wcts_bursts": wcts_bursts,
                        "replay_status": replay_status,
                        "replay_detail": replay_detail,
                    }
                    writer.writerow(row)
                    stream.flush()
                    rows += 1

    print(f"wrote {rows} rows to {args.output}; skipped {skipped}; "
          f"unsupported_layers {unsupported}; replay_failures {replay_failures}")
    return 2 if replay_failures else 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return run(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
