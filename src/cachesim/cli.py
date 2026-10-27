"""python -m cachesim {grid, sweep, run}.

  grid   write the khkw config grid (configs/cache/base.json x khkw_sweep.json)
         as one JSON file per cin_block and print their paths
  sweep  run the native cachesim_sweep with every later argument passed as is
  run    run the native cachesim_run the same way

`python -m cachesim sweep --help` prints the native usage."""
import argparse
import subprocess
import sys

from cachesim import grid

NATIVE = grid.ROOT / "src/cachesim/native"
BINS = {"sweep": NATIVE / "build/release/cachesim_sweep",
        "run": NATIVE / "build/release/cachesim_run"}


def native(name, args):
    """Exit code of the native binary `name` run on `args`, building it first if missing."""
    if not BINS[name].is_file():
        subprocess.run(["make", "-C", str(NATIVE), "MODE=release", "apps"], check=True,
                       stdout=sys.stderr)
    return subprocess.run([str(BINS[name]), *args]).returncode


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    # sweep and run take no arguments of their own, --help included, so they are
    # dispatched before argparse sees (and could reinterpret) the native flags.
    if argv and argv[0] in BINS:
        return native(argv[0], argv[1:])
    p = argparse.ArgumentParser(prog="python -m cachesim",
                                description=__doc__.split("\n\n")[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grid", help="write the khkw grid files")
    g.add_argument("--out", required=True, help="directory for <name>_<k>.json")
    g.add_argument("--base", default=str(grid.BASE_JSON), help="base config (default %(default)s)")
    g.add_argument("--sweep", default=str(grid.SWEEP_JSON), help="sweep axes (default %(default)s)")
    for name in BINS:
        sub.add_parser(name, help=f"run cachesim_{name}; every later argument goes to it")
    a = p.parse_args(argv)
    paths = grid.write_grid(a.out, grid.full_grid(grid.load_base(a.base), grid.load_sweep(a.sweep)))
    print("\n".join(str(path) for path in paths.values()))
    return 0
