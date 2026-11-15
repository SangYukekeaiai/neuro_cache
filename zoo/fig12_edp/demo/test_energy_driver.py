"""The campaign calls the zoo API on saved inputs and fingerprints its sources."""
import shutil

from zoo.fig12_edp import energy_driver as driver
from snn_edp import archx_aggregate_case
from snn_edp.model import load


def test_external_case_uses_the_standalone_api(tmp_path):
    assert driver.archx_aggregate_case is archx_aggregate_case
    source = driver.MODEL_ROOT/'fixtures/spinalflow'
    case = tmp_path/'external/sample_00000'
    shutil.copytree(source, case)
    original = {str(p.relative_to(case)): p.read_bytes() for p in case.rglob('*') if p.is_file()}
    actual = driver.archx_aggregate_case('spinalflow', case, driver.ENERGY_TABLE)
    expected = load(driver.MODEL_ROOT/'runs/spinalflow/fixture_priced/result.json')['rows']
    for row, ref in zip(actual, expected):
        for field in ('total_cycles','T_s','E_dyn_nJ','E_leak_nJ','EDP_nJ_s','area_mm2','breakdown'):
            assert row[field] == ref[field]
    assert len(actual) == 3
    assert original == {str(p.relative_to(case)): p.read_bytes() for p in case.rglob('*') if p.is_file()}


def test_model_sources_are_separately_namespaced():
    files = driver.scientific_files()
    assert files['snn_edp/designs/snn/description.py'].is_file()
    assert files['snn_edp/hardware.json'].is_file()
    assert files['snn_edp/pricing.py'].is_file()
    assert all(p.is_relative_to(driver.MODEL_ROOT) for p in files.values())
    assert not any('energy_table' in name or '/runs/' in name for name in files)


def test_default_model_and_backend_use_vendor():
    from pathlib import Path
    import archx
    import snn_edp
    assert driver.MODEL_ROOT == driver.HERE.parent/'archx/zoo/snn_edp'
    assert Path(archx.__file__).resolve() == driver.HERE.parent/'archx/src/archx/__init__.py'
    assert snn_edp.BACKEND_ROOT == driver.HERE.parent/'archx'
