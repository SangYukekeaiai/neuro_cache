"""Native archx performance callbacks over saved simulator outputs."""
from snn_edp.model import *


def case_dir(workload):
    if set(workload['configuration'])!={'case_dir'}: raise ValueError('workload must contain only case_dir')
    return workload['configuration']['case_dir']


def branch(arm, category):
    def run(architecture_dict, workload_dict):
        case=case_dir(workload_dict); arch=measurements(case)['identity']['arch']
        counts=case_counts(case,arm)
        return {'subevent':{event(arm,key):{'count':counts[key]}
                           for key,spec in operations(arch,arm).items() if spec['category']==category}}
    return run


def root(arm):
    def run(architecture_dict,workload_dict):
        return {'subevent':{f'{category}_{arm}':{'count':1} for category in ('core','memory')}}
    return run


def operation(key,spec):
    def run(architecture_dict,workload_dict):
        return {'subevent':{leaf(key,spec):{'count':1,'operation':{'dynamic_energy':key.split('.')[-1]}}}}
    return run


def chain_reference(architecture_dict,workload_dict):
    n=measurements(case_dir(workload_dict))['noc']['chain_packet_hops']
    return {'subevent':{event('reference',key):{'count':n} for key in ('shared.router.hop','shared.link.hop')}}


for arm in ARMS:
    globals()[arm]=root(arm)
    for category in ('core','memory'): globals()[category+'_'+arm]=branch(arm,category)
    for arch in ARCHES:
        for key,spec in operations(arch,arm).items(): globals()[event(arm,key)]=operation(key,spec)
for key in ('shared.router.hop','shared.link.hop'):
    globals()[event('reference',key)]=operation(key,load(HERE/'hardware.json')[key])
