# 2026-07-28 LoAS status replay

Fresh five-sample replay of all 31 LoAS ResNet19/VGG16 layers using the
corrected per-burst hit-rate definition and packed set index.

## Replay grid

- Layouts: `cout_only`, `cin_cout_2d`
- Cache types: 4/16/32-way set associative and fully associative
- Cache sizes: 16/32/64 KB
- Line sizes: 16/32/64 B
- Inner dimension: `cout`
- Samples: first 5 per layer

## Rebuild the artifact

```bash
/usr/bin/python3 profiling/0728_status_replay/build_artifact.py
/usr/bin/python3 -m http.server 8000 \
  --directory profiling/0728_status_replay/artifact
```

Then open `http://localhost:8000`.

The build script validates row count, uniqueness, sample count, and hit-rate
bounds before writing `artifact/data.js`.
