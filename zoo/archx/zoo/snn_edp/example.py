"""Run the public per-case API on a bundled saved-counter fixture."""
import argparse
import json
from . import archx_aggregate_case
from .model import ARCHES, HERE, save


def main():
    import archx
    print("archx.__file__="+archx.__file__,flush=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arch', choices=ARCHES, default='spinalflow')
    args = parser.parse_args()
    rows = archx_aggregate_case(args.arch, HERE/'fixtures'/args.arch, HERE/'energy_table.json')
    save(HERE/'runs/example'/args.arch/'rows.json', rows)
    print(json.dumps(rows, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
