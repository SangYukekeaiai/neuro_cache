# wcache debugging instruments

Two separate CSV files, produced by two separate flags on `wcache_run`, kept
apart on purpose:

| file | one row per | read it to answer |
|---|---|---|
| `*_cache_state.csv` | slot transition | what is IN the caches, and when that changed |
| `*_line_trace.csv` | residency episode | what happened TO an **L1** line while it was resident |

Neither changes what the engine computes. Verified by diffing the results row
from a run with both attached against one with neither: identical through every
simulated column, with only `sim_wall_seconds` moving.

The generated `.csv` and `.txt` are gitignored; a whole layer is a few hundred
megabytes. `to_txt.py` renders either CSV as aligned columns for reading by eye,
and takes `--rows N` to cut the head off a long one.

Regenerate the tile-0 pair, which is what is on disk now:

```
S=profiling/0823_stagewise_verify/stage4_wcache
BIN=src/wcache/native/build/release/wcache_run
OUT=debug/wcache_instruments

$BIN --config $OUT/C2_block_pack.json \
     --trace  $S/inputs/streams/V8_s00000.wcts \
     --arm cache --tier instruments --run-id V8-C2-block_pack --header \
     --cache-state $OUT/tile0_cache_state.csv --cache-state-tile 0 \
     --line-trace  $OUT/tile0_line_trace.csv  --line-trace-tile 0 \
     > $OUT/V8_C2_block_pack_row.csv

python3 $OUT/to_txt.py $OUT/tile0_cache_state.csv $OUT/tile0_cache_state.txt
python3 $OUT/to_txt.py $OUT/tile0_line_trace.csv  $OUT/tile0_line_trace.txt
python3 $OUT/to_txt.py $OUT/tile0_cache_state.csv $OUT/tile0_cache_state_first2000.txt --rows 2000
python3 $OUT/to_txt.py $OUT/tile0_line_trace.csv  $OUT/tile0_line_trace_first2000.txt  --rows 2000
```

The line trace is **L1 only** by default. An L1 episode and an L2 episode for
the same line are filled at the same instant and differ only in how long they
survive, so carrying both doubles the file and interleaves two populations whose
residencies are not comparable. `--line-trace-level both` (or `l2`) brings the
L2 back; the cache-state log always keeps both levels, so the L2's side of the
story is there either way.

### Cutting it down

| filter | what it keeps | tile 0 | whole layer |
|---|---|---|---|
| none | everything | | 10.0 M state rows, 5.0 M episodes |
| `--cache-state-core 0` / `--line-trace-core 0` | one core's L1 plus the shared L2 | | 5.1 M rows, 2.6 M episodes |
| `--cache-state-tile 0` / `--line-trace-tile 0` | one tile, all 16 cores | 39,680 rows, 26,304 episodes | |
| `--line-trace-line N` | one line id | | the smallest useful cut |

The line trace's tile filter matches the tile the episode was **filled** in, and
keeps each episode whole: one filled in tile 0 that survives into tile 5 reports
its real ending time. A residency is one thing, and cutting it at a tile
boundary would report a shorter life than the line had.

Both files carry `#` comment lines above the header, so:

```python
pandas.read_csv(path, comment='#')
```

## cache_state.csv

```
time,tile,level,core,set,way,action,line,tag,ways_used
32,0,l2,-1,0,0,fill,65536,32,1
32,0,l1,0,0,0,fill,65536,512,1
```

`action` is `fill`, `evict` or `invalidate`, which are the only three ways an
array's contents change. An install that displaces a line writes an `evict` and
then a `fill`, at the same time and for the same way, because that is what the
slot did. `core` is -1 on an L2 row: the L2 is shared and its slots belong to no
core. `ways_used` is that set's occupancy at that level after the row.

## line_trace.csv

```
level,core,line,set,tag,fill_tile,first_request,filled_at,ended_at,residency,hits,demand_hits,opened_by,ended_by
l1,0,65632,96,512,0,66,98,1088,990,0,0,demand,evict
```

An episode runs from the fill that installed a line to the eviction,
invalidation or end of run that removed it. A line fetched, hit twice and
evicted is ONE row carrying both hits; the same line fetched again later is a
second row. `filled_at - first_request` is the fetch that episode waited on.

**Row order is `ended_at`, not `first_request`.** A row is written when the
episode CLOSES, because `residency`, `hits` and `ended_by` are not known until
then, so the file cannot be in fill order. Under LRU the two orders genuinely
differ: the line evicted first is the one used least recently, not the one
fetched first. In tile 0 that is 2,645 inversions of `first_request` out of
26,303 adjacent pairs, while `ended_at` has none.

To read it in request order:

```
python3 to_txt.py tile0_line_trace.csv out.txt --sort first_request --rows 2000
```

`to_txt.py` sorts before it cuts, so `--sort first_request --rows 2000` is the
2000 earliest requests rather than an arbitrary 2000 rows reordered afterwards.
`tile0_line_trace_by_request_first2000.txt` is that view.

## What the run showed

Tile 0, all 16 cores, the file on disk now (L1 only, 13,152 episodes):

```
100.00% never hit, 0 hits total
```

At `--line-trace-level both` the same tile shows the contrast the L1 alone
cannot:

```
L1   13,152 episodes   100.00% never hit       0 hits total
L2   13,152 episodes    92.94% never hit   1,536 hits total, up to 7 on one line
```

The whole layer, all 16 cores, same shape:

```
L1   2,597,632 episodes   100.00% of them never hit    residency p50    990 cycles
L2   2,427,712 episodes    94.39% of them never hit    residency p50 29,170 cycles
```

Every line that ever entered an L1 was evicted without a single subsequent hit.
That is `l1_hit_rate = 0.000000` stated as a fact about lines rather than as a
ratio: it is not that reuse is rare, it is that reuse never happens even once in
2.6 million residencies. The L2 does get some: 135,232 episodes see at least one
hit, up to five.

Both instruments cross-check exactly against the engine's own counters, which is
the argument that they are reporting the run and not themselves:

```
              instrument     results CSV
l1 hits                0     l1_hits             0
l2 hits          169,920     l2_hits       169,920
l1 fills       2,597,632     l1_accesses 2,597,632
l2 fills       2,427,712     dram_accesses 2,427,712
```
