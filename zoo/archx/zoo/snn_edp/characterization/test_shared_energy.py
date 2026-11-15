import pytest
from shared_harvest import report_value


def test_report_parser_rejects_missing_and_invalid_values():
    assert report_value("Activate Energy (nJ): 1.23e-2", "Activate Energy (nJ)") == 0.0123
    with pytest.raises(ValueError):
        report_value("Read Energy (nJ): -1", "Read Energy (nJ)")
    with pytest.raises(ValueError):
        report_value("unrelated", "Read Energy (nJ)")


def test_delivered_shared_costs_and_ddr4_identity():
    import json
    from pathlib import Path
    root = Path(__file__).parent
    rows = json.loads((root.parent / "energy_table.json").read_text())
    dram = rows["shared.ddr4.read"]
    assert dram["dynamic_energy_nJ"] == pytest.approx(dram["activate_nJ"] + dram["precharge_nJ"] + 8 * dram["array_read_nJ"])
    assert dram["leakage_power_mW"] > 0
    assert rows["shared.ddr4_io.byte"]["dynamic_energy_nJ"] > 0
    assert rows["shared.router.hop"]["placeholder"] == "pending-ASAP7-synthesis"
    assert all(rows["shared.router.hop"][k] is None for k in ("dynamic_energy_nJ", "leakage_power_mW", "area_mm2"))
    assert rows["shared.link.hop"]["dynamic_energy_nJ"] > 0
    query = rows["shared.gb.read"]["query"]
    assert query["width"] * query["depth"] // 8 == 2 * 1024 * 1024
    for component in ('router', 'link'):
        assert set(rows[f'shared.{component}.hop']['applies_to']) == {'spad','cacheA','cacheB'}


def test_optional_harvest_reports_confirm_ddr4():
    import re
    from pathlib import Path
    reports=[Path(__file__).parent/'shared_stub'/f'ddr4_{state}.rpt' for state in ('READ','IDLE')]
    if not all(path.exists() for path in reports):
        pytest.skip('optional harvest reports absent; regenerate with energy_harvest.py --design shared')
    for path in reports:
        assert re.search(r'io_type\s*:\s*DDR4',path.read_text())
