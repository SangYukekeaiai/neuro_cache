"""Increment 2 of log/2026-08-24-nocsim-per-tile-cycles-plan.md: combine()'s
cycles_by_step branch.

Increment 1 proved the reader; this proves the branch consumes it. Four
things, all reading the produced tc.csv rather than trusting the call:

  A  multi-node, real weight trace: every mac COUNT duration in the CSV
     equals that (dram_i, noc_i)'s mac_cycles from the trace.
  B  the same run differs from the dense baseline, so the table is being
     used and not silently ignored.
  C  single-node, synthetic table: the branch is arm-agnostic. Uses a
     fabricated table because the real arm S corpus lands in increment 4;
     distinct values per step prove per-step charging either way.
  D  a table missing a key raises KeyError rather than charging zero.

Checks 4 and 5 of the plan (dense and live-model paths byte-identical
before and after) are diffs against baselines captured before the edit, so
they are not reproducible from this file alone and are recorded in
EXPLAIN.md instead.

Run: PYTHONPATH=src conda run -n base python tests/test_combine_cycles_table.py
"""
import gzip
import json
import pathlib
import re
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402

from archmodels import ComputeCycles  # noqa: E402
from nocsim.combine import combine  # noqa: E402
from nocsim.schedule.buf_spatial import BufSpatial  # noqa: E402
from nocsim.schedule.decode import schedule_from_strategy  # noqa: E402
from nocsim.schedule.steps import StepInfo  # noqa: E402
from parsers.arch import SNNArch  # noqa: E402
from parsers.bitwidths import SNNBitwidths  # noqa: E402
from parsers.layer import SNNProb  # noqa: E402
from tracegen import load_step_cycles  # noqa: E402

VERIFY = REPO / "profiling" / "0823_stagewise_verify"
MULTI_SCHED = VERIFY / "stage2_weight_trace" / "inputs" / "schedules" / "loas"
MULTI_TRACE = (VERIFY / "stage2_weight_trace" / "outputs" / "weight_traces"
               / "loas" / "noc2MiB_node32kb")
MULTI_ARCH = (VERIFY / "stage1_mip_solver" / "inputs" / "arch"
              / "loas_inst16_node32kb_noc2MiB_pe16.yaml")
SINGLE_SCHED = REPO / "outputs" / "schedules" / "loas" / "vgg16_T4_n5"
SINGLE_ARCH = REPO / "configs" / "arch" / "loas.yaml"

# "# mac_<dram_i>_<noc_i>__count_<node>: COUNT <node> for <N> cycles  dep=[...]"
MAC_LINE = re.compile(
    r"^#\s*mac_(\d+)_(\d+)__count_\d+:\s*COUNT\s+\d+\s+for\s+(\d+)\s+cycles")


def build(schedule_path, arch_path):
    """(prob, arch, bitwidths, schedule) for one persisted schedule."""
    art = json.loads(pathlib.Path(schedule_path).read_text())
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        yaml.safe_dump(art["workload"], fh)
        wl = fh.name
    prob = SNNProb(pathlib.Path(wl))
    schedule = schedule_from_strategy(art["result"]["strategy"], prob)
    return prob, SNNArch(str(arch_path)), SNNBitwidths(str(arch_path)), schedule


def run(schedule, prob, bitwidths, arch, out, **kw):
    gen = combine(schedule, BufSpatial(schedule, prob), StepInfo(schedule, prob),
                  prob, bitwidths, arch=arch, **kw)
    gen.to_file(out)
    return out


def mac_durations(csv_path):
    """{(dram_i, noc_i): {durations seen}} parsed back out of the CSV.

    combine() emits one COUNT per node per step, so a correct run has
    exactly one distinct duration per step -- a set rather than a scalar so
    a bug that charges cores differently is visible instead of hidden by
    last-write-wins.
    """
    found = {}
    for line in pathlib.Path(csv_path).read_text().splitlines():
        m = MAC_LINE.match(line)
        if m:
            d, n, cyc = int(m.group(1)), int(m.group(2)), int(m.group(3))
            found.setdefault((d, n), set()).add(cyc)
    return found


# ------------------------------------------------------------------ check A/B

def test_multinode_real_trace(tmp, tag, sched_rel, trace_rel):
    prob, arch, bw, schedule = build(MULTI_SCHED / sched_rel, MULTI_ARCH)
    assert not arch.single_node, "expected a multi-node arch for this check"

    sc = load_step_cycles(MULTI_TRACE / trace_rel)
    table = run(schedule, prob, bw, arch, tmp / f"table_{tag}.csv",
                cycles_by_step=sc.by_step)
    dense = run(schedule, prob, bw, arch, tmp / f"dense_{tag}.csv")

    got = mac_durations(table)
    want_keys = {(d, n) for d in range(schedule.dram_num_steps)
                 for n in range(schedule.noc_num_steps)}
    assert set(got) == want_keys, (
        f"{tag}: CSV has {len(got)} mac steps, schedule has {len(want_keys)}")

    for key, durations in sorted(got.items()):
        assert len(durations) == 1, f"{tag} step {key}: mixed durations {durations}"
        landed = durations.pop()
        expected = sc.by_step[key].mac_cycles
        assert landed == expected, (
            f"{tag} step {key}: tc.csv charged {landed}, trace says {expected}")
    print(f"check A  {tag}: {len(got)} steps, every COUNT duration equals the "
          f"trace's mac_cycles   OK")

    # check B: the table changed the answer.
    d_vals = {k: v.pop() for k, v in mac_durations(dense).items()}
    t_vals = {k: sc.by_step[k].mac_cycles for k in want_keys}
    assert len(set(d_vals.values())) == 1, (
        "dense should charge one value for the whole layer, got "
        f"{len(set(d_vals.values()))}")
    dense_val = next(iter(set(d_vals.values())))
    assert dense_val not in set(t_vals.values()) or len(set(t_vals.values())) > 1, (
        f"{tag}: table and dense are indistinguishable")
    ratio = dense_val / (sum(t_vals.values()) / len(t_vals))
    print(f"check B  {tag}: dense charges {dense_val:,} every step; table charges "
          f"{min(t_vals.values())}..{max(t_vals.values())} "
          f"({len(set(t_vals.values()))} distinct), dense/mean = {ratio:.1f}x   OK")


# -------------------------------------------------------------------- check C

def test_singlenode_table(tmp, tag, sched_rel):
    """Arm-agnostic: a single_node arch with a table takes the table branch,
    not the live-model branch. Synthetic values, distinct per step."""
    prob, arch, bw, schedule = build(SINGLE_SCHED / sched_rel, SINGLE_ARCH)
    assert arch.single_node, "expected a single-node arch for this check"
    assert schedule.noc_num_steps == 1, "single-node should have one NoC step"

    table = {(d, n): ComputeCycles(mac_cycles=1000 + d, lif_cycles=None)
             for d in range(schedule.dram_num_steps)
             for n in range(schedule.noc_num_steps)}
    out = run(schedule, prob, bw, arch, tmp / f"sn_table_{tag}.csv",
              cycles_by_step=table)

    got = mac_durations(out)
    assert set(got) == set(table), (
        f"{tag}: CSV has {len(got)} mac steps, table has {len(table)}")
    for key, durations in got.items():
        assert durations == {table[key].mac_cycles}, (
            f"{tag} step {key}: charged {durations}, table says "
            f"{table[key].mac_cycles}")
    print(f"check C  {tag} single-node: {len(got)} steps, all charged from the "
          f"table (1000..{1000 + schedule.dram_num_steps - 1})   OK")


# -------------------------------------------------------------------- check D

def test_missing_key_raises(tmp, sched_rel, trace_rel):
    prob, arch, bw, schedule = build(MULTI_SCHED / sched_rel, MULTI_ARCH)
    sc = load_step_cycles(MULTI_TRACE / trace_rel)
    holed = dict(sc.by_step)
    victim = sorted(holed)[len(holed) // 2]
    del holed[victim]
    try:
        run(schedule, prob, bw, arch, tmp / "holed.csv", cycles_by_step=holed)
    except KeyError as exc:
        assert victim == exc.args[0], f"raised on {exc.args[0]}, removed {victim}"
        print(f"check D  a table missing step {victim} raises KeyError, not zero "
              f"cycles   OK")
        return
    raise AssertionError("a table with a missing step produced a CSV anyway")


# ---------------------------------------------------------------------- main

CASES = [
    ("R9", "resnet19_T4_n5/layer_09_layer2_0_conv2.json",
     "resnet19_T4_n5/layer_09_layer2_0_conv2/sample_00000.json.gz"),
    ("V8", "vgg16_T4_n5/layer_08_features_27.json",
     "vgg16_T4_n5/layer_08_features_27/sample_00000.json.gz"),
]


def main():
    if not (MULTI_TRACE / CASES[0][2]).exists():
        print(f"SKIP: no Stage 2 corpus under {MULTI_TRACE}")
        return 0

    failures = []
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        for tag, sched_rel, trace_rel in CASES:
            try:
                test_multinode_real_trace(tmp, tag, sched_rel, trace_rel)
            except AssertionError as exc:
                failures.append(f"multinode {tag}: {exc}")
        for tag, sched_rel in [("V8", "layer_08_features_27.json")]:
            if not (SINGLE_SCHED / sched_rel).exists():
                print(f"check C: SKIP, no single-node schedule at "
                      f"{SINGLE_SCHED / sched_rel}")
                continue
            try:
                test_singlenode_table(tmp, tag, sched_rel)
            except AssertionError as exc:
                failures.append(f"singlenode {tag}: {exc}")
        try:
            test_missing_key_raises(tmp, CASES[0][1], CASES[0][2])
        except AssertionError as exc:
            failures.append(f"missing key: {exc}")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
