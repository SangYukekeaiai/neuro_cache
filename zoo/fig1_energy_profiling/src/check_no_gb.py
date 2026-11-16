"""Check direct DRAM/local transfers on tiny fixtures; no solver or native run."""
from pathlib import Path
import copy
import hashlib
import json

import yaml

from contracts import require_no_gb

from lays.nocsim.combine import combine
from lays.nocsim.core.transaction import COUNT
from lays.nocsim.schedule.buf_spatial import BufSpatial
from lays.nocsim.schedule.decode import schedule_from_strategy
from lays.nocsim.schedule.steps import StepInfo
from lays.parsers.arch import SNNArch
from lays.parsers.bitwidths import SNNBitwidths
from lays.parsers.layer import SNNProb
from zoo.fig12_edp.nocsim.energycounts import parse_tc_csv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/self_checks/no_gb'


def transactions(arch_path, output):
    problem = OUT / 'tiny_layer.yaml'
    problem.write_text(yaml.safe_dump({'problem': {
        'KH': 1, 'KW': 1, 'CIN': 4, 'COUT': 4,
        'HO': 2, 'WO': 1, 'T': 1, 'shape': 'snn-layer'}}))
    prob = SNNProb(problem)
    # A hand-specified unit fixture, not a solved Figure 1 workload schedule.
    strategy = {'NoCLevel': {'temporal_permutation': {'loops': []}, 'spatial_splitting': {'loops': []}},
                'DRAM': {'temporal_permutation': {'loops': [{'dim': 'COUT', 'size': 4}, {'dim': 'HO', 'size': 2}]}}}
    schedule = schedule_from_strategy(strategy, prob)
    arch = SNNArch(arch_path)
    gen = combine(schedule, BufSpatial(schedule, prob), StepInfo(schedule, prob),
                  prob, SNNBitwidths(arch_path), arch=arch)
    gen.to_file(output)
    n = gen.noc
    counts = parse_tc_csv(output, X=n.X, Y=n.Y, gb_port=n.gb_port, dram_port=n.dram_port)
    return arch, n, gen.tcs, counts


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / 'configs/arch_manifest.json').read_text())
    results = {}
    for key, spec in manifest['variants'].items():
        arch, noc, tcs, counts = transactions(ROOT / spec['path'], OUT / (key.replace('/', '_') + '.csv'))
        assert arch.single_node and not arch.has_noc_buffer and arch.mem_instances[0] == 1
        require_no_gb(counts)
        assert counts['gb_reads'] == counts['gb_writes'] == counts['weight_packet_hops'] == counts['chain_packet_hops'] == 0
        assert counts['dram_accesses'] > 0 and counts['l1_delivery_bytes'] > 0
        transfers = [t for t in tcs if t.op != COUNT]
        assert transfers
        assert all(noc.gb_port not in t.srcs + t.dests for t in transfers)
        assert all(t.srcs == [noc.dram_port] and all(d < noc.num_pes for d in t.dests) for t in transfers)
        results[key] = {'has_noc_buffer': arch.has_noc_buffer, 'counts': counts, 'gb_endpoint_transactions': 0}
    control = yaml.safe_load((ROOT / 'arch/loas_base.yaml').read_text())
    control['arch']['single_node'] = False
    control['arch']['storage'][1]['entries'] = {'weight': 2097152, 'psum': 65536, 'vmem': 65536}
    control_path = OUT / 'gb_present_control.yaml'
    control_path.write_text(yaml.safe_dump(control))
    _, _, _, control_counts = transactions(control_path, OUT / 'gb_present_control.csv')
    assert control_counts['gb_reads'] > 0 and control_counts['gb_writes'] > 0
    try:
        require_no_gb(control_counts)
    except ValueError:
        pass
    else:
        raise AssertionError('GB-present control must be rejected')
    report = {'variants_passed': len(results), 'variants': results, 'gb_present_control': control_counts,
              'scope': 'Synthetic transaction/counter checks only; production schedule generation remains held',
              'physical_hierarchy': 'DRAM <-> node-local buffers <-> PEs',
              'shared_sources_modified': False,
              'arch_manifest_sha256': hashlib.sha256((ROOT / 'configs/arch_manifest.json').read_bytes()).hexdigest()}
    (OUT / 'verification.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print('12 variants: zero GB endpoints/reads/writes/hops; positive direct DRAM/local traffic; GB-present control detects reads/writes')


if __name__ == '__main__':
    main()
