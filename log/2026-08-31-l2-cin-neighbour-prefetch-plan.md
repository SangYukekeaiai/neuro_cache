# 2026-08-31: an L2 cin-neighbour prefetcher

Authority for adding a prefetch policy at the **L2**. Implementation lands in
`src/wcache/native/`; the live board is `profiling/0831_l2_prefetch/PROGRESS.md`.

Supersedes the cout-neighbour draft written earlier today, which the trace
measurements in section 2 rejected before any code was written.

## 1. What is being built

On an L2 reference to the line holding `[cin b*16 .. b*16+15, cout c*4 .. c*4+3]`,
issue prefetches for the same cout block at the adjacent **cin** blocks,
`b - 1` and `b + 1`. Whichever falls outside `[0, n_cin_blocks)` is not issued.
Distance is a knob, `l2_prefetch_distance`, and its **default is 1**, meaning the
two immediate neighbours.

The lines are installed in the L2 alone. No core waits on them.

## 2. Why cin, measured rather than assumed

Four candidate neighbours were scored on `V8_s00000.wcts` by decoding the stream
directly. The metric is **lead in first-touch order**, which is the compulsory
miss stream the L2 actually sees, at V8's 3.63 cycles per L2 reference against a
24-cycle `l2_miss_latency`, so 6.6 references of lead is the minimum that hides
anything, and 8,192 lines is what 512 KB holds.

| target | pairs | lead, lines | cycles | hides the miss | survives 512 KB |
|---|---|---|---|---|---|
| **`cin_blk +1`** | 35,712 | **16** | **58** | yes | yes, by 500x |
| `pos +1` | 32,768 | 512 | 1,861 | yes | yes, by 16x |
| `cout_blk +1` | 36,576 | 4,608 | 16,748 | yes | marginal |
| `cout_blk +8` | 34,560 | 1 | 4 | no, arrives late | not applicable |

Three facts decided it:

- **`cin_blk +1` is where the workload goes next.** Inside a tile a core holds
  one cout block for all 822 of its bursts and walks `cin_blk 0..31`, so the
  next cin block is imminent by construction rather than by luck.
- **`cout_blk +8` is beside the workload, not ahead of it.** All 16 cores fire
  on the same `(kh, kw, cin)` each tick at cout blocks
  `[0, 8, 16, ... 120]`, and a block and its `+8` neighbour are co-present at
  the same `(tile, tick)` in **93.8%** of cases. That prefetch would find a
  matching L2 entry already allocated by another core's demand.
- **`cout_blk +1` is 16 tiles away.** A core holds one cout block for exactly 16
  tiles, and 16 x 20,294 demands per tile is the 324,704 measured. Its span
  against capacity is between 4,608 and 9,728 fills, bracketing 8,192, so it is
  bistable and needs its own capacity sweep. It stays as a later arm.

Coverage is the fourth reason: 35,712 of the layer's 36,864 distinct lines have
a `cin+1` partner, **96.9%**.

## 3. On the `-1` direction, which is built and measured separately

`cin_blk -1` has a lead of **-16 lines**: in the median case that line was used
58 cycles ago, so the prefetch arrives after the fact and is waste. The policy
is built with both directions because that is the specification, and
`l2_pf_issued_up` / `l2_pf_issued_down` are counted separately with their own
timely counts, so the `-1` half is judged on its own evidence rather than
averaged into the total. If it measures as predicted, dropping it is a
one-line config change and not a rewrite.

## 4. Why a prefetcher is the instrument, and what it can reach

`l2_hit_rate` is **0.00% on all 31 layers** of the 31-layer run, maximum 0.00%
anywhere in the set. The reuse-distance work explains it: every L2 stack
distance sits above the 8,192 lines 512 KB holds, and 47.37% of V8's L2
references are compulsory.

Belady's MIN cannot touch a compulsory miss, which is why the Belady plan's
ceiling is 52.63%. A prefetcher can, because it does not require the line to
have been referenced before. Each converted miss is worth the 22 cycles between
`l2_miss_latency` 24 and `l2_latency` 2.

## 5. Where it hooks, and the one invariant that moves

The existing `Prefetcher` (`include/wcache/prefetcher.h`) does not fit and must
not be bent to fit. It sits at the L1, is driven by `(CoreId, BurstIndex)` out
of `E_Issue`, and asks `n_bursts_in_tile`. This policy is driven by a **line
address** at a different level and knows nothing of cores or bursts. It is a
sibling interface, `L2Prefetcher`, for the reason `block_pack.h` gives for
`KhkwSplitMapper` being a sibling rather than a subclass: a class deriving from
another in order to disagree with most of it hides its differences behind the
other's correctness.

**The invariant that moves.** `phaseC-EXPLAIN.md:1044` records why
`l2_demand_reserve` went inert:

> Every request the L2 sees holds an L1 entry, so `is_prefetch_at_issue` is
> false there, so `has_slot` always takes the `free > 0` branch and the reserve
> is never consulted.

with `is_prefetch_at_issue(r) = !r.demand && r.mshr1 == nullptr` and
`I6: r.level == L2 <=> r.mshr1 != nullptr`.

An L2-originated prefetch is **the first request in the design that reaches the
L2 with `demand == false` and `mshr1 == nullptr`**. It is exactly the population
the reserve was written for and never received. Therefore:

- `I6` is restated as **a request that can WAIT at the L2 holds an L1 entry**.
  An L2 prefetch never waits: it is dropped at issue exactly as an L1 prefetch
  is, so it needs no L1 entry and joins no wait index.
- **`l2_demand_reserve` becomes live** and is the budget N16 requires. It
  returns as a knob rather than as a new invention, and the refusal of its name
  at `config.cpp:187` is removed, its stated reason now being false.

The merge path needs nothing new: the prefetch allocates an L2 MSHR entry, and a
later demand for that line forwards from the L1 and attaches to it as a target.
That existing matching-entry path is what makes a prefetch timely rather than
merely early.

## 6. The trigger, and the one subtlety that decides whether it works

**Trigger on an L2 MISS by a DEMAND request**, not on every reference.

Triggering on every reference is what the L1 prefetcher does and it is what the
artifact measured costing between 37% and 90% at 64-byte lines, with 92% of
requests dropped as already resident. Every one of those spent a port slot
before the array was probed.

Miss-triggering alone has a defect that must be fixed in the same unit: the
chain dies after one step. Line `b` misses and prefetches `b+1`; when `b+1` is
demanded it now **hits**, so it triggers nothing, and `b+2` is never fetched.

The fix is tagged prefetching: **one `prefetched` bit per L2 line**, set when a
prefetch fills it and cleared on the first demand hit, and a demand hit on a
line whose bit is set triggers the next prefetch. That keeps the chain running
at one prefetch per line rather than one per reference.

A prefetch never triggers a prefetch directly, so no cascade exists.

## 6b. What a prefetch consumes, which is everything a demand consumes below the L1

A prefetch that costs nothing is a wish, not a simulation. `prefetcher.h` is
already explicit that an L1 prefetch goes "through a REAL L1 port slot", and the
artifact's finding that L1 prefetching costs between 37% and 90% at 64-byte
lines is entirely that slot: `stall_l1_port` went from 0 to 2.44 million
core-cycles. The L2 policy is held to the same standard.

An L2 prefetch **takes**:

| Resource | Model | Note |
|---|---|---|
| L2 bank port slot | `Port{l2_ii}` on `bank_of(line)` | reserved exactly as a demand probe reserves it |
| L2 MSHR entry | `l2_mshrs` | bounded by `l2_demand_reserve`, section 5 |
| DRAM port slot | `Port{dram_ii}` | on the miss, which today is every prefetch |
| DRAM bytes | `dram_bytes` | counted, and reported |
| An L2 way on fill | the victim is evicted | the pollution cost, visible as demand misses that were hits before |

An L2 prefetch **does not take** an L1 port slot or an L1 MSHR entry, because it
never touches the L1. That is the same fact as `mshr1 == nullptr` in section 5,
seen from the resource side.

A prefetch never waits and is never refused, so it contributes to no stall
counter itself. It shows up instead as **demands stalling longer**, in
`stall_l2_port` and `stall_channel`, which is the honest place for it.

**What that costs, measured on V8 at the best config.** The L2 sees 77,824
probes over 282,854 cycles, so at `l2_ii = 1` the L2 port and the DRAM port are
each **27.5% occupied** today.

| Variant | added DRAM accesses | total | port | traffic |
|---|---|---|---|---|
| tagged, one prefetch pair per LINE (U4) | 73,728 | 151,552 | 53.6% | 1.95x |
| untagged, one pair per REFERENCE | 155,648 | 233,472 | 82.5% | 3.00x |
| ideal floor, every line fetched once | | 36,864 | 13.0% | 0.47x |

This is the quantitative reason U4 exists rather than being an optimisation:
tagging halves the traffic and keeps the DRAM port near half occupancy instead
of near saturation.

**A consequence worth recording in advance.** The artifact found `l2_banks`
inert, and gave the reason: "at the sweep's best point the L2's port-contention
stall is exactly zero, there is no queue to split". At 53.6% or 82.5% occupancy
there is a queue. **`l2_banks` may become a live axis for the first time under
this policy**, so it is swept alongside rather than pinned at 1.

## 7. The mapper owns the address arithmetic

The policy must not know that CIN is a digit at stride `n_pos_lo` under
`khkw_split` and at a different stride under `block_pack`. `AddressMapper` gains

```cpp
// The line `delta` blocks along `a` from `line`, or nothing when that steps
// outside the layer. Throws std::out_of_range for a line outside
// [0, num_lines()), std::logic_error for an Axis outside the enumerators.
virtual std::optional<LineId> neighbour(LineId line, Axis a,
                                        std::int32_t delta) const = 0;
```

Under `KhkwSplitMapper` this is `blk = (line / digit_stride(CIN)) % digit_radix(CIN)`,
a bounds test on `blk + delta`, then `line + delta * digit_stride(CIN)`. All
three mappers implement it, so a layout-control run answers instead of throwing.

This is also what keeps `pos +1` and `cout_blk +1` one enum value away rather
than a second implementation.

## 8. Config surface

```
l2_prefetch_policy    none | neighbour        default none
l2_prefetch_axis      cin | pos | cout        default cin
l2_prefetch_distance  d >= 0, issues +-1..+-d default 1
l2_prefetch_down      bool, issue the -d side default true
l2_demand_reserve     resurrected, the budget default lines_per_burst
```

`l2_prefetch_policy = neighbour` with `l2_prefetch_distance = 0` throws, matching
the existing rule that `next_burst` at distance 0 throws rather than quietly
meaning none.

The L1 prefetcher stays independent and stays **off** for this study, since
mixing it in would confound a policy the artifact already measured as costly at
64-byte lines.

## 9. Stats

Mirroring the L1 counters, which already satisfy "the outcomes plus the drop
reasons sum to `pf_issued`":

```
l2_pf_issued  l2_pf_timely  l2_pf_late  l2_pf_wasted
l2_pf_dropped_array_hit  l2_pf_dropped_matching  l2_pf_dropped_no_slot
l2_pf_dropped_reserve  l2_pf_coverage  l2_pf_coverage_ceiling
```

plus the pair section 3 needs: `l2_pf_issued_up`, `l2_pf_issued_down` and their
timely counts.

## 10. Units

One function per increment, then an erasable `EXPLAIN.md`, then stop and wait,
per the standing pipeline.

| Unit | Increment | Exit criterion |
|---|---|---|
| U1 | `AddressMapper::neighbour` on all three mappers | V2 |
| U2 | `L2Prefetcher` interface and `none` | V1 |
| U3 | `NeighbourPrefetcher`, miss-triggered, the drop rules at the L2, `I6` restated | V6 |
| U4 | The `prefetched` bit and hit-retriggering | V7 |
| U5 | `l2_demand_reserve` resurrected as the budget, `config.cpp:187` removed | V5 |
| U6 | The `l2_pf_*` counters | V4 |
| U7 | The sweep over 31 layers, and the artifact | V3 |

## 11. Verification

- **V1, the standing gate.** `l2_prefetch_policy = none` reproduces
  `profiling/0831_all_layer_streams/outputs/all_layers_vs_nocsim.csv` to the
  digit on all 31 layers. A policy that changes a run it is switched off in is
  not a policy.
- **V2.** `neighbour` against `line_of`: for every coordinate of a small shape,
  `neighbour(line_of(c), CIN, +1)` equals `line_of(c with cin_blk + 1)`, and
  returns nothing exactly at the last block. Exhaustive, no sampling.
- **V3, the result.** `l2_hit_rate` leaves 0.00%. It is currently exactly zero
  on all 31 layers, so any nonzero value is attributable to this policy alone.
- **V4, accounting.** `l2_pf_issued` equals outcomes plus drops, and
  `l2_pf_issued_up + l2_pf_issued_down == l2_pf_issued`.
- **V5, the budget.** In-flight L2 prefetch entries never exceed
  `l2_mshrs - l2_demand_reserve`, and `l2_pf_dropped_reserve` is nonzero at a
  reserve that binds, proving the knob is live rather than inert a second time.
- **V6, no cascade and no waiting.** No prefetch ever appears on an L2 wait
  index, and no prefetch is issued from a prefetch fill. Both are assertions in
  the debug build, not comments.
- **V7, the chain.** With the `prefetched` bit on, `l2_pf_issued` is within a
  small factor of the distinct-line count 36,864 for V8, rather than of the
  77,824 reference count. That is the difference between one prefetch per line
  and one per reference, and it is what U4 exists to produce.
- **V8, the resource accounting.** Every prefetch reserves an L2 bank port slot
  and, on a miss, a DRAM slot; `dram_accesses` rises by the issued count minus
  the drops, and no prefetch ever reserves an L1 port slot. Checked by
  differencing the counters against a `none` run on the same stream, not by
  reading the code.
- **V9, the prediction on record.** Section 2 predicts `cin_blk +1` timely and
  `cin_blk -1` waste. The run either confirms it or falsifies the measurement
  method, and both are worth knowing before the cout arm is attempted.

## 12. Out of scope

Prefetching into the L1, adaptive or feedback-directed degree, cross-core
prefetch, and any change to the L1 prefetcher. The `pos` and `cout` axes are
reachable by config but are not this plan's headline; `cout` additionally needs
an `l2_size_bytes` sweep that section 2 shows is unnecessary for `cin`.

## 13. Risk to state plainly

A 16-line lead is enough to hide 24 cycles and no more. This policy buys the
miss-to-hit difference on the lines it converts and nothing beyond it, so the
expected effect is a real but bounded cycle reduction rather than the large
`l2_hit_rate` jump the 4 MB capacity probe produced. If the measured gain is
small, that is the policy working as designed and the `cout` arm is the one
with the larger ceiling.
