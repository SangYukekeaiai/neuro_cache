# Example weight traces

Small slices of real generated traces, committed so that plan unit A3
(`TraceReader`) can be built and reviewed against corpus-shaped data instead of
against `FakeTrace`, the hand-written stand-in every Phase C test drives the
engine from today.

`manifest.json` records, per file, where it was cut from and what was measured
in it. `make_examples.py` regenerates all of them from
`outputs/weight_traces/` and **fails** if any example has stopped carrying the
property it was cut for.

## What is here

| File | Format | Carries |
|---|---|---|
| `loas_vgg16_layer01_v2.json` | v2 | the ordinary case: 8 cores busy every tick, `gap == 1` throughout, `tile_tail == 1`, bursts spanning 16 COUT |
| `ptb_resnet19_layer01_v2.json` | v2 | the only measured non-trivial `tile_tail`: compute outlives the last weight burst by about 20 cycles, so the tile seam is not free |
| `prosperity_vgg16_layer01_v2.json` | v2 | sparse core participation: cores 6 and 7 issue nothing at all, and core 0 runs out of work part way through the window |
| `spinalflow_vgg16_layer01_v2.json` | v2 | bursts four times longer, 64 COUT each, so one burst can cross several lines under a narrow `cout_block` |
| `gustavsnn_vgg16_layer01_v1_legacy.json` | v1 | the legacy flat shape, no `tick` and no `core_id`, which the engine cannot be driven from at all |

Each v2 example is the first 2 tiles of the source sample, cores 0-7, first 24
ticks. Every field is copied verbatim except `mac_cycles`, which is rewritten
to `max_tick_in_slice + original tile_tail` so that `tile_tail` survives the
cut, and `dram_num_steps` / `noc_num_steps`, which are set to what actually
survived so the header does not describe a tiling the file no longer holds. The
originals are in `manifest.json`. Nothing is added to a trace file: an example
is schema-identical to a corpus file, so a reader pointed at one runs the same
decode path it will run on a 1.5 GB sample.

## The on-disk shape, as it actually is

Two shapes are live in `outputs/weight_traces/`. The v2 one is what
`src/tracegen.py` writes today and is the only one the engine can use.

```
v2                                     v1 (legacy, gustavsnn only)
{                                      {
 arch, trace_dir, layer_name,           arch, trace_dir, layer_name,
 sample_idx, workload_dims,             sample_idx, workload_dims,
 dram_num_steps, noc_num_steps,         dram_num_steps,
 tiles: [                               tiles: [
  { dram_i, noc_i,                       { dram_i,
    mac_cycles, lif_cycles,                mac_cycles, lif_cycles,
    ticks: [                               weight_addresses: [ [5 ints], ... ]
     { tick,                             }
       cores: [                         ]
        { core_id,                     }
          weight_addresses: [ [5 ints], ... ] } ] } ] } ] }
```

`workload_dims` carries `KH`, `KW`, `CIN`, `COUT` (plus `HO`, `WO`, `T`,
`shape`, which the cache model does not read), and maps straight onto
`WeightShape`.

An address is five `int32`: `[kh, kw, cin, cout_start, cout_end]`, a
half-open COUT run. Every arch emits this order and no other
(`src/archmodels/tick_output.h`). It becomes a `Burst` as

```c++
Burst{ Coord{kh, kw, cin, cout_start}, Axis::COUT,
       /*count=*/cout_end - cout_start, /*stride=*/1 }
```

A tick omits a core that fetched nothing; it is never padded with an empty
entry (`tracegen.TickEntry`). Core ids are the flat encoding of
`nocsim.schedule.tiles.encode_core_id` and are therefore dense over the
machine, not over the cores that happen to appear in a file.

## What the format does not say, and A3 has to get from somewhere

Four things the engine needs are absent from every header on disk. They are
listed here rather than in `manifest.json` because they are decisions, not
measurements.

1. **The machine's core count.** Nothing states it. `max(core_id) + 1` gives
   128 on every sample measured, but that is luck: `prosperity` layer 01 has
   only 90 distinct core ids across the whole sample and 75-85 per tile, so a
   trace whose top core is idle everywhere would report a machine one core too
   small, and the barrier is a countdown over exactly that number.
2. **`spatial_factors`.** Plan unit A3's row calls for the `spatial_factors`
   core decode, and `spatial_factors` is not in the trace. It lives in the
   schedule artifact under `outputs/schedules/`, reachable only by decoding
   `result.strategy` through `nocsim.schedule.decode` -- Python, and a MIP
   strategy at that.
3. **The burst axis and stride.** `types.h` documents `Burst::axis` as coming
   from a "header `burst_dim`" and `Burst::stride` from a "`burst_stride`".
   Neither field exists. Today every burst in the corpus is COUT with stride 1,
   so hardcoding it is correct and would stay correct silently if it ever
   stopped being true.
4. **The address tuple's field order.** The `A2a -> A3` obligation requires the
   tuple to be decoded "by header-declared field order, never positionally".
   No header declares one, so it can only be decoded positionally.
