# Relax MIP spatial-split V2 validation to best-fit divisor

## Context

`src/snn_cosa/model/constraints/node_level.py::add_pe_spatial_split_constraints`
implements Constraint C: for each `{spatial: N}`-tagged dimension in an
arch's `node_dim_capacity`, it pins that dimension's NodeLevel spatial
extent to *exactly* `N` via a Gurobi equality constraint
(`spatial_sum == log2(N)`), after a hard pre-check ("V2") that raises
`ValueError` unless `N` evenly divides the workload's real dimension size
(`prob.prob_bound[j]`).

The archmodel live-wiring plan's real 28-layer sweep
(`docs/superpowers/plans/2026-07-16-archmodel-live-wiring.md`, Task 6)
surfaced how often this fails against real captured-trace-derived layer
shapes: GustavSNN (`HO: {spatial: 8}`) failed **all 28** layers (real HO
values `30/14/6/2`, none divisible by 8); SpinalFlow and Prosperity
(`COUT: {spatial: 128}`) each failed 2 layers where the real `COUT=64`.
In every case the arch's nominal PE count (`8`, `128`) is the real
hardware's PE count from its source paper — not a free parameter to
retune — so the fix is in how the constraint handles a real dimension
that doesn't happen to be a clean multiple of that count, not in the
declared capacity itself.

## Design

Replace the exact-match requirement with a **best-fit** rule: the
NodeLevel spatial extent becomes the largest divisor of the real
dimension size that does not exceed the arch's declared cap. This covers
both failure shapes already found:

- **Real dimension smaller than the cap** (e.g. `COUT=64` vs. cap `128`):
  effective factor = `64` (use fewer PEs than the array's max width —
  legitimate; not every layer needs to fill the whole array).
- **Real dimension larger than the cap but not a clean multiple**
  (e.g. `HO=30` vs. cap `8`): effective factor = the largest divisor of
  `30` that's `<= 8`, i.e. `6` (`2*3`); `HO=14` vs. cap `8` → `7`.

```python
def _largest_divisor_leq(bound: int, cap: int) -> int:
    for d in range(min(bound, cap), 0, -1):
        if bound % d == 0:
            return d
    return 1
```

**Why this is provably solver-feasible, not just numerically plausible:**
any divisor `d` of `prob_bound[j]` is, by the fundamental theorem of
arithmetic, expressible as the product of a sub-multiset of
`prob.prob_factors[j]`'s own prime factors (the exact same list Constraint
C's Gurobi variables are already built from) — so pinning
`spatial_sum == log2(d)` is always achievable by some real assignment of
those variables. There is no new infeasibility risk from the relaxation
itself, only the removal of a strictness that used to reject cases Gurobi
could otherwise have solved.

**Why nothing downstream needs to change:** traced
`schedule.spatial_factors` (produced by `decode()`/`schedule_from_strategy()`,
`nocsim/schedule/decode.py`) end to end — it is read back from which `x`
variables Gurobi *actually* turned on (`x[(i,j,n,0)].X > 0.5`), never from
the arch's nominal declared cap. `BufSpatial.num_pes`
(`nocsim/schedule/buf_spatial.py:77-89`) and `combine.py`'s NoC `X`/`Y`
sizing both read `schedule.spatial_factors` the same way. So once
Constraint C pins to the effective (possibly-smaller) factor, every
downstream consumer picks it up automatically — this change is contained
entirely to `node_level.py`.

**Non-regression:** when `F_j` already divides `prob_bound[j]` exactly
(every config that passed before this change), `_largest_divisor_leq`
returns `F_j` itself unchanged — this is a strict superset of previously
solvable cases, never a behavior change for one that already worked.

**Observability:** log (at existing `logger.debug`/`.info` level, matching
this file's own convention) whenever the effective factor is less than
the nominal cap — e.g. `"COUT: using 64/128 PEs (real dim=64 doesn't
divide evenly by 128)"` — this underutilization is itself a
locality/efficiency-relevant fact for the paper, not just solver trivia.

**V1 unaffected:** `parsers/arch.py::_validate_spatial_split` (the
parse-time product-of-nominal-caps `<= num_pes` check) is unrelated and
untouched — it validates the arch's own declared capacity is physically
buildable, independent of any specific workload.

## Non-goals

- No change to any arch YAML's declared `{spatial: N}` values.
- No change to `parsers/arch.py`, `decode.py`, `buf_spatial.py`,
  `combine.py`, or any archmodel plugin — confirmed contained to
  `node_level.py`.
- No retroactive re-verification of every existing pilot's already-solved
  schedules — this only ever expands what's solvable, never changes an
  already-passing case's result.

## File-level changes

```
src/snn_cosa/model/constraints/node_level.py   MODIFIED
```

## Verification plan

1. Unit-style scratch script: `_largest_divisor_leq` against hand-picked
   cases (`(64,128)->64`, `(30,8)->6`, `(14,8)->7`, `(128,128)->128`,
   `(6,8)->6`, `(2,8)->2`).
2. Zero-regression: re-solve at least one already-passing config from
   each of the 5 archs' existing sweeps (e.g. PTB/LoAS's already-OK rows)
   and confirm byte-identical solved schedules before/after.
3. Re-run the full `scripts/sweep_archmodel_layers.py` 5-arch x 28-layer
   sweep; confirm GustavSNN, SpinalFlow, and Prosperity's previously-ERROR
   rows now solve (`status: OK`), and record the new summary CSVs for
   review, per this project's standing verification-output convention.