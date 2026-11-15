import energy_harvest as harvest
from test_energy_harvest import ROOT, ARCHX


def test_gustav_geometry_and_register_state(tmp_path):
    harvest.cap_threads()
    rows = harvest.harvest(ROOT, ARCHX, tmp_path, "gustavsnn")
    assert rows["gustavsnn.l1_weight_spad.read"]["query"]["width"] == 16
    assert rows["gustavsnn.merger_tree2.merge"]["query"]["inputs"] == 2
    assert rows["gustavsnn.lif_core.step"]["query"]["state_register"] is False
    reg = rows["gustavsnn.potential_regfile.rmw"]
    assert reg["placeholder"] == harvest.PENDING
    assert reg["query"]["class"] == "register_file"
    assert reg["query"]["depth"] * reg["query"]["width"] * reg["physical_instances"] // 8 == 1024
    assert rows["gustavsnn.output_fifo.push"]["count_expression"] == "W_o/32"
    assert not any("vmem" in key or "merger_tree4" in key for key in rows)
    for row in rows.values():
        if row["placeholder"]:
            assert row["placeholder"] == harvest.PENDING
            assert all(row[k] is None for k in ("dynamic_energy_nJ", "leakage_power_mW", "area_mm2"))
        else:
            assert all(row[k] is not None for k in ("dynamic_energy_nJ", "leakage_power_mW", "area_mm2"))
