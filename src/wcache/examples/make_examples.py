"""Cut small, schema-faithful example traces out of the generated corpus.

Plan unit A3 (`TraceReader`) is unbuilt, and every Phase C test drives the
engine from `FakeTrace`, a hand-written stand-in that invents its own numbers.
The obligation row "Phase C -> A3" in PROGRESS.md says what that costs: the
`gap == 0` count and the `tile_tail` histogram are owed against the REAL
corpus, and a green Phase C suite is not evidence for either.

These examples are the corpus half of that. Each one is a SLICE of a real
generated sample, small enough to commit and read by eye, and schema-identical
to the file it came from: no key is added, renamed, or reordered, so a reader
pointed at an example is exercising the same decode path it will run on a
1.5 GB corpus file. Provenance and the slice parameters live in
`manifest.json` beside them, never inside the trace files.

Two on-disk shapes exist in the corpus and both get an example:

  v2  tiles[] -> ticks[] -> cores[] -> weight_addresses[]   (tick and core_id
      present; what the engine needs, and what `src/tracegen.py` writes today)
  v1  tiles[] -> weight_addresses[]                          (flat, no tick, no
      core; a stale generation still on disk for gustavsnn)

The one number a slice cannot preserve by truncation is `mac_cycles`, since
`tile_tail = mac_cycles - max_tick` (Q10) and truncating the ticks moves
`max_tick`. It is rewritten to `max_tick_in_slice + original_tail` so the tail
is carried across exactly; `manifest.json` records the original value. Every
other field is copied verbatim.

Run from the repo root:  conda run -n base python src/wcache/examples/make_examples.py
"""

from __future__ import annotations

import gzip
import json
import os
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
CORPUS = REPO / "outputs" / "weight_traces"
OUT = pathlib.Path(__file__).resolve().parent

# Slice size. Small enough that the whole file is readable in a terminal and
# every burst can be checked by hand, large enough that a core still runs out
# of work inside the window (which is what makes `n_bursts == 0` and the
# early-finishing core reachable at all).
N_TILES = 2
N_CORES = 8
N_TICKS = 24
N_FLAT_ADDRS = 32  # v1 only: it has no ticks to cut on

# Each entry states the property the example exists to carry. `check` is run
# against the finished slice and the script fails if it does not hold, so an
# example cannot silently stop demonstrating the thing it was cut for.
EXAMPLES = [
    dict(
        name="loas_vgg16_layer01_v2.json",
        src="loas/vgg16_T4_all/layer_01_features_3/sample_00000.json.gz",
        why="the ordinary case: every core busy every tick, gap == 1 throughout, "
            "tile_tail == 1, burst spans 16 COUT",
        check=lambda s: s["gap_min"] == 1 and s["gap_max"] == 1 and s["tail"] == [1, 1]
                        and s["spans"] == [16] and s["empty_core_tiles"] == 0,
    ),
    dict(
        name="ptb_resnet19_layer01_v2.json",
        src="ptb/resnet19_T4_all/layer_01_layer1_0_conv1/sample_00000.json.gz",
        why="the only measured non-trivial tile_tail: compute outlives the last "
            "weight burst by ~20 cycles, so the tile seam is not free",
        check=lambda s: min(s["tail"]) >= 15,
    ),
    dict(
        name="prosperity_vgg16_layer01_v2.json",
        src="prosperity/vgg16_T4_all/layer_01_features_3/sample_00000.json.gz",
        why="sparse core participation: some cores issue nothing in a tile "
            "(n_bursts == 0 is legal) and another runs out of work mid-window",
        check=lambda s: s["empty_core_tiles"] > 0 and s["short_cores"] > 0,
    ),
    dict(
        name="spinalflow_vgg16_layer01_v2.json",
        src="spinalflow/vgg16_T4_all/layer_01_features_3/sample_00000.json.gz",
        why="a burst four times longer than loas/ptb: 64 COUT per burst, so a "
            "single burst can span several lines under a narrow cout_block",
        check=lambda s: s["spans"] == [64],
    ),
    dict(
        name="gustavsnn_vgg16_layer01_v1_legacy.json",
        src="gustavsnn/vgg16_T4_all/layer_01_features_3/sample_00000.json.gz",
        why="the legacy flat shape, still on disk for all 31 gustavsnn layers: "
            "no tick, no core_id, so the engine cannot be driven from it at all",
        check=lambda s: s["fmt"] == "v1",
    ),
]


def load(path: pathlib.Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as fh:
        return json.load(fh)


def slice_v2(doc):
    """First N_TILES tiles, cores 0..N_CORES-1, first N_TICKS ticks of each."""
    tiles = []
    for tile in doc["tiles"][:N_TILES]:
        original_tail = tile["mac_cycles"] - max(t["tick"] for t in tile["ticks"])
        ticks = []
        for entry in tile["ticks"][:N_TICKS]:
            cores = [c for c in entry["cores"] if c["core_id"] < N_CORES]
            # A tick every kept core sat out is dropped rather than written as
            # an empty `cores` list: the corpus omits absent cores, never pads
            # them (tracegen.TickEntry), and an example must not invent a shape
            # the reader will never see.
            if cores:
                ticks.append({"tick": entry["tick"], "cores": cores})
        if not ticks:
            continue
        out = dict(tile)
        out["ticks"] = ticks
        out["mac_cycles"] = max(t["tick"] for t in ticks) + original_tail
        tiles.append(out)

    doc = dict(doc)
    doc["tiles"] = tiles
    # Kept consistent with what survived the cut, so the header does not claim
    # a tiling the file no longer contains.
    doc["dram_num_steps"] = len({t["dram_i"] for t in tiles})
    doc["noc_num_steps"] = len({t["noc_i"] for t in tiles})
    return doc


def slice_v1(doc):
    tiles = []
    for tile in doc["tiles"][:N_TILES]:
        out = dict(tile)
        out["weight_addresses"] = tile["weight_addresses"][:N_FLAT_ADDRS]
        tiles.append(out)
    doc = dict(doc)
    doc["tiles"] = tiles
    doc["dram_num_steps"] = len(tiles)
    return doc


def summarize(doc):
    """The properties the `check` predicates are written against."""
    tiles = doc["tiles"]
    if "ticks" not in tiles[0]:
        return dict(fmt="v1", n_tiles=len(tiles),
                    bursts=sum(len(t["weight_addresses"]) for t in tiles),
                    spans=sorted({a[4] - a[3] for t in tiles for a in t["weight_addresses"]}))

    gaps, tails, spans = [], [], set()
    bursts = empty_core_tiles = short_cores = 0
    for tile in tiles:
        per_core = {}
        for entry in tile["ticks"]:
            for core in entry["cores"]:
                wa = core["weight_addresses"]
                bursts += len(wa)
                spans.update(a[4] - a[3] for a in wa)
                per_core.setdefault(core["core_id"], []).extend([entry["tick"]] * len(wa))
        window = max(t["tick"] for t in tile["ticks"])
        for core_id in range(N_CORES):
            ticks = sorted(per_core.get(core_id, []))
            if not ticks:
                empty_core_tiles += 1
                continue
            if ticks[-1] < window:
                short_cores += 1
            gaps.extend(b - a for a, b in zip(ticks, ticks[1:]))
        tails.append(tile["mac_cycles"] - window)

    return dict(fmt="v2", n_tiles=len(tiles), bursts=bursts,
                cores=sorted({c["core_id"] for t in tiles for e in t["ticks"] for c in e["cores"]}),
                gap_min=min(gaps), gap_max=max(gaps),
                gap_zero_count=sum(1 for g in gaps if g == 0),
                tail=tails, spans=sorted(spans),
                empty_core_tiles=empty_core_tiles, short_cores=short_cores)


# `json.dump(..., indent=1)` puts every one of an address tuple's five integers
# on its own line, which turns a 384-burst example into 4900 lines and defeats
# the point of an example being readable. Indent everything else and keep each
# `[kh, kw, cin, cout_start, cout_end]` on one line, by dumping the tuples as
# placeholder strings and taking the quotes back off afterwards. The result is
# the same JSON value; only the whitespace differs.
# json.dumps escapes the sentinel to the six characters \u0000, not the byte.
_INLINED = re.compile(r'"\\u0000(\[[^"]*\])\\u0000"')


def dumps_addresses_inline(doc) -> str:
    def mark(node):
        if isinstance(node, dict):
            return {k: ([f"\x00{json.dumps(a)}\x00" for a in v]
                        if k == "weight_addresses" else mark(v))
                    for k, v in node.items()}
        if isinstance(node, list):
            return [mark(x) for x in node]
        return node

    return _INLINED.sub(lambda m: m.group(1), json.dumps(mark(doc), indent=1)) + "\n"


def main() -> int:
    if not CORPUS.is_dir():
        print(f"corpus not found: {CORPUS}", file=sys.stderr)
        return 1

    manifest = dict(
        generated_by="src/wcache/examples/make_examples.py",
        corpus_root=os.path.relpath(CORPUS, REPO),
        slice=dict(n_tiles=N_TILES, n_cores=N_CORES, n_ticks=N_TICKS,
                   n_flat_addresses=N_FLAT_ADDRS),
        mac_cycles="rewritten to max_tick_in_slice + original tile_tail; every "
                   "other field is copied verbatim from the source sample",
        examples=[],
    )

    failures = []
    for spec in EXAMPLES:
        src = CORPUS / spec["src"]
        if not src.exists():
            failures.append(f"{spec['name']}: source missing, {src}")
            continue
        doc = load(src)
        is_v2 = "ticks" in doc["tiles"][0]
        sliced = slice_v2(doc) if is_v2 else slice_v1(doc)
        summary = summarize(sliced)

        if not spec["check"](summary):
            failures.append(f"{spec['name']}: no longer carries its property -- {summary}")
            continue

        path = OUT / spec["name"]
        path.write_text(dumps_addresses_inline(sliced))

        manifest["examples"].append(dict(
            file=spec["name"], source=spec["src"], why=spec["why"],
            format=summary["fmt"],
            source_tiles=len(doc["tiles"]),
            source_mac_cycles=[t["mac_cycles"] for t in doc["tiles"][:N_TILES]],
            bytes=path.stat().st_size,
            **{k: v for k, v in summary.items() if k != "fmt"},
        ))
        print(f"{spec['name']:44s} {path.stat().st_size:7d} B  {summary['bursts']:5d} bursts")

    with open(OUT / "manifest.json", "w") as fh:
        json.dump(manifest, fh, indent=1)
        fh.write("\n")

    for f in failures:
        print("FAIL " + f, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
