"""Single-node spad model compiled by the vendored archx AGraph frontend."""
from archx.programming.graph.agraph import AGraph
from model import *


def description(path):
    case = load(Path(path)/'request.json')['case_dir']
    identity = load(Path(case)/'case.json')
    specs = specifications(identity['arch']+'/'+identity['size'])
    graph = AGraph(path=str(path))
    graph.architecture.add_attributes(technology=7, frequency=FREQUENCY_MHZ)
    graph.workload.add_configuration(name='spad').add_parameter(parameter_name='case_dir',parameter_value=case)
    callback = str(ROOT/'archx_config/performance.py')
    graph.event.add_event(name='spad',subevent=[s for s in SEGMENTS if any(v['segment']==s for v in specs.values())],performance=callback)
    # Empty dynamic categories have no event node; static inventory is allocated during pricing.
    for segment in SEGMENTS:
        keys = [k for k,s in specs.items() if s['segment']==segment]
        if keys: graph.event.add_event(name=segment,subevent=[event(k) for k in keys],performance=callback)
    modules = {}
    for key,spec in specs.items():
        name=leaf(key); modules[name]=spec
        graph.event.add_event(name=event(key),subevent=[name],performance=callback)
    for name,spec in modules.items():
        graph.architecture.add_module(name=name,instance=[spec['instances']],tag=[spec['inventory_segment']],
            query={**spec['query'],'interface':str(ROOT/'archx_config/zero_metrics')})
    for name,spec in METRICS.items(): graph.metric.add_metric(name=name,**spec)
    graph.generate()
