import energy_harvest as harvest
from test_energy_harvest import ROOT, ARCHX


def test_prosperity_graph(tmp_path):
    harvest.cap_threads()
    rows = harvest.harvest(ROOT, ARCHX, tmp_path, "prosperity")
    assert rows["prosperity.tcam.search"]["placeholder"] == harvest.PENDING
    assert rows["prosperity.tcam.search"]["physical_instances"] == 2
    assert rows["prosperity.tcam.search"]["count_expression"] == "N_rows"
    assert rows["prosperity.ps_table.read"]["query"]["width"] * rows["prosperity.ps_table.read"]["query"]["depth"] // 8 == 1536
    assert rows["prosperity.psum_buffer.read"]["count_expression"] == "seed_reads_bound"
    assert rows["prosperity.adder16.add"]["count_expression"] == "A_p"
    assert not any("sfu" in key for key in rows)
    assert harvest.PENDING == "pending-ASAP7-synthesis"
    for row in rows.values():
        values = [row[k] for k in ("dynamic_energy_nJ", "leakage_power_mW", "area_mm2")]
        if row["placeholder"]:
            assert row["placeholder"] == "pending-ASAP7-synthesis"
            assert all(v is None for v in values)
        else:
            assert all(v > 0 for v in values)
    assert rows["prosperity.lif_core.step"]["query"]["state_register"] is False
    assert rows["prosperity.lif_state.rmw"]["count_expression"] == "L"
