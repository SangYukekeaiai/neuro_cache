from dataclasses import asdict
import json
import tempfile

import numpy as np
import pytest
import yaml

from lays.nocsim.schedule.decode import schedule_from_strategy
from lays.nocsim.schedule.tiles import iter_node_tiles
from lays.nocsim.step_cycles import save_step_cycles
from lays.parsers.layer import SNNProb
from lays.scheduler.artifact import ScheduleArtifact
from lays.weight_trace_gen.weight_trace import reconstruct_samples
from zoo.fig12_edp.nocsim.driver import run_case
from contracts import require_no_gb
from ideal_counts import native_demand
from schedule_spec import ROOT, PES, resident, strategy


@pytest.mark.parametrize('arch', list(PES))
def test_dense_native_equals_compulsory_traffic(arch, tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    p = {'shape': 'snn-layer', 'KH': 1, 'KW': 1, 'CIN': 4, 'COUT': 16, 'HO': 2, 'WO': 2, 'T': 2}
    arch_path = ROOT/'arch'/f'{arch}_128k.yaml'
    workload = tmp_path/'workload.yaml'; workload.write_text(yaml.safe_dump({'problem': p}))
    prob = SNNProb(workload)
    spec = strategy(p, resident(p, arch, 131072, 8), arch)
    decoded = schedule_from_strategy(spec, prob)
    tiles = list(iter_node_tiles(decoded, prob))
    options = {'wave_width': PES[arch]} if arch == 'gustavsnn' else {}
    native, = reconstruct_samples(arch, np.ones((2, 1, 4, 2, 2), dtype=np.uint8), tiles,
                                  [0], 'dense', 'tiny', p, decoded.dram_num_steps, **options)
    used, _, _ = native_demand(native)
    assert used.all() and int(used.sum()) == 64
    artifact = ScheduleArtifact(arch, 'dense', 'tiny', {'problem': p},
                                {'has_solution': True, 'strategy': spec}, decoded.dram_num_steps)
    schedule_path = tmp_path/'schedule.json'; schedule_path.write_text(json.dumps(asdict(artifact)))
    steps = tmp_path/'steps.json.gz'; save_step_cycles(native, steps)
    noc = run_case(schedule_path, arch, steps_path=steps, output_dir=tmp_path/'noc', arch_path=arch_path)
    require_no_gb(noc)
    assert noc['dram_payload_bytes'] == noc['dram_bytes'] == noc['l1_delivery_bytes'] == int(used.sum())
