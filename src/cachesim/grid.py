"""The khkw cache grid: the base config in configs/cache/base.json crossed with
the sweep axes in configs/cache/khkw_sweep.json, and the grid files
cachesim_sweep reads."""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE_JSON = ROOT / "configs/cache/base.json"
SWEEP_JSON = ROOT / "configs/cache/khkw_sweep.json"


def load_base(path=BASE_JSON):
    return json.loads(pathlib.Path(path).read_text())


def load_sweep(path=SWEEP_JSON):
    return json.loads(pathlib.Path(path).read_text())


def grid_for(line_bytes, base=None, sweep=None):
    """The points at one line size, which share one cin_block and so one mapper:
    l2_banks x l2 prefetch x (L1 prefetch policy, distance), banks varying
    slowest.  When the l2_prefetch key is absent, the grid has no L2-prefetch
    axis and each point carries the base config's L2 settings.

    Keys stay in base.json's order, with the two L2-prefetch keys appended only
    for a sweep that declares that axis."""
    base = load_base() if base is None else base
    sweep = load_sweep() if sweep is None else sweep
    cin_block = line_bytes // (base["cout_block"] * base["weight_bytes"])
    l2_prefetch = sweep.get("l2_prefetch")
    if l2_prefetch is None:
        return [dict(base, cin_block=cin_block, l2_banks=banks,
                     prefetch_policy=policy, prefetch_distance=dist)
                for banks in sweep["l2_banks"] for policy, dist in sweep["prefetch"]]
    return [dict(base, cin_block=cin_block, l2_banks=banks,
                 l2_prefetch_policy=l2_policy, l2_prefetch_distance=l2_dist,
                 prefetch_policy=policy, prefetch_distance=dist)
            for banks in sweep["l2_banks"]
            for l2_policy, l2_dist in l2_prefetch
            for policy, dist in sweep["prefetch"]]


def full_grid(base=None, sweep=None):
    """grid_for over every line size in the sweep, line size varying slowest."""
    base = load_base() if base is None else base
    sweep = load_sweep() if sweep is None else sweep
    return [p for lb in sweep["line_bytes"] for p in grid_for(lb, base, sweep)]


def write_grid(out_dir, grid=None, name="khkw"):
    """Write `grid` (default: full_grid()) to out_dir/<name>_<k>.json, one file
    per cin_block in order of first appearance, because cachesim_sweep gives one
    mapper to a whole grid file. Returns {cin_block: path}."""
    grid = full_grid() if grid is None else grid
    groups = {}
    for p in grid:
        groups.setdefault(p.get("cin_block"), []).append(p)
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for k, (cin_block, points) in enumerate(groups.items()):
        paths[cin_block] = out_dir / f"{name}_{k}.json"
        paths[cin_block].write_text(json.dumps(points, indent=1))
    return paths
