"""eventsim: a dependency must delay its successor, not merely release it.

Before this was fixed, EventSim.h read a transaction's start time from
`get_actor_free(actor)` alone and discarded the predecessor's finish time
at the completion queue. Dependency edges therefore controlled dispatch
ORDER but not TIME, and every actor's timeline packed gaplessly from 0. A
COUNT whose input arrived at cycle 1000 still ran at cycle 0.

The failure is invisible whenever the dependency and the resource agree
(a chain on one actor serializes correctly either way), which is why it
survived: it only shows up when the successor sits on a DIFFERENT actor,
which is exactly the DRAM-load-then-compute shape of every real run.

Each check drives the compiled binary on a hand-written tc.csv, so it
tests the shipped artifact rather than a reimplementation of its rules.

Row format (see Transaction.h): tc_id,actor,op,size,srcs,dests,deps
op 2 is COUNT, whose `size` IS its cycle count.

Run: conda run -n base python tests/test_eventsim_deps.py
"""
import json
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
BINARY = REPO / "src/nocsim/eventsim/eventsim"


def run(rows, tmp, name):
    csv = tmp / f"{name}.csv"
    csv.write_text("".join(r + "\n" for r in rows))
    r = subprocess.run(
        [str(BINARY), str(csv), "--X", "4", "--Y", "4",
         "--dram-port", "33", "--dram-latency", "17"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(f"{name}: eventsim rc={r.returncode}\n{r.stderr}")
    return json.loads(r.stdout)


def check_cross_actor_delay(tmp):
    """The case the old code got wrong: successor on its own actor."""
    res = run(["0,5,2,1000,5,,", "1,6,2,10,6,,0"], tmp, "cross_actor")
    assert res["total_cycles"] == 1010, (
        f"successor ran at 0 instead of 1000: total_cycles={res['total_cycles']}")
    assert res["count_cycles"] == 1010
    print("check K  cross-actor dep: successor starts at 1000, total=1010   OK")


def check_same_actor_unchanged(tmp):
    """Dependency and resource agree, so this was already right and must
    stay right."""
    res = run(["0,5,2,1000,5,,", "1,5,2,10,5,,0"], tmp, "same_actor")
    assert res["total_cycles"] == 1010, res
    print("check L  same-actor chain: unchanged at 1010   OK")


def check_no_deps_still_overlap(tmp):
    """Independent work on separate actors must still run concurrently.
    A fix that serialized everything would also pass check K."""
    res = run(["0,5,2,1000,5,,", "1,6,2,10,6,,"], tmp, "no_deps")
    assert res["total_cycles"] == 1000, (
        f"independent transactions were serialized: {res['total_cycles']}")
    print("check M  no deps: actors 5 and 6 overlap, total=1000   OK")


def check_fan_in_takes_max(tmp):
    """Two predecessors: the successor waits for the LATER one, not the
    first listed. Guards against reading deps[0] only."""
    res = run(["0,5,2,100,5,,", "1,6,2,500,6,,", "2,7,2,10,7,,0 1"],
              tmp, "fan_in")
    assert res["total_cycles"] == 510, (
        f"fan-in waited for the wrong predecessor: {res['total_cycles']}")
    print("check N  fan-in of 100 and 500: successor starts at 500, total=510   OK")


def check_chain_accumulates(tmp):
    """A three-deep chain across three actors accumulates, proving the
    finish time propagates rather than being read once."""
    res = run(["0,5,2,100,5,,", "1,6,2,200,6,,0", "2,7,2,300,7,,1"],
              tmp, "chain3")
    assert res["total_cycles"] == 600, (
        f"chain did not accumulate: {res['total_cycles']}")
    print("check O  three-actor chain 100+200+300: total=600   OK")


def main():
    if not BINARY.exists():
        print(f"SKIP: no eventsim binary at {BINARY} (cd src/nocsim/eventsim && make)")
        return 0
    failures = []
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        for fn in (check_cross_actor_delay, check_same_actor_unchanged,
                   check_no_deps_still_overlap, check_fan_in_takes_max,
                   check_chain_accumulates):
            try:
                fn(tmp)
            except AssertionError as exc:
                failures.append(f"{fn.__name__}: {exc}")
    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
