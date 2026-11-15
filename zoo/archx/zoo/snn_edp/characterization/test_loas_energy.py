import energy_harvest as harvest
from test_energy_harvest import ROOT, ARCHX


def test_loas_graph(tmp_path):
    harvest.cap_threads()
    rows = harvest.harvest(ROOT, ARCHX, tmp_path, "loas")
    assert rows["loas.adder16.add"]["physical_instances"] == 128
    assert rows["loas.reg16.rmw"]["physical_instances"] == 128
    assert rows["loas.bsf32.scan"]["count_expression"] == "A/cout_n"
    assert rows["loas.spike_prefix_scan32.scan"]["count_expression"] == "B"
    assert rows["loas.and_gate.and"]["count_expression"] == "32*B"
    assert rows["loas.output_fifo.push"]["count_expression"] == "W_o"
    assert rows["loas.lif_unit.step"]["physical_instances"] == 4
    for key, row in rows.items():
        assert row["technology_nm"] == 7
        if row["placeholder"]:
            assert row["placeholder"] == harvest.PENDING
            assert all(row[k] is None for k in ("dynamic_energy_nJ", "leakage_power_mW", "area_mm2"))
        else:
            assert row["dynamic_energy_nJ"] > 0
    assert not any("merge" in key for key in rows)
