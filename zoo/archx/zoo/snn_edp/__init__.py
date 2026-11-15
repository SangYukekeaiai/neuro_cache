"""Archx is the required backend for per-case event counting and energy."""
import os
for _name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS',
              'RAYON_NUM_THREADS','BLIS_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_MAX_THREADS',
              'POLARS_MAX_THREADS','TBB_NUM_THREADS','GOTO_NUM_THREADS'):
    os.environ[_name]='1'
os.environ['ARCHX_DISABLE_PERFORMANCE_CACHE']='1'


# Pin the sibling backend before any model or CLI imports archx.
from pathlib import Path
import sys
BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT/'src'))
import archx
if Path(archx.__file__).resolve() != BACKEND_ROOT/'src/archx/__init__.py':
    raise RuntimeError(f'archx already loaded from a different tree: {archx.__file__}')


def archx_aggregate_case(arch,case_folder,energy_table_path,frequency_MHz=500):
    """Count once outside the receipted folder, then price immutable checkpoints."""
    from .model import Path,load,save,digest,hashlib,json,count_fingerprint,validate_artifacts,HERE
    from .run import count
    from .pricing import price
    case=Path(case_folder).resolve()
    if load(case/'case.json')['arch']!=arch: raise ValueError('architecture differs from case')
    fingerprint=count_fingerprint(case)
    tag=hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest()
    base=case.parent/'archx_artifacts'/case.name
    counts=base/'counts'/tag
    if not (counts/'manifest.json').exists(): count(case,counts)
    manifest=validate_artifacts(counts)
    if manifest['fingerprint']!=fingerprint: raise ValueError('count fingerprint differs')
    price_key=hashlib.sha256(json.dumps({'counts':digest(counts/'manifest.json'),
        'table':digest(energy_table_path),'frequency_MHz':frequency_MHz,
        'code':{n:digest(HERE/n) for n in ('pricing.py','model.py')}},sort_keys=True).encode()).hexdigest()
    return price(counts,energy_table_path,base/'energy'/price_key,frequency_MHz)
