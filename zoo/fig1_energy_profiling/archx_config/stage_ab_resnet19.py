"""Stage A+B for the resnet19 extension, on separate roots.

Counts in outputs/counts_resnet19 -> price-free archx checkpoints in
outputs/archx_counts_resnet19 -> priced rows in outputs/priced_resnet19/
{baseline,ideal}. The vgg16 and spikinglm artifacts are never touched;
templates are compiled fresh per variant into archx_templates_resnet19.

Run from the repo root:
  ARCHX_DISABLE_PERFORMANCE_CACHE=1 PYTHONPATH=src:. conda run -p <env> \
      python -B zoo/fig1_energy_profiling/archx_config/stage_ab_resnet19.py
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

PER_SIZE = 130  # 13 replayable resnet19 layers x 10 samples


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
    expected = PER_SIZE if args.size else 4 * PER_SIZE
    cases = [p.parent for p in
             sorted((ROOT / 'outputs/counts_resnet19').glob(pattern))]
    if len(cases) != expected:
        raise ValueError(f'expected {expected} resnet19 count cases, got {len(cases)}')
    templates = {}
    for i, case in enumerate(cases):
        identity = json.loads((case / 'case.json').read_text())
        variant = identity['arch'] + '/' + identity['size']
        if variant not in templates:
            templates[variant] = stage_a.compile_template(
                case, ROOT / 'outputs/archx_templates_resnet19' / variant)
        output = ROOT / 'outputs/archx_counts_resnet19' / case.relative_to(
            ROOT / 'outputs/counts_resnet19')
        stage_a.count(case, output, templates[variant])
        if (i + 1) % 65 == 0:
            print(f'counted {i+1}/{len(cases)}', flush=True)
    table = HERE / 'energy_table_asap7_syn.json'
    directories = [p.parent for p in
                   sorted((ROOT / 'outputs/archx_counts_resnet19').glob(
                       pattern.replace('receipt', 'manifest')))]
    if len(directories) != expected:
        raise ValueError(f'expected {expected} archx checkpoints, got {len(directories)}')
    for i, directory in enumerate(directories):
        relative = directory.relative_to(ROOT / 'outputs/archx_counts_resnet19')
        stage_b.price(directory, table, ROOT / 'outputs/priced_resnet19/baseline' / relative)
        if relative.parts[1] == '256k':
            stage_b.price(directory, table, ROOT / 'outputs/priced_resnet19/ideal' / relative, True)
        if (i + 1) % 65 == 0:
            print(f'priced {i+1}/{len(directories)}', flush=True)
    print(f'stage A+B complete for size={args.size or "all"}: '
          f'{len(directories)} baseline rows'
          + (f', {PER_SIZE} ideal rows' if args.size in (None, '256k') else ''))


if __name__ == '__main__':
    main()
