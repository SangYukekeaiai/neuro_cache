"""Run one manifest-pinned Figure 1 array case."""
import argparse
import json
import resource
import time
import traceback
from pathlib import Path

from count_case import run, save
from schedule_spec import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=int, required=True)
    parser.add_argument('--trace-root', type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads((ROOT/'configs/cases.json').read_text())
    case = cases[args.index]
    assert case['index'] == args.index
    start = time.monotonic()
    status = {'case': case}
    error = None
    try:
        status['result'] = run(ROOT/case['manifest'], case['layer'], case['sample'],
                               args.trace_root, ROOT/'outputs/counts')
    except Exception:
        error = traceback.format_exc()
        status['error'] = error
    usage = resource.getrusage(resource.RUSAGE_SELF)
    status.update(wall_seconds=time.monotonic()-start, cpu_seconds=usage.ru_utime+usage.ru_stime,
                  max_rss_kib=usage.ru_maxrss)
    directory = ROOT/'outputs/task_status'; directory.mkdir(parents=True, exist_ok=True)
    save(directory/f'{args.index:04d}.json', status)
    print(json.dumps(status), flush=True)
    if error:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
