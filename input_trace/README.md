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

## Where the full captures live

```
/work/hdd/bebv/yyu9/neuro_cache_trace/input_trace/loas/{vgg16_T4_all,resnet19_T4_all}
```

26 GB, on the `bebv` allocation rather than in `$HOME`. Alongside them are
`capture/` (the LoAS grabber that produced them), `model/` (the checkpoints it
needs), `tests/`, and the original `README.md` and slurm script, so a re-capture
is possible without the snapshot.

To run the pipeline on the full 10,000 samples instead of the committed five,
point `--trace-root` at that path:

```
conda run -n base python scripts/solve_schedules.py \
    --trace-root /work/hdd/bebv/yyu9/neuro_cache_trace/input_trace/loas \
    --trace-dirs vgg16_T4_all resnet19_T4_all
```

`scripts/subset_input_traces.py --src <that path>` cuts a wider subset from the
same place.

## How this was recovered, in case it happens again

These lived in a sibling repo at `/u/yyu9/neuro_cache_trace/`, which was deleted
between the 2026-08-11 and 2026-08-12 daily home snapshots. Delta home is NFS
and exposes read-only snapshots at `/u/yyu9/.snapshot/`, one per day, retained
roughly 30 days, and `.snapshot` exists at every level of the tree. The copy
above came from

```
/u/yyu9/.snapshot/snapshot-daily-_2026-08-11_17_00_00_UTC/neuro_cache_trace/
```

which expires around 2026-09-10. Looping the snapshots and testing for a path is
how the deletion date was bracketed: the newest snapshot still holding it is the
last day the file existed. Note that `/projects` and `/work` are Lustre and have
**no** snapshots, so only `$HOME` is recoverable this way, which is the reason
the durable copy above is the one that matters.
