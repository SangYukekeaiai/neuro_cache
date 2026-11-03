# Example weight traces

Small slices of real generated traces, committed as test fixtures for the cache
simulator. `manifest.json` records, per file, where it was cut from and what
was measured in it.

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

## `to_stream.py`

Writes one v2 fixture out as a WCTS stream on stdout; the native CLI tests
(`native/tests/*.sh`, run by `make test-cli`) drive the simulator from it.

```
python3 to_stream.py <fixture.json> [max_tiles] > slice.wcts
```

`max_tiles` truncates the stream after that many tile frames. The v1 legacy
fixture has no `tick` or `core_id` and cannot drive the engine.
