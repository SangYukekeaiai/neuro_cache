"""Price-independent hardware, scope and simulator-derived event counts."""
import ast
import csv
from functools import lru_cache
import hashlib
import json
import math
import operator
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ARCHES = ('spinalflow','ptb','loas','gustavsnn','prosperity')
ARMS = ('spad','cacheA','cacheB')
UNUSED = {'psum_l1','psum_l2','vmem_l1','vmem_l2'}
SF = {'adder32.add':'A','cmp32.compare':'A','reg32.rmw':'A+L','min_tree4.compare':'R','l1_weight_spad.read':'R'}
METRICS = {'dynamic_energy':{'unit':'nJ','aggregation':'summation'},
           'leakage_power':{'unit':'mW','aggregation':'module'},
           'area':{'unit':'mm^2','aggregation':'module'}}
OPS = {ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,
       ast.Div:operator.truediv,ast.FloorDiv:operator.floordiv,ast.Mod:operator.mod}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.part')
    import os
    with temporary.open('w') as stream:
        json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)



def evaluate(expression, values):
    def visit(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float): return node.value
        if isinstance(node,ast.Name): return float(values[node.id])
        if isinstance(node,ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](visit(node.left),visit(node.right))
        raise ValueError('invalid count expression: '+expression)
    value=float(visit(ast.parse(expression,mode='eval').body))
    if not math.isfinite(value) or value<0: raise ValueError('invalid count: '+expression)
    return value


def physical(key,spec):
    namespace,module,_=key.split('.')
    return namespace+'.'+spec.get('physical_module',module)


def instances(key,spec):
    ns,module,_=key.split('.')
    scope=spec.get('scope','node' if ns in ARCHES else 'system')
    if scope not in ('node','system'): raise ValueError('unknown inventory scope')
    n=spec.get('physical_instances',1)
    if ns=='spinalflow' and module in ('adder32','cmp32','reg32') and scope=='node': n=4
    return n*(16 if scope=='node' else 1)


def leaf(key,spec): return 'm__'+physical(key,spec).replace('.','__')
def event(arm,key): return arm+'__'+key.replace('.','__')


def operations(arch,arm):
    result={}
    for key,spec in load(HERE/'hardware.json').items():
        ns,module,op=key.split('.')
        if ns not in (arch,'cache','shared'): continue
        if ns=='spinalflow' and module in UNUSED: continue
        if arm not in spec.get('applies_to',ARMS): continue
        if ns=='cache' and arm=='spad': continue
        if arm!='spad' and (ns==arch and module=='l1_weight_spad' or key.startswith('shared.gb.')): continue
        expression=spec.get('count_expression')
        if key in ('shared.router.hop','shared.link.hop'):
            expression='weight_packet_hops+chain_packet_hops' if arm=='spad' else 'chain_packet_hops'
        elif ns==arch and module=='l1_weight_spad' and op=='write':
            expression=f"l1_delivery_bytes*8/{float(spec['query']['width'])}"
        elif expression is None and ns=='spinalflow': expression=SF.get(module+'.'+op)
        if not expression: raise ValueError('missing expression: '+key)
        result[key]={**spec,'expression':expression,
                     'category':'core' if ns==arch and module!='l1_weight_spad' else 'memory'}
    return result


@lru_cache(maxsize=16)
def measurements(case_dir):
    case=Path(case_dir)
    identity=load(case/'case.json'); arch=identity['arch']
    if arch not in ARCHES: raise ValueError('unsupported architecture')
    raw=load(case/'counts.json'); counts=dict(raw); noc=load(case/'noc/result.json')
    counts['L']=raw['HO']*raw['WO']*raw['COUT']*raw['T']
    counts['O']=counts['L']*raw['d_out']
    if arch=='prosperity':
        record,=list(csv.DictReader((case/'record_count.csv').open()))
        if (record['capture'],record['layer'],int(record['sample'])) != (identity['trace_relative_dir'],identity['layer'],noc['sample_idx']):
            raise ValueError('record-count identity mismatch')
        counts['R_p']=int(record['R_p']); counts['A_p']=counts['R_p']*raw['cout_n']
        counts['A']=counts['A_p']; counts['B']=counts['R_p']
        counts['N_rows']=raw['HO']*raw['WO']*raw['T']*raw['CIN']
        counts['seed_reads_bound']=counts['psum_writes']=counts['N_rows']*raw['COUT']
    else:
        counts['A']=raw['S_sum' if arch in ('ptb','loas') else 'S_win']*raw['COUT']
        if arch in ('ptb','loas'):
            counts['B']=raw['S_or']*raw['COUT']/raw['cout_n']; counts['W_o']=counts['O']/raw['T']
        elif arch=='spinalflow': counts['R']=counts['A']/raw['cout_n']
        else: counts['R_g']=counts['A']/raw['cout_n']; counts['W_o']=counts['O']
    caches={}
    for arm in ARMS[1:]:
        row,=list(csv.DictReader((case/f"cache_{arm[-1].lower()}.csv").open()))
        caches[arm]=row
    return {'identity':identity,'counts':counts,'noc':noc,'caches':caches}


def case_counts(case_dir,arm):
    data=measurements(str(case_dir)); arch=data['identity']['arch']
    counts={}
    for key,spec in operations(arch,arm).items():
        source=data['counts'] if key.startswith(arch+'.') else data['noc'] if arm=='spad' else data['caches'][arm]
        if key in ('shared.link.hop','shared.router.hop') or key==arch+'.l1_weight_spad.write': source=data['noc']
        counts[key]=evaluate(spec['expression'],source)
    return counts


def backend_fingerprint():
    import archx
    from importlib.metadata import version
    directory=Path(archx.__file__).parent
    paths=sorted(directory.rglob('*.py'))+sorted(directory.glob('_core*.so'))
    return {'version':version('archx'),'source_sha256':hashlib.sha256(json.dumps(
        {str(p.relative_to(directory)):digest(p) for p in paths},sort_keys=True).encode()).hexdigest()}


def count_fingerprint(case):
    case=Path(case)
    arch=load(case/'case.json')['arch']
    names=['case.json','counts.json','noc/result.json','cache_a.csv','cache_b.csv']
    if arch=='prosperity': names.append('record_count.csv')
    files=('__init__.py','designs/snn/description.py','model.py','performance.py','run.py','hardware.json',
           'interfaces/counts.py','runtime/sitecustomize.py')
    return {'inputs':{name:digest(case/name) for name in names},
            'model':{name:digest(HERE/name) for name in files},
            'archx':backend_fingerprint()}


def validate_artifacts(directory):
    directory=Path(directory); manifest=load(directory/'manifest.json')
    for name,sha in manifest['artifacts'].items():
        path=(directory/name).resolve()
        if not path.is_relative_to(directory.resolve()) or digest(path)!=sha:
            raise ValueError('checkpoint artifact changed: '+name)
    return manifest
