"""Prosperity counts from saved per-sample records; never rerun the prefix walk."""
import argparse
import csv
import json
import math
import re
from pathlib import Path

import spinalflow_counts as spinal

FIELDS = ("T", "CIN", "Hin", "Win", "HO", "WO", "cout_n", "S_win", "N_rows",
          "SORT", "R_p", "A_p", "A", "B", "raw", "saved_fetches", "L", "O", "d_out",
          "seed_reads_bound", "psum_writes", "weight_bytes", "records_source")


def count_sample(trace, sample, *, cout, kernel, stride=1, cout_n=None, d_out=None,
                 tile, records=None, records_source="exact_pipeline_csv"):
    import numpy as np
    if d_out is None:
        raise ValueError("d_out is required: use next-layer density, or an explicitly labeled final-layer proxy")
    slab = int(tile["COUT"])
    if cout_n is not None and cout_n != slab:
        raise ValueError("cout_n must match the realized Prosperity schedule")
    base = spinal.count_sample(trace, sample, cout=cout, kernel=kernel, stride=stride, cout_n=slab)
    active = np.asarray(trace[:, sample]) != 0
    sort = 0.0
    closed_form = 0
    for t in range(0, base["T"], tile["T"]):
        for h in range(0, base["HO"], tile["HO"]):
            for w in range(0, base["WO"], tile["WO"]):
                block = active[t:t+tile["T"], :, h:h+tile["HO"], w:w+tile["WO"]]
                m = block.shape[0] * block.shape[2] * block.shape[3]
                sort += 2 * m * math.log2(m) * base["CIN"]
                if kernel == 1:
                    closed_form += int(np.any(block, axis=(0, 2, 3)).sum()) * (cout // slab)
    if records is None:
        if kernel != 1:
            raise ValueError("missing exact per-sample S3 records for 3x3; digest means cannot substitute")
        records = closed_form
        records_source = "1x1_closed_form"
    elif kernel == 1 and records != closed_form:
        raise ValueError("saved digest records disagree with the 1x1 closed form")
    raw = base["A"] // slab
    if not isinstance(records, int) or not 0 <= records <= raw:
        raise ValueError("invalid deduplicated record count")
    density = float(d_out)
    if not 0 <= density <= 1:
        raise ValueError("d_out must be in [0,1]")
    n_rows = base["HO"] * base["WO"] * base["T"] * base["CIN"]
    return {**{k: base[k] for k in FIELDS[:8]}, "N_rows": n_rows, "SORT": sort,
            "R_p": records, "A_p": records * slab, "A": records * slab, "B": records,
            "raw": raw, "saved_fetches": raw - records, "L": base["O"], "O": density * base["O"],
            "d_out": density, "seed_reads_bound": n_rows * cout, "psum_writes": n_rows * cout,
            "weight_bytes": records * slab, "records_source": records_source}


def schedule_tile(record, artifact):
    problem = record["workload"]["problem"]
    strategy = artifact["result"]["strategy"]
    factors = {dim: 1 for dim in ("KH", "KW", "CIN", "COUT", "HO", "WO", "T")}
    for loops in (strategy["DRAM"]["temporal_permutation"].get("loops", []),
                  strategy["NoCLevel"].get("temporal_permutation", {}).get("loops", []),
                  strategy["NoCLevel"].get("spatial_splitting", {}).get("loops", [])):
        for loop in loops:
            factors[loop["dim"]] *= int(loop["size"])
    if any(int(problem[k]) % factor for k, factor in factors.items()):
        raise ValueError("nonintegral schedule tile")
    return {k: int(problem[k]) // factor for k, factor in factors.items()}


def load_records(path):
    records = {}
    if path is None:
        return records
    with path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            key = (Path(row["capture"]).name, row["layer"], int(row["sample"]))
            if key in records:
                raise ValueError(f"duplicate digest count: {key}")
            records[key] = int(row["R_p"])
    return records


def digest_anchors(path):
    """Only explicitly reported sample-0 records; never use ranked means."""
    text = path.read_text()
    records = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 5 and cells[0] == "prosperity":
            records[(cells[1], cells[2], 0)] = int(cells[3].replace(",", ""))
    match = re.search(r"Prosperity B09\s+`loas_resnet19`\s+`([^`]+)`, sample 0, emitted\s+([\d,]+) bursts", text)
    if match:
        records[("loas_resnet19_T4_n500", match[1], 0)] = int(match[2].replace(",", ""))
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--record-counts", type=Path, help="saved exact CSV: capture,layer,sample,R_p")
    parser.add_argument("--digest", type=Path, default=spinal.ROOT / "zoo/wt500_fig3cfg/stokes/s3_digest.md")
    parser.add_argument("--manifest", type=Path, default=spinal.ROOT / "zoo/wt500_fig3cfg/outputs/manifest.json")
    extra, remaining = parser.parse_known_args(argv)
    records = digest_anchors(extra.digest)
    supplied = load_records(extra.record_counts)
    for key in records.keys() & supplied.keys():
        if records[key] != supplied[key]:
            raise ValueError(f"saved count disagrees with published digest anchor: {key}")
    records.update(supplied)
    manifest = json.loads(extra.manifest.read_text())
    schedules = {(r["trace_relative_dir"], r["layer"]): r for r in manifest["schedules"] if r["arch"] == "prosperity"}

    def prepare(capture, layer, meta):
        row = schedules[(capture, layer)]
        if row["solver_status"] == "INFEASIBLE":
            return None
        artifact = json.loads((extra.manifest.parent / row["schedule_path"]).read_text())
        tile = schedule_tile(row, artifact)

        def counter(trace, sample, **kwargs):
            return count_sample(trace, sample, tile=tile,
                                records=records.get((Path(capture).name, layer, sample)),
                                records_source=("exact_pipeline_csv" if (Path(capture).name, layer, sample) in supplied else "digest_anchor"), **kwargs)
        return counter

    from capture_counts import main as run
    return run("prosperity", count_sample, FIELDS, remaining, layer_setup=prepare)


if __name__ == "__main__":
    raise SystemExit(main())
