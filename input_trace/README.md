# Captured LoAS input spike traces

`loas/<workload>/` holds one `meta.json` (layer name -> input-tensor shape
`[T, B, Cin, Hin, Win]`) plus one `<layer_name>.npy` per captured layer, binary
`uint8` spikes over CIFAR-10. Read them through
`archmodels.trace.load_layer_trace`, which validates each array against the
shape `meta.json` declares.

## What is committed here, and what is not

These are **5-sample subsets**, not the full captures. The originals are 10,000
CIFAR-10 samples per layer and **25.8 GB** across both workloads, which is why
they never lived in this repo.

| Directory | Layers | Samples | Size |
|---|---|---|---|
| `loas/vgg16_T4_n5` | 12 | 5 of 10,000 | 3.6 MB |
| `loas/resnet19_T4_n5` | 19 | 5 of 10,000 | 10.0 MB |

The `_n5` suffix is deliberate: the source directories are named `_all` because
they hold all 10,000 samples, and a directory named `_all` holding five of them
would read as the full capture later.

Both subsets hold **the same five images**, indices `[2697, 3078, 5110, 6367,
8502]`, drawn with `numpy.random.default_rng(0)`. The same indices across every
layer of both workloads is what makes the subset a subset of *images*: the
reconstruction walks one network's layers as a single forward pass, so a
per-layer draw would put different CIFAR-10 images in layer 2 than in layer 1.
Seed, indices, and method are recorded in each `meta.json` under `subset`.

## Regenerating, or widening to more samples

`scripts/subset_input_traces.py` cuts these. To take 20 samples instead:

```
conda run -n base python scripts/subset_input_traces.py --n 20 --seed 0
```

It reads the full captures from the home-directory snapshot by default. The
sibling capture repo `/u/yyu9/neuro_cache_trace/` that used to hold them was
deleted between the 2026-08-11 and 2026-08-12 daily snapshots, and the newest
snapshot that still has it is

```
/u/yyu9/.snapshot/snapshot-daily-_2026-08-11_17_00_00_UTC/neuro_cache_trace/
```

Daily snapshots retain roughly 30 days, so that copy expires around 2026-09-10.
After that, the full captures have to be re-captured from the LoAS checkpoints
with `capture/run_loas.py` from the same snapshot, and only what has been
copied out survives. `ls /u/yyu9/.snapshot/` lists what is still available.
