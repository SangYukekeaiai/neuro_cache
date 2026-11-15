"""Locate the standalone archx zoo design and pass saved counter directories."""
import hashlib
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
MODEL_ROOT = Path(os.environ.get('SNN_EDP_MODEL_ROOT',
    HERE.parent/'archx/zoo/snn_edp')).resolve()
CACHE_CONFIGS = HERE/'configs'
ENERGY_TABLE = MODEL_ROOT/'energy_table.json'
if not (MODEL_ROOT/'designs/snn/description.py').is_file():
    raise FileNotFoundError(f'SNN energy design missing: {MODEL_ROOT}; set SNN_EDP_MODEL_ROOT')
sys.path.insert(0, str(MODEL_ROOT.parent))
from snn_edp import archx_aggregate_case
import snn_edp
if Path(snn_edp.__file__).resolve().parent != MODEL_ROOT:
    raise ValueError('loaded snn_edp differs from SNN_EDP_MODEL_ROOT')


def scientific_files():
    """Namespaced model sources; prices are fingerprinted separately by callers."""
    files = {f'snn_edp/{p.relative_to(MODEL_ROOT)}': p
             for p in MODEL_ROOT.rglob('*.py')
             if not {'runs', 'fixtures', 'characterization'}.intersection(p.relative_to(MODEL_ROOT).parts)
             and not p.name.startswith('test_')}
    files['snn_edp/hardware.json'] = MODEL_ROOT/'hardware.json'
    return files


CACHE_CONFIG_SHA256 = {
    'a': 'a08ec1f85b637c2c83827dbb4009996fd929dd76fad0e22bddcbaae6b9628d3c',
    'b': '4d89ff610a6646fdaa507fba7c479a4095d4d151e9a8a79624834d05c0f685e7',
}


def check_cache_configs(cache_a, cache_b):
    """Reject byte drift from the fixed production cache configurations."""
    for arm, path in zip(('a', 'b'), (cache_a, cache_b)):
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != CACHE_CONFIG_SHA256[arm]:
            raise ValueError(f'cache {arm.upper()} differs from pinned SHA256')
