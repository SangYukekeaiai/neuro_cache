"""Audit exact factor coordinates without generating or executing a workload."""
from collections import defaultdict
import itertools
import json
import math
from pathlib import Path
import string

ROOT=Path(__file__).resolve().parents[1]

def main():
    report={}
    for path in sorted((ROOT/'inputs/schedules').glob('*.json')):
        data=json.loads(path.read_text());s=data['result']['strategy'];shape=data['workload']['problem']
        levels=[('NodeSpatial',s['NodeLevel']['spatial_split']['factors']),
                ('NodeTemporalUnordered',s['NodeLevel']['temporal_tile']['factors']),
                ('NoCSpatial',s['NoCLevel']['spatial_splitting']['loops']),
                ('NoCTemporal',list(reversed(s['NoCLevel']['temporal_permutation']['loops']))),
                ('DRAMTemporal',list(reversed(s['DRAM']['temporal_permutation']['loops'])))]
        multipliers=defaultdict(lambda:1);indices=[]
        for level,loops in levels:
            for loop in loops:
                dim,size=loop['dim'],int(loop['size'])
                label=string.ascii_uppercase[len(indices)]
                indices.append(dict(label=label,dimension=dim,extent=size,coefficient=multipliers[dim],level=level))
                multipliers[dim]*=size
        assert dict(multipliers)=={k:shape[k] for k in multipliers}
        for dim,extent in multipliers.items():
            parts=[x for x in indices if x['dimension']==dim]
            coordinates=[sum(v*x['coefficient'] for v,x in zip(values,parts))
                         for values in itertools.product(*(range(x['extent']) for x in parts))]
            assert sorted(coordinates)==list(range(extent)),(path.name,dim)
        spatial_nodes=math.prod(x['extent'] for x in indices if x['level']=='NoCSpatial')
        spatial_pes=math.prod(x['extent'] for x in indices if x['level']=='NodeSpatial')
        assert spatial_nodes==16 and spatial_pes==4
        report[path.stem]={'split_indices_inner_to_outer':indices,
                          'source_temporal_order':'outer-to-inner; explicitly reversed for Timeloop',
                          'dimension_coordinate_bijections_verified':True,
                          'node_fanout':spatial_nodes,'PE_fanout_per_node':spatial_pes,
                          'node_temporal_order':'not specified by schedule; native LoAS T-bit-vector execution is not a scalar MAC nest',
                          'status':'coordinate representation only; workload/SAF correctness not yet established'}
    target=ROOT/'outputs/self_checks/mapping_coordinates.json'
    target.write_text(json.dumps(report,indent=2)+'\n')
    print(f'{len(report)} schedules: coordinate bijections exact, node fanout16 x PE4; no model runs')

if __name__=='__main__':main()
