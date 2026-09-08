# 0907: two replacement policies

Status: PLAN, awaiting the go-ahead. Nothing in `src/wcache/native` has moved.

Two additions, both as config knobs so that every arm of a sweep differs in one
field and nothing else:

  * `PolicyKind::RRIP`, SRRIP with a 2-bit RRPV
  * `PolicyKind::LFU`, a per-slot reference count

The layout stays `khkw_split`. Section 3 records the two indexing methods that
were scoped for this stage and the measurement that closed them, so the question
does not have to be re-opened from scratch.

## 1. The baseline these are measured against

`profiling/0903_l1_pf_fix/run_sweep.py:29-33`, confirmed against a resolved row
of `profiling/0903_l1_8k/outputs/l1cap_rows.csv`.

| field | value | derived |
|---|---|---|
| `layout` | `khkw_split` | digits `[pos_hi][cout_blk][cin_blk][pos_lo]` |
| `cin_block` / `cout_block` / `weight_bytes` | 16 / 4 / 1 | line 64 B |
| `l1_size_bytes` / `l1_assoc` | 16384 / 8 | 256 lines, 32 sets, 5 index bits |
| `l2_size_bytes` / `l2_assoc` | 524288 / 16 | 8192 lines, 512 sets, 9 index bits |
| `policy` / `l2_policy` | `lru` / follows `policy` | |
| `inclusion` | `non_inclusive` | |
| `l1_mshrs` / `l1_tgts_per_mshr` | 16 / 20 | `l1_demand_reserve` resolves to 1 |
| `l2_mshrs` / `l2_tgts_per_mshr` | 32 / 12 | |
| `l1_latency` / `l1_ii` / `l1_pf_ii` | 0 / 1 / -1 | no second tag port |
| `l2_latency` / `l2_to_l1_latency` / `l2_miss_latency` | 2 / 0 / 24 | |
| `l2_banks` / `l2_ii` / `dram_ii` / `core_accept_ii` | 1 / 1 / 1 / 1 | |
| `prefetch_policy` / `l2_prefetch_policy` | `none` / `none` | |
| cores | 16 | private L1 per core, shared L2 |

Corpus: 31 layers, vgg16_T4_n5 and resnet19_T4_n5, 5 samples each. Every layer
is 3x3, so `KH*KW = 9`. `CIN` and `COUT` are powers of two in [64, 512], every
`CIN` divides by 16 and every `COUT` by 4, and bursts run along COUT with span
4, which is exactly one `cout_block`.

## 2. Where the pressure is, and therefore what a policy can move

Distinct lines a single (tile, core) touches under the baseline layout, and how
they land across the 32 sets and 8 ways, computed on the streams themselves:

| layer | lines per (tile,core) p50 / max | sets reached | lines per set p50 / max | sets over 8 ways |
|---|---|---|---|---|
| V1 `features_3` | 35 / 36 | 32/32 | 1 / 2 | 0% |
| V2 `features_7` | 35 / 36 | 32/32 | 1 / 2 | 0% |
| R1 `layer1_0_conv1` | 36 / 36 | 32/32 | 1 / 2 | 0% |
| R9 `layer2_0_conv2` | 143 / 144 | 32/32 | 4 / 8 | 0% |
| V8 `features_27` | 192 / 288 | 24/32 | 8 / 16 | 4.2% |
| R16 `layer3_0_conv2` | 192 / 288 | 24/32 | 8 / 16 | 4.2% |

A replacement policy changes an outcome only where a set holds more live lines
than it has ways, so this table is also the prediction: **RRIP and LFU should be
indistinguishable from LRU on every layer with `CIN <= 128`, and can move only
the `CIN >= 256` layers, where 4.2% of sets carry up to 16 lines against 8
ways.** An arm that moves V1, V2 or R1 is reporting a bug rather than a policy
effect.

The headline number the baseline already reports at 16 KB is `l1_hit_rate
0.9888` aggregated over the 31 layers, so the room a better policy is competing
for is the remaining 1.1%.

## 3. Why the two indexing methods are closed

Both proposals put 2 bits of `cout_blk` into the 5-bit L1 index. Measured over
all 31 layers, `distinct cout_blk per (tile, core)` is **1**, and a core holds
one block for many consecutive tiles (core 5 of V8 stays on `cout_blk = 40` for
at least its first 12 tiles, matching 128 tiles over the 8 blocks it owns).

So 2 cout bits in the index are 2 bits that cannot change inside a tile,
whichever 2 are chosen, and the tile is left with 3 live index bits:

| layer | arm | sets reached | lines per set p50 / max | sets over 8 ways |
|---|---|---|---|---|
| V2 | `khkw_split` | 32/32 | 1 / 2 | 0% |
| | `[cout_blk low 2][pos_lo 3]` | 8/32 | 4 / 8 | 0% |
| R9 | `khkw_split` | 32/32 | 4 / 8 | 0% |
| | `[cout_blk low 2][pos_lo 3]` | 8/32 | 16 / 32 | 100% |
| V8 | `khkw_split` | 24/32 | 8 / 16 | 4.2% |
| | `[cout_blk low 2][pos_lo 3]` | 6/32 | 32 / 64 | 100% |
| R16 | `khkw_split` | 24/32 | 8 / 16 | 4.2% |
| | `[cout_blk low 2][pos_lo 3]` | 32 / 64 | | 100% |

The low 2 bits of `cout_blk` are the better of the two choices, since the high 2
bits are the top of the core id and never change at all, while the low 2 rotate a
core's 8-set window between tiles. Neither choice changes what one tile can
reach. The only digits measured to vary inside a tile are `cin_blk`, which takes
its full `CIN/16` range in every tile, and `pos`, which takes 4 to 9 of its 9
values, and those are exactly what `khkw_split` indexes on today.

Making a cout bit live inside a tile means changing what a core sweeps per tile,
which is a dataflow change rather than an indexing one.

The second method also widened the line to `[cin 2][kh_kw 8][cout 4]`. With
`KH*KW = 9` the `pos_hi = 1` group holds one real position in its 8 slots, so
the layout addresses `16 * CIN * COUT` element slots for `9 * CIN * COUT` real
weights, which is 43.75% padding, and the line count per (tile, core) rises on
the large layers rather than falling (V8 192 to 394, R16 192 to 462).

## 4. The policies

`ReplacementPolicy::pick_victim` requires order independence (`policy.h:88-101`):
permuting the candidate vector leaves the answer unchanged. Both policies below
meet it with a smallest-slot-id tie-break, which is what `StampPolicy` already
does. `pick_victim` is non-const, which is what lets RRIP age its candidates
there.

**`LfuPolicy`.** One `int64` count per slot, in the flat-vector-indexed-by-SlotId
shape the interface is built for. `on_fill` resets the count to 0, `on_hit`
increments it, `on_invalidate` clears it, and the victim is the minimum count and
then the smallest slot id. The known ceiling is that a pure LFU never ages, so a
line that was hot early can outlive its usefulness; aging is a follow-up only if
the results ask for it.

**`RripPolicy`.** SRRIP with a 2-bit RRPV. `on_fill` inserts at 2, `on_hit` sets
0, `on_invalidate` sets 3. `pick_victim` increments every candidate until one
reaches 3, then takes the smallest slot id at 3. `M` and the insertion value stay
compile-time constants until a sweep asks for them as knobs.

Neither policy reads a set index, a way, an associativity or a line address, so
`cache.h`'s split between the array and the policy holds unchanged and one
implementation serves both levels.

## 5. Increments

Each stops with an erasable `EXPLAIN.md` and waits for "next".

| id | what |
|---|---|
| P1 | `LfuPolicy` in `stamp_policy.h/.cpp` |
| P2 | `RripPolicy` in `stamp_policy.h/.cpp` |
| P3 | Wiring: `PolicyKind::RRIP` and `LFU`, `make_policy`, the shared `policy` and `l2_policy` parse in `config.cpp`, the CSV names in `stats.cpp` |
| P4 | `test_stamp_policy.cpp`: hit, fill and invalidate behaviour for both, the RRPV aging loop, and the permuted-candidate order-independence check `policy.h` requires |

`make_policy` already refuses `PolicyKind::RANDOM` and that stays true, since
`RANDOM` is also the sentinel meaning "`l2_policy` is unset, follow `policy`".

## 6. The sweep

`profiling/0907_index_policy/run_sweep.py`, one grid over `policy` alone:
`{lru, fifo, rrip, lfu}`, all 31 layers, 5 samples, every other field at section
1. `l2_policy` stays unset so both levels move together.

`belady` is already built and is the offline bound, so a fifth arm at
`policy = belady` costs one grid row and turns the comparison into a spread
between LRU and the optimum rather than four numbers with no scale. Section 2 is
the prediction to check the result against.
