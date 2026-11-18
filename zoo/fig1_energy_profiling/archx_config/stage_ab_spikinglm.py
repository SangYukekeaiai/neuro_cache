"""Stage A+B for the spikinglm extension, on separate roots.

Counts in outputs/counts_spikinglm -> price-free archx checkpoints in
outputs/archx_counts_spikinglm -> priced rows in outputs/priced_spikinglm/
{baseline,ideal}. The vgg16 artifacts and templates are never touched;
templates are compiled fresh per variant into archx_templates_spikinglm.

Run from the repo root:
  ARCHX_DISABLE_PERFORMANCE_CACHE=1 PYTHONPATH=src:. conda run -p <env> \
      python -B zoo/fig1_energy_profiling/archx_config/stage_ab_spikinglm.py
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parent

import count as stage_a  # noqa: E402
import price as stage_b  # noqa: E402
from loguru import logger  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', choices=('128k', '256k', '512k', '1m'),
                        help='limit to one capacity (one parallel job per size)')
    args = parser.parse_args()
    if os.environ.get('ARCHX_DISABLE_PERFORMANCE_CACHE') != '1':
        raise ValueError('ARCHX_DISABLE_PERFORMANCE_CACHE=1 is mandatory')
    logger.remove()
    logger.add(sys.stderr, level='ERROR')
    pattern = f'*/{args.size}/sample_*/*/receipt.json' if args.size else '*/*/sample_*/*/receipt.json'
    expected = 480 if args.size else 1920
    cases = [p.parent for p in
             sorted((ROOT / 'outputs/counts_spikinglm').glob(pattern))]
    if len(cases) != expected:
        raise ValueError(f'expected {expected} spikinglm count cases, got {len(cases)}')
    templates = {}
    for i, case in enumerate(cases):
        identity = json.loads((case / 'case.json').read_text())
        variant = identity['arch'] + '/' + identity['size']
        if variant not in templates:
            templates[variant] = stage_a.compile_template(
                case, ROOT / 'outputs/archx_templates_spikinglm' / variant)
        output = ROOT / 'outputs/archx_counts_spikinglm' / case.relative_to(
            ROOT / 'outputs/counts_spikinglm')
        stage_a.count(case, output, templates[variant])
        if (i + 1) % 120 == 0:
            print(f'counted {i+1}/{len(cases)}', flush=True)
    table = HERE / 'energy_table_asap7_syn.json'
    directories = [p.parent for p in
                   sorted((ROOT / 'outputs/archx_counts_spikinglm').glob(
                       pattern.replace('receipt', 'manifest')))]
    if len(directories) != expected:
        raise ValueError(f'expected {expected} archx checkpoints, got {len(directories)}')
    for i, directory in enumerate(directories):
        relative = directory.relative_to(ROOT / 'outputs/archx_counts_spikinglm')
        stage_b.price(directory, table, ROOT / 'outputs/priced_spikinglm/baseline' / relative)
        if relative.parts[1] == '256k':
            stage_b.price(directory, table, ROOT / 'outputs/priced_spikinglm/ideal' / relative, True)
        if (i + 1) % 120 == 0:
            print(f'priced {i+1}/{len(directories)}', flush=True)
    print(f'stage A+B complete for size={args.size or "all"}: '
          f'{len(directories)} baseline rows'
          + (', 480 ideal rows' if args.size in (None, '256k') else ''))


if __name__ == '__main__':
    main()
