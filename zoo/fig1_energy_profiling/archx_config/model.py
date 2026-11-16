"""Figure 1 price-free graph specification and saved-counter formulas."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
BACKEND = REPO/'zoo/archx'
sys.path.insert(0, str(BACKEND/'src'))
sys.path.insert(0, str(BACKEND/'zoo'))
import archx
from snn_edp.model import evaluate
if not Path(archx.__file__).resolve().is_relative_to(BACKEND/'src'):
    raise RuntimeError('Figure 1 requires the vendored archx backend')

SEGMENTS = ('compute', 'on_chip_sram', 'off_chip_weights', 'off_chip_other')
METRICS = {'dynamic_energy': {'unit':'nJ','aggregation':'summation'},
           'leakage_power': {'unit':'mW','aggregation':'module'},
           'area': {'unit':'mm^2','aggregation':'module'}}
FREQUENCY_MHZ = 500


def load(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix+'.part')
    part.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')
    part.replace(path)


def event(key):
    return 'op__'+key.replace('.', '__')


def leaf(key):
    return 'm__'+key.rsplit('.', 1)[0].replace('.', '__')


@lru_cache(maxsize=12)
def specifications(variant):
    return load(ROOT/'archx_config/hardware.json')['variants'][variant]


@lru_cache(maxsize=1)
def measurements(case):
    case = Path(case)
    identity = load(case/'case.json'); raw = load(case/'counts.json'); noc = load(case/'noc/result.json')
    if any(noc[k] != 0 for k in ('gb_reads','gb_writes','weight_packet_hops','chain_packet_hops','psum_boundary_bytes','vmem_boundary_bytes')):
        raise ValueError('unexpected shared/state traffic')
    variant = identity['arch']+'/'+identity['size']
    values = {**raw, **{k:v for k,v in noc.items() if isinstance(v,(int,float))}}
    specs = specifications(variant)
    counts = {k: evaluate(s['expression'], values) for k,s in specs.items()}
    return identity, noc, counts
