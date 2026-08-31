"""Increment 1 of log/2026-08-24-nocsim-per-tile-cycles-plan.md: the reader
that lets nocsim charge each schedule step its own MAC time (ruling U31).

Three checks, matching the plan's verification table:

  1  loader on real multi-node data: one key per (dram_i, noc_i), and every
     value equal to the file's own tiles[i].mac_cycles.
  2  loader on the single-node SHAPE (noc_num_steps=1, one core per tile),
     from a synthetic fixture. The real 2048-key arm S corpus does not exist
     until increment 4, so this checks the degenerate shape the loader has to
     accept without waiting on that data.
  3  the identity guard fires: one layer's trace against another layer's
     schedule raises, and the message names what disagrees.

Plus two format-contract checks the loader promises: a duplicate tile key
and a tile count that disagrees with the file's own step counts are both
load-time failures, not KeyErrors from inside combine()'s NoC loop later.

Run: PYTHONPATH=src conda run -n base python tests/test_step_cycles.py

Checks 1 and 3 need the 0823 Stage 2 corpus. Absent, they skip rather than
fail, so the file stays runnable on a fresh clone.
"""
import gzip
import json
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402

from tracegen import ScheduleArtifact, load_step_cycles  # noqa: E402
from nocsim.schedule.decode import schedule_from_strategy  # noqa: E402
from parsers.layer import SNNProb  # noqa: E402

STAGE2 = REPO / "profiling" / "0823_stagewise_verify" / "stage2_weight_trace"
SCHEDULES = STAGE2 / "inputs" / "schedules" / "loas"
TRACES = STAGE2 / "outputs" / "weight_traces" / "loas" / "noc2MiB_node32kb"

# (label, trace_dir, layer). R9 and V8 are the two representative layers.
R9 = ("R9", "resnet19_T4_n5", "layer_09_layer2_0_conv2")
V8 = ("V8", "vgg16_T4_n5", "layer_08_features_27")


def trace_path(combo, sample=0):
    _, trace_dir, layer = combo
    return TRACES / trace_dir / layer / f"sample_{sample:05d}.json.gz"


def schedule_path(combo):
    _, trace_dir, layer = combo
    return SCHEDULES / trace_dir / f"{layer}.json"


def load_artifact_and_schedule(combo):
    """The same pair run_stage3.py will build: the persisted artifact, and
    the Schedule its strategy block decodes to."""
    artifact = ScheduleArtifact(**json.loads(schedule_path(combo).read_text()))
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        yaml.safe_dump(artifact.workload, fh)
        wl = fh.name
    prob = SNNProb(pathlib.Path(wl))
    return artifact, schedule_from_strategy(artifact.result["strategy"], prob)


# ---------------------------------------------------------------- check 1

def test_loads_real_multinode_trace(combo):
    path = trace_path(combo)
    sc = load_step_cycles(path)
    raw = json.load(gzip.open(path, "rt"))

    expected = raw["dram_num_steps"] * raw["noc_num_steps"]
    assert len(sc.by_step) == expected, f"{len(sc.by_step)} keys, expected {expected}"
    assert len(sc.by_step) == len(raw["tiles"]), "a tile was dropped or merged"

    # Every value must be the file's own number, untouched.
    for tile in raw["tiles"]:
        got = sc.by_step[(tile["dram_i"], tile["noc_i"])]
        assert got.mac_cycles == tile["mac_cycles"], (
            f"tile {(tile['dram_i'], tile['noc_i'])}: "
            f"read {got.mac_cycles}, file says {tile['mac_cycles']}"
        )
        assert got.lif_cycles == tile["lif_cycles"]

    # The keys must be the full cross product, not merely the right count.
    want_keys = {(d, n) for d in range(raw["dram_num_steps"])
                 for n in range(raw["noc_num_steps"])}
    assert set(sc.by_step) == want_keys, "keys are not the full step cross product"

    # Identity carried through verbatim.
    assert sc.arch == raw["arch"]
    assert sc.layer_name == raw["layer_name"]
    assert sc.trace_dir == raw["trace_dir"]
    assert sc.sample_idx == raw["sample_idx"]

    macs = [c.mac_cycles for c in sc.by_step.values()]
    print(f"check 1  {combo[0]}: {len(sc.by_step)} keys "
          f"({raw['dram_num_steps']}x{raw['noc_num_steps']}), "
          f"mac_cycles min/median/max = {min(macs)}/{sorted(macs)[len(macs)//2]}/{max(macs)}, "
          f"sum = {sum(macs):,}   OK")


# ---------------------------------------------------------------- check 2

def _fixture(path, *, dram_steps, noc_steps, arch="loas",
             trace_dir="vgg16_T4_n5", layer="layer_08_features_27",
             tiles=None):
    """Write a minimal weight-trace document. Only the fields
    load_step_cycles reads are populated -- the tick/core payload is
    deliberately absent, which is itself part of the contract: this reader
    must not need the addresses."""
    doc = {
        "arch": arch,
        "trace_dir": trace_dir,
        "layer_name": layer,
        "sample_idx": 0,
        "workload_dims": {"KH": 3, "KW": 3, "CIN": 512, "COUT": 512,
                          "HO": 4, "WO": 4, "T": 4, "shape": "snn-layer"},
        "dram_num_steps": dram_steps,
        "noc_num_steps": noc_steps,
        "tiles": tiles if tiles is not None else [
            {"dram_i": d, "noc_i": n, "mac_cycles": 100 + 10 * d + n,
             "lif_cycles": None, "ticks": []}
            for d in range(dram_steps) for n in range(noc_steps)
        ],
    }
    path.write_text(json.dumps(doc))
    return doc


def test_loads_single_node_shape(tmp):
    """noc_num_steps=1: every tile is its own DRAM step, one core each.
    This is the shape arm S produces (measured: V8 single-node is 2048 DRAM
    steps x 1 NoC step x 1 core)."""
    path = tmp / "single_node.json"
    doc = _fixture(path, dram_steps=64, noc_steps=1)
    sc = load_step_cycles(path)

    assert len(sc.by_step) == 64
    assert sc.noc_num_steps == 1
    assert set(sc.by_step) == {(d, 0) for d in range(64)}
    for tile in doc["tiles"]:
        assert sc.by_step[(tile["dram_i"], 0)].mac_cycles == tile["mac_cycles"]
    # Distinct per step, which is the whole point of reading them per tile.
    assert len({c.mac_cycles for c in sc.by_step.values()}) == 64
    print(f"check 2  single-node shape: {len(sc.by_step)} keys, "
          f"noc_num_steps={sc.noc_num_steps}, 64 distinct durations   OK")


# ---------------------------------------------------------------- check 3

def test_guard_fires_on_wrong_layer(trace_combo, schedule_combo):
    sc = load_step_cycles(trace_path(trace_combo))
    artifact, schedule = load_artifact_and_schedule(schedule_combo)
    try:
        sc.check_against(artifact, schedule)
    except ValueError as exc:
        msg = str(exc)
        assert "layer_name" in msg, f"message does not name the layer: {msg}"
        first = msg.splitlines()[1].strip()
        print(f"check 3  {trace_combo[0]} trace vs {schedule_combo[0]} schedule: "
              f"raised, {len(msg.splitlines()) - 1} fields named, first = {first!r}   OK")
        return
    raise AssertionError(
        f"{trace_combo[0]}'s trace passed {schedule_combo[0]}'s schedule guard"
    )


def test_guard_passes_on_matching_pair(combo):
    sc = load_step_cycles(trace_path(combo))
    artifact, schedule = load_artifact_and_schedule(combo)
    sc.check_against(artifact, schedule)  # must not raise
    print(f"check 3b {combo[0]} trace vs its own schedule: passes   OK")


# ------------------------------------------------- format-contract checks

def test_rejects_duplicate_key(tmp):
    path = tmp / "dup.json"
    _fixture(path, dram_steps=2, noc_steps=2, tiles=[
        {"dram_i": 0, "noc_i": 0, "mac_cycles": 1, "lif_cycles": None, "ticks": []},
        {"dram_i": 0, "noc_i": 0, "mac_cycles": 2, "lif_cycles": None, "ticks": []},
        {"dram_i": 1, "noc_i": 0, "mac_cycles": 3, "lif_cycles": None, "ticks": []},
        {"dram_i": 1, "noc_i": 1, "mac_cycles": 4, "lif_cycles": None, "ticks": []},
    ])
    try:
        load_step_cycles(path)
    except ValueError as exc:
        assert "duplicate" in str(exc)
        print("check 4a duplicate (dram_i, noc_i): rejected at load   OK")
        return
    raise AssertionError("a duplicate tile key loaded without error")


def test_rejects_wrong_tile_count(tmp):
    path = tmp / "short.json"
    _fixture(path, dram_steps=4, noc_steps=4, tiles=[
        {"dram_i": 0, "noc_i": 0, "mac_cycles": 1, "lif_cycles": None, "ticks": []},
    ])
    try:
        load_step_cycles(path)
    except ValueError as exc:
        assert "expected 16" in str(exc), str(exc)
        print("check 4b tile count vs 4x4 step counts: rejected at load   OK")
        return
    raise AssertionError("a short tile list loaded without error")


def test_reads_plain_json_and_gzip(tmp):
    """Same document, two encodings, identical result."""
    plain = tmp / "plain.json"
    _fixture(plain, dram_steps=3, noc_steps=2)
    gz = tmp / "gz.json.gz"
    with gzip.open(gz, "wt") as fh:
        fh.write(plain.read_text())
    a, b = load_step_cycles(plain), load_step_cycles(gz)
    assert a == b, "gzip and plain json disagree"
    print("check 4c .json and .json.gz read identically   OK")


# ---------------------------------------------------------------------- main

def main():
    failures = []
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        # Fixture-driven checks always run.
        for fn in (test_loads_single_node_shape, test_rejects_duplicate_key,
                   test_rejects_wrong_tile_count, test_reads_plain_json_and_gzip):
            try:
                fn(tmp)
            except AssertionError as exc:
                failures.append(f"{fn.__name__}: {exc}")

    # Corpus-driven checks skip if the 0823 Stage 2 outputs are absent.
    if not trace_path(R9).exists() or not schedule_path(V8).exists():
        print(f"checks 1 and 3: SKIP, no Stage 2 corpus under {STAGE2}")
    else:
        for combo in (R9, V8):
            try:
                test_loads_real_multinode_trace(combo)
                test_guard_passes_on_matching_pair(combo)
            except AssertionError as exc:
                failures.append(f"real trace {combo[0]}: {exc}")
        try:
            test_guard_fires_on_wrong_layer(R9, V8)
        except AssertionError as exc:
            failures.append(f"guard: {exc}")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
