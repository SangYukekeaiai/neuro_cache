# 2026-09-03: is there a hot cin? Measured on the weight trace itself

`run.py` decodes the WCTS streams directly and counts bursts per `cin`. No
simulator: a burst is emitted when input channel `cin` spikes, so the per-cin
burst count is the per-channel spike density the weight stream inherits.

Four layers, five samples each (V8, V9, R9, R16), 53.3M bursts.

## Answer: no. There is skew, and it is not usable.

| tag | max/mean | CV | Gini | entropy vs flat | top 10% of cins hold |
|---|---|---|---|---|---|
| V8  | 2.64 | 0.542 | 0.290 | 0.978 | 21.8% |
| V9  | 1.32 | 0.279 | 0.158 | 0.993 | 13.2% |
| R9  | 3.21 | 0.640 | 0.320 | 0.969 | 25.6% |
| R16 | 1.64 | 0.395 | 0.226 | 0.986 | 16.0% |

A flat layer would put 10.0% in its top 10%. Three facts kill it:

1. **No dead channels.** Every cin is referenced in every layer except three of
   R16's 512. There is no cold tail to evict and no hot head to pin.
2. **The skew is below the line granularity.** `khkw_split` groups 16 cins per
   line, and averaging over 16 neighbours erases it: max/mean falls to
   1.13-1.30, Gini to 0.041-0.089, and the hottest 10% of *blocks* hold
   10.5-15.7%. The cache never sees a cin, it sees a cin block.
3. **The hot set is per-image, not per-layer.** Cross-sample Spearman on the
   per-cin counts is 0.005-0.95, mean 0.32-0.65. A static top-k chosen
   leave-one-out (no oracle) captures 13.1-25.3% at k=10% and 32.8-43.6% at
   k=25% -- barely above k itself, which is what picking at random gets.

So a cin-indexed hot-line policy, pinning, or a skew-aware partition has
nothing to work with. Locality along cin is *sequential* (the `cin_blk +1`
lead measured on 08-31), not *frequency* -- which is why the prefetcher is the
right instrument and a hot-set cache is not.

Run: `conda run -n base python profiling/0903_hot_cin/run.py`
Self-check: `... run.py --demo`. Every file's walk is asserted against its own
WCTS trailer (burst count and byte count).

## Tile scope: `run.py --tiles`

The layer-wide count averages over 128 tiles, so it can only see a cin that is
hot *everywhere*. Recut per tile, over all (tile, sample) pairs.

| tag | cin present in a tile | max/mean | Gini | spearman(t, t+1) | adaptive top-10% |
|---|---|---|---|---|---|
| V8  | 74.1% | 1.96 | 0.304 | 0.576 | 21.4% (oracle 26.0) |
| V9  | 95.9% | 1.27 | 0.173 | 0.643 | 12.3% (oracle 13.2) |
| R9  | 65.7% | 2.12 | 0.337 | 0.811 | 30.2% (oracle 32.4) |
| R16 | 83.6% | 1.38 | 0.205 | 0.728 | 14.5% (oracle 16.4) |

"adaptive top-10%" is the realizable policy: the hot set is chosen on tile
`t-1` and applied to tile `t`, never on the tile it is about to serve. Flat is
10%.

**At cin granularity, a hot cin exists at tile scope and is predictable.**
Unlike the layer-wide cut, the skew is real (Gini up to 0.34), it persists into
the next tile (rho 0.58-0.81), and the adaptive choice lands within 1-5 points
of the oracle. R9 is the strong case: 10% of the cin axis carries 30% of a
tile's references, picked with no oracle.

**Three facts still stop it from paying.**

1. **The cache does not index a cin, it indexes a 16-cin block.** Averaged over
   the block, the same adaptive top-10% captures 11.4 / 10.5 / 16.8 / 11.4%
   against a flat 10%. Only R9 keeps anything, and 25% capture is 27-32%
   against a flat 25% everywhere. The skew lives entirely below the line.
2. **No cin is ever referenced twice inside a tile.** `(tile, core, kh, kw,
   cin)` has a maximum repeat count of **1**, measured on V8 and R9. So within
   a tile "hot" can never mean "will be used again soon" -- a hot cin is hot
   only *across* tiles. A retention policy has no intra-tile reuse to protect.
3. **The 5-12 touches a line does get per tile are not a hot cin.** They come
   from the 16 *different* cins packed into that one line, each firing once.
   That is spatial packing, the same mechanism the `cin_blk +1` prefetcher
   already exploits, arriving under a different name.

Verified rather than assumed, on V8 and R9: burst span is always 4 and
cout-aligned, so one burst is exactly one line; each core holds exactly one
cout run_start for a whole tile, so `(tile, core, kh, kw, cin_block)` names one
line. The line model checks out against the layer total: 9 x 32 x 128 = 36,864
distinct lines, the count the 08-31 prefetch plan quotes.

## One thing this turned up that is not about cin

A tile touches only **1,930-3,200 distinct lines**, 0.2-0.4x the 8,192 lines a
512 KB L2 holds, and a core holds its cout block for 16 consecutive tiles. That
sits oddly beside `l2_hit_rate` 0.00% on all 31 layers. It is a trace-side
count and not a simulated one, so it is a question and not yet a contradiction
-- the 0831 reuse tool (`profiling/0831_reuse_distance/reuse_tool.cpp`) run at
tile scope is what would settle it.

Run: `conda run -n base python profiling/0903_hot_cin/run.py --tiles`

## Trace-only reuse: `run.py --reuse`

No cache is modelled. The reference order is the one the trace states (tiles in
order, ticks in order, the 16 cores of a tick together -- verified: at every
tick all 16 cores fire the same `(kh, kw, cin)` at 16 different cout blocks).
The metric is the exact **gap in references** between consecutive touches of
the same line. A gap of `g` spans at most `g` distinct lines, so `gap < C`
*proves* a fully-associative C-line cache holds it. Sample 0 of each layer.

| tag | refs | distinct lines | compulsory | per-core immediate repeat | shared gap p50 |
|---|---|---|---|---|---|
| V8  | 2,597,632 | 36,864 | 1.42% | **84.23%** | 16 |
| V9  | 4,995,072 | 36,864 | 0.74% | **91.80%** | 16 |
| R9  | 1,382,144 |  4,608 | 0.33% | **82.13%** | 16 |
| R16 | 1,969,728 | 18,432 | 0.94% | **89.60%** | 16 |

**82-92% of a core's references are to the line it just referenced.** Not a
near line, the same line, gap exactly 1. One register catches them; no
associativity, no capacity, no policy. And the shared stream's gap is exactly
`n_cores = 16`, because the 16 cores interleave one reference each between a
core's two touches -- so a 17-line shared buffer catches the same reuse.

This is a cross-check on the tile numbers, not a new claim: a line touched `k`
times back to back gives a repeat fraction `(k-1)/k`, and the measured mean
touches per tile (6.06 / 12.10 / 5.00 / 9.76) predict 83.5 / 91.7 / 80.0 /
89.7%. Two independent passes over the trace agree to within a point.

**The mechanism is not hotness.** Consecutive ticks walk `cin, cin+1, ...`, and
16 consecutive cins share one line, so the line repeats until the walk leaves
the block. That is the same spatial packing section 3 of the tile scope names.

**So the hot-cin question is moot at the design level.** A hot-cin policy sorts
the 15.8% of references that are not already a repeat of the immediately
preceding one, and it sorts them by a signal that vanishes at block
granularity. The lever this trace actually offers is capturing the repeat.

Window unions confirm there is no capacity wall behind it: 16 consecutive tiles
touch **4,608** distinct lines (2,304 for R9), against the 8,192 a 512 KB L2
holds. Compulsory references are 0.33-1.42% of the stream.

**One number to reconcile.** These are trace-side counts, so they do not
contradict a simulated result by themselves, but they do not sit easily beside
the recorded `l1_hit_rate` 0.00% with `l1_accesses == l1_fills == 2,597,632`,
nor beside "47.37% of V8's L2 references are compulsory" (the trace has 36,864
distinct lines in a 2.6M reference stream, so 1.42%). Worth checking what
counts as an access on each side before either number is used again.

Run: `conda run -n base python profiling/0903_hot_cin/run.py --reuse`

## Reuse TIMES of one cin inside one tile: `run.py --reuse-times`

Not the distance -- the count. How many times is a single cin referenced
within a single tile, over every live (tile, cin) pair of all five samples.

| tag | reuse times mean | p50 | p90 | max | min | = cout blocks x (kh,kw) |
|---|---|---|---|---|---|---|
| V8  | 51.1 | 48 | 96  | 144 | 16 | 16.0 x 3.19 |
| V9  | 78.8 | 80 | 144 | 144 | 16 | 16.0 x 4.93 |
| R9  | 57.3 | 48 | 112 | 144 | 16 | 16.0 x 3.58 |
| R16 | 73.0 | 64 | 128 | 144 | 16 | 16.0 x 4.56 |

**Every cin that appears in a tile is reused, and heavily: 51-79 times on
average, never fewer than 16, against a ceiling of 16 cores x 9 kernel
positions = 144.** 100% of live (tile, cin) pairs are touched more than once.
This is the opposite of the layer-wide picture, and it is the number the
indexing question actually rests on.

The count factors exactly, because `(tile, core, kh, kw, cin)` never repeats:

```
reuse times  =  distinct cout blocks (16, one per core)  x  distinct (kh, kw) (3.2 - 4.9)
```

**And khkw_split scatters all of it.** kh, kw and the cout block are all in the
address, so each of those 51-79 touches is a different line: one cin's traffic
spreads over 51-79 lines and the reuse any one line gets *from that cin* is
exactly **1.00**. The 6-12 touches a line does collect come from the other 15
cins sharing its block, never from repetition of one cin.

**What the grouping would expose.** Holding the reference stream fixed and only
regrouping addresses, if (kh, kw) moved into the line offset -- one line
covering all 9 kernel positions of a (cin, cout block) -- the same touches
collapse from 51-79 lines onto **16**, one per cout block, and per-cin line
reuse rises from 1.00 to **3.19 / 4.93 / 3.58 / 4.56**. The 16 cout blocks are
irreducible: different cores, genuinely different weights. So 3.2-4.9x is the
whole of what the layout is currently throwing away, and the (kh,kw) axis is
where it sits.

This is a regrouping of the measured addresses, not a simulation and not a
proposal: a line holding 9 (kh,kw) x 4 cout x 1 byte is 36 bytes, so any real
version of it has to settle line size and padding against the cin packing that
currently yields the 82-92% immediate-repeat stream. Those two want opposite
things from the same 64 bytes, and that trade is the actual design question.

Run: `conda run -n base python profiling/0903_hot_cin/run.py --reuse-times`
