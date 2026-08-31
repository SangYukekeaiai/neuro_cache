# Two instruments, two files: cache state and line life cycle

Erasable. Replaces the previous mixed `--line-log`, which was reverted.

```
new     src/wcache/native/include/wcache/cache_state_log.h
new     src/wcache/native/include/wcache/line_trace.h
edited  include/wcache/engine.h    two setters, three private verbs
edited  src/engine.cpp             the three verbs + 6 call sites
edited  apps/app_support.h         int_value_of()
edited  apps/wcache_run.cpp        --cache-state* / --line-trace*
```

`src/engine_core.cpp` is untouched this time: neither instrument records
anything on the core side.

---

## 1. Why two files and not one

They are read in different directions. A state log is read down its `set` column
in time order, looking for a set that thrashes. An episode table is read down its
`hits` and `residency` columns, and sorts fine by any of them. Interleaved,
neither is scannable, which is what was wrong with the previous attempt.

Both are CSV with `#` comment lines above the header, so
`pandas.read_csv(path, comment='#')` loads either.

## 2. `--cache-state PATH`: what is in the caches

One row per **slot transition**. The contents of an array change at exactly
three places, and each is one row:

```
fill        a line was installed into a way
evict       a line was displaced by an install into its way
invalidate  a line was back-invalidated out of an L1 (inclusive only)
```

```
time,tile,level,core,set,way,action,line,tag,ways_used
32,0,l2,-1,0,0,fill,65536,32,1
32,0,l1,0,0,0,fill,65536,512,1
```

An install that displaces a line writes an `evict` **and** a `fill`, in that
order, at the same time, for the same way, because that is what the slot did.

`ways_used` is the set's occupancy after the row. It is counted by the log
itself (a fill raises it, the other two lower it) rather than read off the array:
`CacheArray` has no slot-to-line accessor, and widening that interface for a
debugging aid would be the wrong trade.

`way` comes from probing the array for the line just installed, and the victim
left from that same way, since `install` puts the new line where the old one was.

## 3. `--line-trace PATH`: what happened to a line

One row per **residency episode**: from the fill that installed a line to the
eviction, invalidation or end of run that removed it. A line fetched, hit twice
and evicted is ONE row carrying both hits; the same line fetched again later is a
second row.

```
level,core,line,set,tag,fill_tile,first_request,filled_at,ended_at,residency,hits,demand_hits,opened_by,ended_by
l1,0,65632,96,512,0,66,98,1088,990,0,0,demand,evict
```

`filled_at - first_request` is the fetch that episode waited on. `opened_by` is
`demand` or `prefetch`; `ended_by` is `evict`, `invalidate` or `end_of_run`.

**Memory is bounded by the caches, not by the run.** An episode opens on a fill
and closes on the eviction of that same slot, so the open-episode map cannot
exceed `n_cores * l1_lines + l2_lines` entries however long the run is. That
bound is why it is a map and not a ring buffer.

## 4. How they are fed

Three private verbs on the engine, and **both** instruments are fed from them:

```
note_fill(level, core, line, way, now, first_request, pf_opened)
note_leave(level, core, line, way, now, why)
note_hit(level, core, line, demand)
```

One source, two files. Fed from one place so the two can never disagree about
what the array did; written to two files so neither has to be read through the
other. `note_hit` reaches only the line trace: a hit changes what a line has
*done*, not what the array *holds*, so it is not a state transition.

Call sites: `on_l1_fill`, `on_l2_fill`, `back_invalidate` (which gained a
`SimTime` parameter, since it had no clock of its own), and the two probe
handlers on a `Hit`.

## 5. Verification

**No perturbation.** Same config with both instruments and with neither:
identical through every simulated column of the results row; only
`sim_wall_seconds` moves.

**They agree with the engine.** Every total cross-checks exactly:

```
              instrument       results CSV
l1 hits                0       l1_hits             0
l2 hits          169,920       l2_hits       169,920
l1 fills       2,597,632       l1_accesses 2,597,632
l2 fills       2,427,712       dram_accesses 2,427,712
```

`make test` exits 0, 48,129 checks, 0 failures.

## 6. What the first run says

V8, C2, `block_pack`, all 16 cores:

```
L1   2,597,632 episodes   100.00% never hit    residency p50    990 cycles
L2   2,427,712 episodes    94.39% never hit    residency p50 29,170 cycles
```

Every line that ever entered an L1 was evicted without a single subsequent hit.
That answers the reuse question you left open on 08-25 in the sharpest available
form: it is not that L1 reuse is rare, it is that in 2.6 million residencies it
never happens once. The L2 does get some, 135,232 episodes with at least one hit
and up to five.

## 7. Questions

1. **Should `split_cin` be generated as the paired comparison?** One command,
   and the episode tables diff directly on `hits`.
2. **Do you want a tile filter on the state log?** The `tile` column is there so
   post-filtering works, but a `--cache-state-tile N` would cut the file at the
   source instead of after 200 MB is written.
3. **`--line-trace-line N` follows one line through both levels.** Is that the
   cut you want for a hand walkthrough, or would per-set (`--line-trace-set N`)
   be more useful for the collapse argument?
