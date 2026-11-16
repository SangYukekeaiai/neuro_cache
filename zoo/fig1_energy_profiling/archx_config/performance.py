"""archx performance callbacks derive counts only from Figure 1 counter files."""
from model import *


def spad(architecture_dict, workload_dict):
    return {'subevent':{s:{'count':1} for s in SEGMENTS}}


def category(segment):
    def run(architecture_dict, workload_dict):
        config = workload_dict['configuration']
        if set(config) != {'case_dir'}: raise ValueError('workload requires only case_dir')
        identity, _, counts = measurements(config['case_dir'])
        specs = specifications(identity['arch']+'/'+identity['size'])
        return {'subevent':{event(k):{'count':counts[k]} for k,s in specs.items() if s['segment']==segment}}
    return run


def operation(key):
    def run(architecture_dict, workload_dict):
        return {'subevent':{leaf(key):{'count':1,'operation':{'dynamic_energy':key.split('.')[-1]}}}}
    return run


for segment in SEGMENTS: globals()[segment] = category(segment)
for specs in load(ROOT/'archx_config/hardware.json')['variants'].values():
    for key in specs: globals()[event(key)] = operation(key)
