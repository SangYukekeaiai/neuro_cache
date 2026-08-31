"""Increment 3 of log/2026-08-24-nocsim-per-tile-cycles-plan.md: sim.py's
B179 reader fix, the cycles_by_step threading, and --weight-trace.

Everything here goes through the CLI (a subprocess), not through combine():
increment 2 already proved the branch, so what is left to prove is that a
user-facing invocation reaches it. Six checks:

  E  --weight-trace on a real Stage 2 sample: every mac COUNT duration in
     the produced tc.csv equals that (dram_i, noc_i)'s mac_cycles from the
     trace. This is plan check 6, driven the way Stage 3 will drive it.
  F  both schedule JSON shapes load -- a ScheduleArtifact (nests the solver
     result under "result") and a raw `mip_solver solve` document (IS the
     result) -- and produce byte-identical CSVs. The artifact half is what
     B179 blocked.
  G  the same schedule run without --weight-trace still charges the dense
     static value, so the flag is what changes the answer.
  H  a trace whose keys do not cover the schedule exits 2 with "simulation
     failed" rather than charging zero cycles.
  I  a trace with the wrong tile count is rejected by the loader, before any
     CSV is written.
  J  --simulate accepts an artifact too (the second place that unwrapped
     "result"), and eventsim's count_cycles moves with the flag.

Run: PYTHONPATH=src conda run -n base python tests/test_sim_weight_trace.py
"""
import gzip
import json
import pathlib
import re
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src"

VERIFY = REPO / "profiling" / "0823_stagewise_verify"
ARTIFACT = (VERIFY / "stage2_weight_trace" / "inputs" / "schedules" / "loas"
            / "vgg16_T4_n5" / "layer_08_features_27.json")
TRACE = (VERIFY / "stage2_weight_trace" / "outputs" / "weight_traces" / "loas"
         / "noc2MiB_node32kb" / "vgg16_T4_n5" / "layer_08_features_27"
         / "sample_00000.json.gz")
LAYER = (VERIFY / "stage1_mip_solver" / "inputs" / "workloads"
         / "vgg16_T4_all__layer_08_features_27.yaml")
ARCH = (VERIFY / "stage1_mip_solver" / "inputs" / "arch"
        / "loas_inst16_node32kb_noc2MiB_pe16.yaml")

# "# mac_<dram_i>_<noc_i>__count_<node>: COUNT <node> for <N> cycles  dep=[...]"
MAC_LINE = re.compile(
    r"^#\s*mac_(\d+)_(\d+)__count_\d+:\s*COUNT\s+\d+\s+for\s+(\d+)\s+cycles")


def cli(out, *extra, schedule=ARTIFACT):
    """Run the CLI in-process (same interpreter, so no conda env question)
    and return (exit_code, stdout+stderr)."""
    from nocsim.sim import main
    import contextlib, io
    argv = ["--schedule", str(schedule), "--layer", str(LAYER),
            "--arch", str(ARCH), "--out", str(out), *[str(a) for a in extra]]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = main(argv)
    return code, buf.getvalue()


def mac_durations(csv_path):
    """{(dram_i, noc_i): {durations}} parsed back out of the CSV."""
    found = {}
    for line in pathlib.Path(csv_path).read_text().splitlines():
        m = MAC_LINE.match(line)
        if m:
            d, n, cyc = int(m.group(1)), int(m.group(2)), int(m.group(3))
            found.setdefault((d, n), set()).add(cyc)
    return found


def trace_mac_cycles(path):
    with gzip.open(path, "rt") as fh:
        doc = json.load(fh)
    return ({(t["dram_i"], t["noc_i"]): t["mac_cycles"] for t in doc["tiles"]},
            doc["dram_num_steps"], doc["noc_num_steps"])


# -------------------------------------------------------------------- check E

def test_number_lands(tmp):
    want, dram_steps, noc_steps = trace_mac_cycles(TRACE)
    out = tmp / "table.csv"
    code, log = cli(out, "--weight-trace", TRACE)
    assert code == 0, f"CLI exited {code}:\n{log}"
    assert f"{len(want)} per-step entries" in log, (
        f"CLI did not report the table it loaded:\n{log}")

    got = mac_durations(out)
    assert set(got) == set(want), (
        f"CSV has {len(got)} mac steps, trace has {len(want)}")
    assert len(want) == dram_steps * noc_steps, (
        f"trace covers {len(want)} of {dram_steps}x{noc_steps} steps")
    for key in sorted(got):
        assert got[key] == {want[key]}, (
            f"step {key}: tc.csv charged {got[key]}, trace says {want[key]}")
    vals = set(want.values())
    print(f"check E  {len(got)} steps via the CLI, every COUNT duration equals "
          f"the trace's mac_cycles ({min(vals)}..{max(vals)}, "
          f"{len(vals)} distinct)   OK")
    return out


# -------------------------------------------------------------------- check F

def test_both_json_shapes(tmp):
    raw = tmp / "raw_solver.json"
    raw.write_text(json.dumps(json.loads(ARTIFACT.read_text())["result"]))
    assert "result" not in json.loads(raw.read_text()), "raw doc still wrapped"

    a_out, r_out = tmp / "shape_artifact.csv", tmp / "shape_raw.csv"
    for out, sched, what in ((a_out, ARTIFACT, "artifact"),
                             (r_out, raw, "raw solver doc")):
        code, log = cli(out, schedule=sched)
        assert code == 0, f"{what} exited {code}:\n{log}"
    assert a_out.read_bytes() == r_out.read_bytes(), (
        "the two schedule JSON shapes produced different CSVs")
    print(f"check F  ScheduleArtifact and raw solver JSON both load and agree "
          f"byte-for-byte ({a_out.stat().st_size:,} B)   OK")
    return a_out


# -------------------------------------------------------------------- check G

def test_dense_still_dense(tmp, dense_csv, table_csv):
    dense = mac_durations(dense_csv)
    vals = {v for durs in dense.values() for v in durs}
    assert len(vals) == 1, (
        f"no --weight-trace should charge one static value, got {len(vals)}")
    assert dense_csv.read_bytes() != table_csv.read_bytes(), (
        "--weight-trace produced the same CSV as the dense path")
    want, _, _ = trace_mac_cycles(TRACE)
    dense_val = next(iter(vals))
    ratio = dense_val / (sum(want.values()) / len(want))
    print(f"check G  without the flag every step is charged {dense_val:,} "
          f"(dense/mean = {ratio:.1f}x), and the two CSVs differ   OK")


# -------------------------------------------------------------------- check H

def test_key_mismatch_fails(tmp):
    """Right tile count, wrong keys: the loader has nothing to object to, so
    this must surface out of combine()'s KeyError as a nonzero exit."""
    with gzip.open(TRACE, "rt") as fh:
        doc = json.load(fh)
    doc["tiles"][0]["noc_i"] = doc["noc_num_steps"] + 99   # out of range
    bad = tmp / "bad_keys.json"
    bad.write_text(json.dumps(doc))

    out = tmp / "bad_keys.csv"
    code, log = cli(out, "--weight-trace", bad)
    assert code == 2, f"expected exit 2, got {code}:\n{log}"
    assert "simulation failed" in log, f"unexpected message:\n{log}"
    assert not out.exists(), "a CSV was written from a mismatched table"
    print(f"check H  a table missing step (0, 0) exits 2 and writes no CSV   OK")


# -------------------------------------------------------------------- check I

def test_bad_tile_count_fails(tmp):
    with gzip.open(TRACE, "rt") as fh:
        doc = json.load(fh)
    doc["tiles"] = doc["tiles"][:-1]
    bad = tmp / "short.json"
    bad.write_text(json.dumps(doc))

    out = tmp / "short.csv"
    code, log = cli(out, "--weight-trace", bad)
    assert code == 2, f"expected exit 2, got {code}:\n{log}"
    assert "error loading weight trace" in log, f"unexpected message:\n{log}"
    assert not out.exists(), "a CSV was written from a short table"
    print(f"check I  a trace one tile short is rejected by the loader   OK")


# -------------------------------------------------------------------- check J

def test_simulate_on_artifact(tmp):
    binary = SRC / "nocsim" / "eventsim" / "eventsim"
    if not binary.exists():
        print(f"check J  SKIP, eventsim not built at {binary}")
        return
    counts = {}
    for tag, extra in (("dense", ()), ("table", ("--weight-trace", TRACE))):
        code, log = cli(tmp / f"sim_{tag}.csv", "--simulate", *extra)
        assert code == 0, f"--simulate ({tag}) exited {code}:\n{log}"
        m = re.search(r"^count_cycles\s*:\s*(\d+)", log, re.M)
        assert m, f"no count_cycles in eventsim output ({tag}):\n{log}"
        counts[tag] = int(m.group(1))
    assert counts["dense"] != counts["table"], (
        f"eventsim reported the same count_cycles either way: {counts}")
    print(f"check J  --simulate loads the artifact; count_cycles "
          f"dense={counts['dense']:,} table={counts['table']:,} "
          f"({counts['dense'] / counts['table']:.1f}x)   OK")


# ---------------------------------------------------------------------- main

def main():
    for p in (ARTIFACT, TRACE, LAYER, ARCH):
        if not p.exists():
            print(f"SKIP: missing {p}")
            return 0

    failures = []
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        table_csv = None
        try:
            table_csv = test_number_lands(tmp)
        except AssertionError as exc:
            failures.append(f"check E: {exc}")
        dense_csv = None
        try:
            dense_csv = test_both_json_shapes(tmp)
        except AssertionError as exc:
            failures.append(f"check F: {exc}")
        if dense_csv and table_csv:
            try:
                test_dense_still_dense(tmp, dense_csv, table_csv)
            except AssertionError as exc:
                failures.append(f"check G: {exc}")
        for name, fn in (("check H", test_key_mismatch_fails),
                         ("check I", test_bad_tile_count_fails),
                         ("check J", test_simulate_on_artifact)):
            try:
                fn(tmp)
            except AssertionError as exc:
                failures.append(f"{name}: {exc}")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(SRC))
    sys.exit(main())
