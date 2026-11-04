# How the weight-trace generator handles each architecture

Sections 1-7 cover the pipeline, Prosperity and GustavSNN.
[Section 8](#8-loas-ptb-and-spinalflow) covers LoAS, PTB and SpinalFlow, and
compares all five.

Written against commit `67420ba`. Every output below comes from running the code,
with the binaries built in a scratch copy, except where a line says it was only
read from the code. The paths and line numbers in this document were later
re-pointed to the src-layout tree at `0c55f2f`; the recorded outputs are still
the ones produced at `67420ba`.

## The short version

The input is the captured spike trace plus a solved schedule. No Prosperity or
GustavSNN spike trace exists: both models replay the **spikes captured for LoAS**
(`examples/input_trace/loas/`) and re-derive which weights their own hardware would fetch.

1. The schedule says which slice of the layer each **tile** covers.
2. A small C++ program per arch walks that slice of spikes and applies the arch's
   dataflow rule to decide which weights are fetched, and on which cycle (**tick**).
3. Python merges the results. Cycle counts go to a `.json.gz` file for `nocsim`.
   Addresses go to a binary WCTS stream for `cachesim`.

The two archs differ only in step 2:

|  | Prosperity | GustavSNN |
|---|---|---|
| A tile holds | one input channel, all ticks, a block of output pixels | **all** resident input channels, one tick, a block of output pixels |
| Saves work by | reusing an earlier row's result, fetching only the difference | fetching a weight once per HO row, however many WO positions need it |
| Timing | one fetch per cycle | up to 8 HO rows fetch in parallel |
| Fetches per tick | always 1 per core | often several |

**Known problem: `--stream` crashes on GustavSNN.** Cycle-count generation works,
but no GustavSNN address stream can be written today. See
[section 6](#6-what-does-not-work-today).

## 1. The data flow

```
python -m lays.weight_trace_gen gen --arch ...  cli.py:128 (files) or :301 (--stream)
  check_schedule_matches_trace                  layer shape must match meta.json
  load_schedule -> tiles                        weight_trace.py:23, src/lays/nocsim/schedule/tiles.py:98
  load_layer_trace -> [T, B, Cin, Hin, Win]     trace.py:39
  reconstruct_samples                           weight_trace.py:163, picks the arch's bridge
    native_bridge.py                            writes trace.bin + task.bin, runs the binary
      prosperitygen / gustavgen                 loops sample -> tile, calls reconstruct_sample
      write_tick_grouped                        tick_output.h:34, groups addresses by tick
    assemble_layer_traces                       weight_trace.py:109, merges cores per tile
  save_step_cycles   -> sample_NNNNN.json.gz    src/lays/nocsim/step_cycles.py:27, cycles only
  stream_weight_trace -> WCTS on stdout         src/lays/cachesim/stream.py:178, addresses
```

The Python side is shared. The per-arch parts are only `ProsperityGen.h`,
`GustavGen.h`, and the 12-int tile record each bridge packs
(`prosperity/native_bridge.py:32`, `gustavsnn/native_bridge.py:37`).

**What an address means.** A fetch is `(kh, kw, cin, cout_start, cout_end)`: the
weights at kernel position `(kh, kw)`, input channel `cin`, for output channels
`[cout_start, cout_end)`. It is a burst of many weights, and it never records
HO or WO, because the same weight serves every output pixel.

**Padding.** Both archs use the same mapping from output pixel to input pixel,
and treat out-of-bounds positions as no spike:

```
hin = ho + kh - 1        win = wo + kw - 1        (3x3 kernel, pad = 1)
```

## 2. From schedule to tiles

`iter_node_tiles` (`src/lays/nocsim/schedule/tiles.py:98`) turns the schedule into one
`NodeTileSpec` per `(dram_i, noc_i, core_id)`:

- `node_bound[dim]` is how many values of `dim` the tile spans: the dim's total
  divided by its DRAM-temporal, NoC-temporal and core-spatial factors (`:128-132`).
- `tile_offset[dim]` is where the tile starts in that dim, stepped as a mixed-radix
  counter over the temporal loops (`:154-161`).

Real example, `vgg16` `layer_07_features_24`, whose shape is
`KH=3 KW=3 CIN=256 COUT=512 HO=4 WO=4 T=4`:

|  | Prosperity | GustavSNN |
|---|---|---|
| DRAM loops, outer to inner | `COUTx64 -> CINx256` | `COUTx64 -> Tx4` |
| Tiles | 64 x 256 = **16384** | 64 x 4 = **256** |
| One tile spans | CIN 1, COUT 8, HO 4, WO 4, T 4 | CIN 256, COUT 8, HO 4, WO 4, T 1 |
| Tile 1 starts at | `CIN=1, COUT=0` | `T=1, COUT=0` |
| Last tile starts at | `CIN=255, COUT=504` | `T=3, COUT=504` |

## 3. Prosperity: reuse an earlier row, fetch the difference

Source: `reconstruct_sample`, `prosperity/ProsperityGen.h:90`.

Each `(ho, wo, t)` in the tile becomes a **row**: a bitmask of which
kernel positions see a spike, with `bit = kh*3 + kw`. If a row's bits contain all
of an earlier row's bits, the hardware can reuse that earlier result and only has
to add the difference.

The algorithm:

1. Build every row's bitmask, in `(ho, wo, t)` order (`:99-123`).
2. Sort rows by popcount, keeping original order on ties (`:126-130`).
3. For each row, scan backward through processed rows for the most recent one
   that is a subset: `(prev & ~bits) == 0` (`:148-155`).
4. The row's `pattern` is `bits ^ prev`, or just `bits` if no subset exists.
5. Each set bit in `pattern` is one fetch and one cycle (`:160-172`).

So `mac_cycles` always equals the number of fetches, and every tick has exactly
one fetch per core.

### Worked example

Input channel `cin=0`, tile `HO=2, WO=2, T=1`, `COUT=[0,8)`, so rows are written `(ho,wo)`:

```
          win 0 1 2 3
    hin 0     0 0 1 0
    hin 1     0 1 1 0
    hin 2     1 1 0 0
    hin 3     0 0 0 0
```

Row bits, using the padding rule. For `(0,1)`, the spike at `(hin 0, win 2)` is
`kh=1, kw=2`, which is bit 5:

| Row `(ho,wo)` | Bits | Popcount |
|---|---|---|
| (0,0) | {8} | 1 |
| (0,1) | {5,7,8} | 3 |
| (1,0) | {5,7,8} | 3 |
| (1,1) | {2,4,5,6,7} | 5 |

Processing in sorted order, which here is also the original order:

| Row | Prefix found | Pattern | Fetches `(kh,kw)` | Ticks |
|---|---|---|---|---|
| (0,0) | none | {8} | (2,2) | 0 |
| (0,1) | (0,0) = {8} | {5,7} | (1,2), (2,1) | 1-2 |
| (1,0) | (0,1), identical | {} | none | none |
| (1,1) | none, since bit 8 rules out every earlier row | {2,4,5,6,7} | (0,2), (1,1), (1,2), (2,0), (2,1) | 3-7 |

Actual `prosperitygen` output, 12 spike bits reduced to 8 fetches:

```
mac 8
tick 0 (2,2,0,0,8)     tick 1 (1,2,0,0,8)     tick 2 (2,1,0,0,8)     tick 3 (0,2,0,0,8)
tick 4 (1,1,0,0,8)     tick 5 (1,2,0,0,8)     tick 6 (2,0,0,0,8)     tick 7 (2,1,0,0,8)
```

(1,2) and (2,1) are fetched twice, because a reused row does not stop a later row
with no valid prefix from fetching the same weight. The cache sees those repeats,
which is why order matters: output follows **popcount order, not pixel order**.

## 4. GustavSNN: one fetch per HO row, HO rows in parallel

Source: `reconstruct_tile` (`gustavsnn/GustavGen.h:82`) and `addresses_and_ticks`
(`:132`).

**Step 1, build a line list for each HO row.** A *line* is one `(kh, kw, cin)`
triple. It is kept if any WO position in the tile sees a spike there (`:105-114`).
WO is OR'd away, which is where the saving comes from. Lines are ordered by `kh`,
then `kw`, then `cin`.

**Step 2, group HO rows into waves of up to `PE_COUNT_MAX = 8`** (`:35`, `:142-152`).
A wave lasts as long as its longest row:

```
wave_len      = max(number of lines in each row of the wave)
tick(line j)  = wave_start + j
mac_cycles    = sum of wave_len over all waves
```

Rows in a wave advance together, so several fetches share a tick, and a short row
just stops early.

### Worked example 1: same spikes, plus a second channel

Same `cin=0` grid as above, plus `cin=1` with spikes at `(0,0)` and `(1,1)`. The
tile has `HO=2, WO=2, CIN=2`, so both channels are resident, and `COUT=[0,8)`.

Row `ho=0` has 7 lines, and `kh=0` is skipped because `hin=-1`:

```
(1,0,1) (1,1,1) (1,2,0) (2,1,0) (2,1,1) (2,2,0) (2,2,1)
```

Row `ho=1` has 10 lines:

```
(0,0,1) (0,1,1) (0,2,0) (1,1,0) (1,1,1) (1,2,0) (1,2,1) (2,0,0) (2,1,0) (2,2,0)
```

There are two rows, so one wave with `wave_len = 10`. Actual `gustavgen` output,
17 fetches in 10 cycles:

```
mac 10
tick 0 (1,0,1,0,8) (0,0,1,0,8)
tick 1 (1,1,1,0,8) (0,1,1,0,8)
tick 2 (1,2,0,0,8) (0,2,0,0,8)
tick 3 (2,1,0,0,8) (1,1,0,0,8)
tick 4 (2,1,1,0,8) (1,1,1,0,8)
tick 5 (2,2,0,0,8) (1,2,0,0,8)
tick 6 (2,2,1,0,8) (1,2,1,0,8)
tick 7 (2,0,0,0,8)
tick 8 (2,1,0,0,8)
tick 9 (2,2,0,0,8)
```

`ho=0` finishes after tick 6, so ticks 7-9 hold only `ho=1`.

### Worked example 2: more rows than PEs

Nine HO rows, where row 0 has 2 lines, row 3 has 1, row 8 has 3, and the rest
have none. This one uses a tile with `kh_n=1, kw_n=3, WO offset 1`:

```
wave 1 = rows 0-7, wave_len 2, starts at tick 0
wave 2 = row 8,    wave_len 3, starts at tick 2

mac 5
tick 0 (0,0,0,0,8) (0,0,0,0,8)     rows 0 and 3 fetch the same weight
tick 1 (0,1,0,0,8)                 row 0
tick 2 (0,0,0,0,8)                 row 8
tick 3 (0,1,0,0,8)                 row 8
tick 4 (0,2,0,0,8)                 row 8
```

Tick 0 lists the same address twice. Nothing deduplicates across rows, so the
cache sees both. Real data does this too. The first ticks of `layer_07` tile 0
begin:

```
tick 0: (1,0,0,0,8) (0,0,0,0,8) (0,0,1,0,8) (0,0,3,0,8)
tick 2: (1,0,7,0,8) (0,0,7,0,8) (0,0,6,0,8) (0,0,6,0,8)
```

## 5. Real numbers

`vgg16`, sample 0, all tiles of each layer:

| Layer | Arch | Tiles | Fetch bursts | MAC cycles | Bursts per cycle | Weights per burst |
|---|---|---|---|---|---|---|
| `layer_04_features_14` | Prosperity | 1024 | 32,614 | 32,614 | 1.00 | 128 |
| `layer_04_features_14` | GustavSNN | 128 | 588,416 | 88,512 | 6.65 | 8 |
| `layer_07_features_24` | Prosperity | 4096 | 43,364 | 43,364 | 1.00 | 128 |
| `layer_07_features_24` | GustavSNN | 256 | 672,768 | 204,992 | 3.28 | 8 |

Compare weights, not bursts, because the burst widths differ by 16x. On
`layer_07`, Prosperity touches about 5.55M weights (43,364 x 128) and GustavSNN
about 5.38M (672,768 x 8).

Prefix reuse cuts Prosperity's fetches by 2.52x on `layer_04` (82,232 spike bits
to 32,614) and 1.49x on `layer_07` (64,728 to 43,364).

A separate Python reimplementation of the Prosperity rules matched the C++
addresses, order and cycle counts on every tile of both layers. GustavSNN's output
was checked only against the hand-traced examples above.

**Assumptions the code does not check.** Neither binary receives a KH or KW offset,
Prosperity reads one `cin`, and GustavSNN reads one `t`, so a schedule that split
those dims differently would be silently misread. All 124 cached schedules (31 layers x
{Prosperity, GustavSNN} x {single-node, multinode}) satisfy the assumptions: KH and
KW are 3 with no offset, Prosperity's CIN is 1, GustavSNN's T is 1 and its CIN is
the full channel count. That count predates Prosperity's full T residency, so those
Prosperity schedules must be re-solved to get it.

## 6. What does not work today

### `--stream` crashes on GustavSNN (real bug, not fixed)

```
$ python -m lays.weight_trace_gen gen --arch gustavsnn ... --stream
ValueError: write_tile_frame: local_tick 0 not strictly ascending in core 0 of tile 0 (previous 0)
exit code 1, 293 bytes already written to stdout
```

- **Cause:** WCTS requires strictly ascending ticks within a core
  (`src/lays/cachesim/stream.py:120`, and `docs/atlas/cachesim_native.md` section
  1.7, WCTS v2 wire format). GustavSNN's
  parallel PEs are not cores, so its same-tick fetches all land on one core. The
  merge at `src/lays/cachesim/stream.py:168` flattens them into equal ticks.
- **Reach:** it failed on all four single-node layers tried (`layer_01`, `04` and
  `10` through the writer, `07` through the CLI) and on multinode `layer_07`. Any
  tile with two fetches in one tick on a core triggers it. Prosperity streams fine
  in the same tests, because it never has two fetches in one tick on a core.
- **Why tests miss it:** the repo's demo and tests do not stream real GustavSNN
  output. The only GustavSNN fixture is the legacy file that
  `examples/cachesim/manifest.json:155-157` marks as unable to drive the engine.
  `tests/test_stream_writer.py:116-124` asserts this rejection on purpose.
- **Direction for a fix:** either give each HO-row PE its own core id, or teach the
  format and the reader about same-tick bursts. The first keeps WCTS unchanged but
  changes `n_cores` and `spatial_factors`. Neither has been tried.

The Prosperity stream was checked only as far as the writer. I did not feed it
through `cachesim`.

### Neither arch runs out of the box

Generation works once these are handled:

| Obstacle | Where | What to do |
|---|---|---|
| Binaries not built | `make build` only builds LoAS (`Makefile:8`) | `make -C src/lays/weight_trace_gen/prosperity` and the same for `gustavsnn` |
| No schedules in the repo | `examples/schedules/` has only `loas/` | Solve with Gurobi, or reuse `~/projects/neuro_cache/outputs/schedules/` |
| Directory name mismatch | Those are under `vgg16_T4_all`, the traces under `vgg16_T4_n5` | Symlink, as below. The layer shapes matched in all checks run |
| Default sample set fails | `--n-samples 100` draws indices up to 9999, and the in-repo traces have 5 samples: `IndexError: index 18 is out of bounds for axis 1 with size 5` | Pass `--sample-start 0 --sample-count 1` |
| `scripts/pipeline.py` refuses them | Only LoAS has a nocsim arch (`scripts/pipeline.py:45`) | Call `python -m lays.weight_trace_gen` directly |

From reading the code, not from running it: the borrowed schedules also carry
`trace_dir: vgg16_T4_all`, so `StepCycles.check_against`
(`src/lays/nocsim/step_cycles.py:115`) would reject them against a `vgg16_T4_n5` file in
`nocsim`. `check_schedule_matches_trace` compares only the layer shape, so it does
not confirm that a borrowed schedule was solved with this repo's current mapspace.

### Misleading comments

- `prosperity/ProsperityGen.h:36-38` and `prosperity/__init__.py:14` describe `k=16` (KH=KW=4)
  and m=256. Real layers here have `k=9`, because only 3x3 convs are replayable
  (`trace.py:26`), and `m` varies with the schedule (16 on `layer_07`).
- Both headers say they are ports "kept in lockstep" with Python modules such as
  `reconstruct.py`. Those files no longer exist, so the C++ is the source of truth.

## 7. Reproducing this

```bash
make -C src/lays/weight_trace_gen/prosperity
make -C src/lays/weight_trace_gen/gustavsnn     # binaries are git-ignored

SC=$(mktemp -d)                                 # schedule cache with the expected names
for a in prosperity gustavsnn; do
  mkdir -p $SC/$a
  ln -s ~/projects/neuro_cache/outputs/schedules/$a/vgg16_T4_all $SC/$a/vgg16_T4_n5
done

python -m lays.weight_trace_gen gen --arch prosperity \
  --trace-dir vgg16_T4_n5 --layer layer_07_features_24 \
  --schedule-cache $SC --sample-start 0 --sample-count 1 --out-dir /tmp/wt
```

This writes
`/tmp/wt/prosperity/vgg16_T4_n5/layer_07_features_24/sample_00000.json.gz`. To
print addresses for a small hand-made case, as in sections 3 and 4:

```python
import numpy as np
from weight_trace_gen import NodeTileSpec
from weight_trace_gen.weight_trace import reconstruct_samples
from parsers.layer import DIM_CIN as C, DIM_COUT as O, DIM_HO as H, DIM_KH as KH, DIM_KW as KW, DIM_T as T, DIM_WO as W

trace = np.zeros((1, 1, 2, 4, 4), np.uint8)     # [T, B, Cin, Hin, Win]
trace[0, 0, 0] = [[0,0,1,0], [0,1,1,0], [1,1,0,0], [0,0,0,0]]
trace[0, 0, 1, 0, 0] = trace[0, 0, 1, 1, 1] = 1

def run(arch, cin_n):
    tile = NodeTileSpec(0, {H:2, W:2, KH:3, KW:3, C:cin_n, O:8, T:1}, {}, True)
    for t in reconstruct_samples(arch, trace, [tile], [0], "x", "y", {}, 1)[0].tiles:
        print(arch, "mac", t.mac_cycles)
        for e in t.ticks:
            print(" tick", e.tick, [a for c in e.cores for a in c.weight_addresses])

run("prosperity", 1)    # 8 fetches, 8 cycles
run("gustavsnn", 2)     # 17 fetches, 10 cycles
```

## 8. LoAS, PTB and SpinalFlow

These three share everything in section 1, and differ from Prosperity and GustavSNN
in the tile shape. **One tile is one output pixel `(ho, wo)`**, with all resident
input channels and all 4 timesteps. Their tile record is the same 11 ints
(`loas/native_bridge.py:31`), and they read the same spikes through the same
padding rule.

The question each one answers about that pixel's spikes:

| Arch | Source | Fetch a weight when | `mac_cycles` |
|---|---|---|---|
| LoAS | `loas/LoASGen.h:64` | it spikes at **any** timestep: once per `(kh, kw, cin)` | number of fetches |
| PTB | `ptb/PTBGen.h:87` | same as LoAS | `max(fetches, compute_cycle_count(...))` |
| SpinalFlow | `spinalflow/SpinalFlowGen.h:56` | **every** spike, so once per `(t, kh, kw, cin)` | number of fetches |

All three fetch at most one address per tick, so they all stream.

### LoAS: skip silent positions

Walk `kh`, then `kw`, then `cin`. If that input fired at any timestep, emit one
fetch (`loas/LoASGen.h:73-105`). The burst covers every timestep, so T never appears in
the address.

### PTB: LoAS's addresses, different timing

**Pass 1** is LoAS's silence removal, and addresses come only from this pass
(`ptb/PTBGen.h:153-162`), in the same order. **Pass 2** walks the survivors and merges a
line with the next one when their spike vectors never overlap (`:131-149`). A merged
pair counts as one group, a line is merged at most once, and `ln` is the group count.
`ln` only feeds the cycle formula:

```
active_rows = min(cout_n, 16)
active_cols = min(ceil(T / 8), 8)
last_col    = T - 8 * (active_cols - 1)
compute     = max(ln + active_rows + T,  ln + active_rows + active_cols + last_col)
mac_cycles  = max(number of fetches, compute)
```

With `T=4` and `cout_n=16`, this reduces to `compute = ln + 21`. So the systolic
overhead only sets the cycle count on tiles with few fetches.

### SpinalFlow: one fetch per spike, in time order

Walk `t` first, then `kh`, `kw`, `cin` (`spinalflow/SpinalFlowGen.h:69-76`), and emit a fetch
for every spike. A weight is fetched again each time its input fires, and `t` is
dropped from the address, so repeats are visible to the cache. Of the five, this is
the only order that groups fetches by timestep.

### Worked example

One output pixel `(ho=1, wo=1)`, `CIN=2`, `T=4`, `COUT=[0,16)`. At this pixel
`kh = hin` and `kw = win`. Spikes:

| Line `(kh, kw, cin)` | t0 | t1 | t2 | t3 |
|---|---|---|---|---|
| (1,1,0) | 1 | 1 | 0 | 0 |
| (1,1,1) | 1 | 0 | 0 | 0 |
| (1,2,0) | 0 | 0 | 1 | 0 |
| (2,2,1) | 0 | 1 | 0 | 1 |

PTB's Pass 2 goes as follows:

1. (1,1,0) and (1,1,1) overlap at t0, so (1,1,0) stands alone.
2. (1,1,1) and (1,2,0) never overlap, so they merge.
3. (2,2,1) stands alone, giving `ln = 3`.

`compute` is then `max(3+16+4, 3+16+1+4) = 24`.

Actual output from the three binaries, addresses shown as `(kh,kw,cin)`:

```
loas        mac 4   (1,1,0) (1,1,1) (1,2,0) (2,2,1)
ptb         mac 24  (1,1,0) (1,1,1) (1,2,0) (2,2,1)
spinalflow  mac 6   (1,1,0) (1,1,1) (1,1,0) (2,2,1) (1,2,0) (2,2,1)
```

### Real numbers

`vgg16`, sample 0, all tiles. All three streamed through the writer without error.

| Layer | Arch | Tiles | Fetch bursts | MAC cycles | Weights per burst | Weights touched |
|---|---|---|---|---|---|---|
| `layer_04_features_14` | LoAS | 1024 | 282,608 | 282,608 | 16 | 4.52M |
| `layer_04_features_14` | PTB | 1024 | 282,608 | 282,624 | 16 | 4.52M |
| `layer_04_features_14` | SpinalFlow | 128 | 82,232 | 82,232 | 128 | 10.53M |
| `layer_07_features_24` | LoAS | 512 | 263,360 | 263,360 | 16 | 4.21M |
| `layer_07_features_24` | PTB | 512 | 263,360 | 263,360 | 16 | 4.21M |
| `layer_07_features_24` | SpinalFlow | 64 | 64,728 | 64,728 | 128 | 8.29M |

- **PTB barely differs from LoAS here.** On these layers the schedules and burst
  counts match, and PTB's timing adds 16 cycles on `layer_04` and none on `layer_07`.
  PTB's window logic is also barely exercised: `TW_SIZE` is 8 and these traces have
  `T=4`, so `active_cols` is always 1. Its cache behaviour will look like LoAS until
  a longer trace exists.
- **The spike counts cross-check.** SpinalFlow's fetch counts equal the raw spike
  bits measured separately for Prosperity in section 5 (82,232 and 64,728), as they
  should, since both count every spike seen through every output pixel's window.
  These two counts are the only cross-check on these three archs, beyond the
  hand-traced example above.

### All five side by side

| Arch | Tile covers | Same weight fetched again? | Parallel fetches per core | Cycle count |
|---|---|---|---|---|
| LoAS | 1 pixel, all CIN, all T | no, within a tile | no | fetches |
| PTB | 1 pixel, all CIN, all T | no, within a tile | no | `max(fetches, ln + overhead)` |
| SpinalFlow | 1 pixel, all CIN, all T | yes, per spike | no | fetches |
| Prosperity | pixel block, 1 CIN, all T | yes, across rows | no | fetches |
| GustavSNN | pixel block, all CIN, 1 T | yes, across HO rows | **yes**, up to 8 | sum of wave lengths |

### Assumptions and running them

These three read one pixel and receive no KH or KW offset. A schedule with `HO` or
`WO` bound above 1 would silently use only the first pixel, and one with no HO or WO
offset would raise `KeyError` in the bridge. All 198 cached schedules for these
archs, single-node and multinode, have `HO=WO=1`, KH and KW of 3 with no offset, and
HO and WO offsets present.

- **LoAS** is the supported path: `make build` builds it, `examples/schedules/loas/`
  tracks four layers, and `scripts/pipeline.py` runs it. I did not re-run that
  pipeline for this doc.
- **PTB and SpinalFlow** have the same obstacles as the table in section 6, and the
  commands in section 7 work with `--arch ptb` or `--arch spinalflow` once built
  with `make -C src/lays/weight_trace_gen/<arch>`. Their `--stream` output was checked
  only as far as the writer, single-node, not through `cachesim`.
