"""Serial capture traversal and durable CSV output for architecture counts."""
import csv
import json
import sys
from pathlib import Path

import spinalflow_counts as spinal

IDENTITY = ("capture", "layer", "sample", "source_sample", "kernel", "stride", "COUT")
PROVENANCE = ("density_layer", "O_source", "wcts_path", "wcts_bursts", "replay_status")


def validate_replay(path, counts, design, layer, sample):
    summary = spinal.read_wcts_summary(path)
    if (summary["arch"], summary["layer"], summary["sample"]) != (design, layer, sample):
        raise ValueError("WCTS identity does not match requested architecture/layer/sample")
    if summary["burst_dim"] != 3 or summary["burst_stride"] != 1:
        raise ValueError("WCTS must burst over contiguous COUT")
    if summary["dims"].get(3) != counts["COUT"] or summary["weights"] != counts["weight_bytes"]:
        raise ValueError("WCTS dimensions/lane bytes do not match analytic full-layer work")
    return summary["bursts"], "pass" if summary["bursts"] == counts["B"] else "pass_geometry"


def resume_rows(path, fields):
    """Discard only an interrupted final record; refuse interior corruption."""
    if not path.exists() or not path.stat().st_size:
        return set()
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(fields):
            raise ValueError(f"CSV schema differs: {path}")
        rows = list(reader)
    complete = []
    keys = set()
    for i, row in enumerate(rows):
        try:
            if None in row or any(v is None for v in row.values()):
                raise ValueError("partial record")
            key = (row["capture"], row["layer"], int(row["sample"]))
            for name in ("A", "O", "d_out"):
                float(row[name])
        except (TypeError, ValueError):
            if i != len(rows) - 1:
                raise ValueError(f"corrupt interior row in {path}: {i + 2}")
            break
        if key in keys:
            raise ValueError(f"duplicate row in {path}: {key}")
        keys.add(key)
        complete.append(row)
    if len(complete) != len(rows):
        temporary = path.with_suffix(path.suffix + ".repair")
        with temporary.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(complete)
        temporary.replace(path)
    return keys


def main(design, count_sample, count_fields, argv=None, layer_setup=None):
    args = spinal._parse_args(argv)
    spinal.cap_threads(args.threads)
    # The shared argument parser's default belongs to SpinalFlow.
    if args.output == Path(spinal.__file__).with_name("spinalflow_counts.csv"):
        args.output = Path(__file__).with_name(design + "_counts.csv")
    sys.path.insert(0, str(spinal.SRC))
    from lays.weight_trace_gen.trace import load_layer_trace
    import numpy as np
    captures = spinal._capture_dirs(args.trace_root)
    if args.captures:
        selected = []
        for name in args.captures:
            matches = [p for p in captures if name in (p.name, p.relative_to(args.trace_root).as_posix())]
            if len(matches) != 1:
                raise ValueError(f"capture {name!r} matches {len(matches)} directories")
            selected.extend(matches)
        captures = selected
    captures = captures[:args.max_captures]
    if not captures:
        raise ValueError("no captures selected")
    fields = (*IDENTITY, *count_fields, *PROVENANCE)
    if args.output.exists() and args.output.stat().st_size and not args.resume:
        raise ValueError("output exists; use --resume")
    completed = resume_rows(args.output, fields) if args.resume else set()
    index = spinal.index_wcts(args.wcts_root) if args.wcts_root else {}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.output.exists() and args.output.stat().st_size else "w"
    written = skipped = 0
    with args.output.open(mode, newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        if mode == "w":
            writer.writeheader()
        for directory in captures:
            capture = directory.relative_to(args.trace_root).as_posix()
            meta = json.loads((directory / "meta.json").read_text())
            all_layers = list(meta["layers"])
            for layer in spinal._valid_layers(meta, args.layers)[:args.max_layers]:
                counter = count_sample if layer_setup is None else layer_setup(capture, layer, meta)
                if counter is None:
                    continue
                trace = load_layer_trace(directory, layer, mmap=True)
                position = all_layers.index(layer)
                density_layer = all_layers[min(position + 1, len(all_layers) - 1)]
                following = trace if density_layer == layer else load_layer_trace(directory, density_layer, mmap=True)
                params = meta["layer_params"][layer]
                for sample in spinal._sample_indices(trace.shape[1], args.sample_start, args.sample_count, args.max_samples):
                    key = (capture, layer, sample)
                    if key in completed:
                        skipped += 1
                        continue
                    density = float(np.count_nonzero(following[:, sample]) / following[:, sample].size)
                    counts = counter(trace, sample, cout=params["cout"], kernel=params["kernel"],
                                          stride=params["stride"], cout_n=args.cout_n, d_out=density)
                    paths = [p for p in index.get(key, []) if spinal.read_wcts_summary(p)["arch"] == design]
                    if len(paths) > 1:
                        raise ValueError(f"multiple replay streams for {key}")
                    bursts, status = ("", "unavailable")
                    if paths:
                        bursts, status = validate_replay(paths[0], {**counts, "COUT": params["cout"]}, design, layer, sample)
                    source = meta.get("subset", {}).get("sample_indices", [])
                    writer.writerow({"capture": capture, "layer": layer, "sample": sample,
                                     "source_sample": source[sample] if source else sample,
                                     "kernel": params["kernel"], "stride": params["stride"], "COUT": params["cout"],
                                     **counts, "density_layer": density_layer,
                                     "O_source": "final_layer_own_density_proxy" if density_layer == layer else "next_layer_input_density",
                                     "wcts_path": str(paths[0]) if paths else "", "wcts_bursts": bursts, "replay_status": status})
                    stream.flush()
                    completed.add(key)
                    written += 1
    print(f"{design}: wrote {written} rows; skipped {skipped}; output={args.output}")
    return 0
