"""Compile the three-arm hardware/event model with the archx AGraph frontend."""
from pathlib import Path
from archx.programming.graph.agraph import AGraph
from snn_edp.model import *


def description(path):
    request=load(Path(path)/'request.json'); case=str(Path(request['case_dir']).resolve())
    arch=load(Path(case)/'case.json')['arch']
    graph=AGraph(path=str(path))
    graph.architecture.add_attributes(technology=7,frequency=100)
    performance=str(HERE/'performance.py')
    modules={}
    for arm in ARMS:
        graph.workload.add_configuration(name=arm).add_parameter(parameter_name='case_dir',parameter_value=case)
        graph.event.add_event(name=arm,subevent=['core_'+arm,'memory_'+arm],performance=performance)
        specs=operations(arch,arm)
        for category in ('core','memory'):
            graph.event.add_event(name=category+'_'+arm,performance=performance,
                subevent=[event(arm,key) for key,spec in specs.items() if spec['category']==category])
        for key,spec in specs.items():
            name=leaf(key,spec); modules[name]=(key,spec)
            graph.event.add_event(name=event(arm,key),subevent=[name],performance=performance)
    graph.event.add_event(name='chain_reference',subevent=[event('reference',key) for key in ('shared.router.hop','shared.link.hop')],performance=performance)
    for key in ('shared.router.hop','shared.link.hop'):
        spec=load(HERE/'hardware.json')[key]
        graph.event.add_event(name=event('reference',key),subevent=[leaf(key,spec)],performance=performance)
    for name,(key,spec) in modules.items():
        query={**spec.get('query', {}),'interface':str(HERE/'interfaces/counts')}
        query.setdefault('class',key.split('.')[1])
        # CLI initializes metrics before performance; no prices enter this graph.
        graph.architecture.add_module(name=name,instance=[instances(key,spec)],tag=[key.split('.')[0]],query=query)
    for name,definition in METRICS.items(): graph.metric.add_metric(name=name,**definition)
    graph.generate()
