import energy_harvest as harvest
import pytest
from test_energy_harvest import ROOT, ARCHX


def test_ptb_graph_and_preservation(tmp_path):
    harvest.cap_threads()
    rows = harvest.harvest(ROOT, ARCHX, tmp_path / "graph", "ptb")
    assert all(key.startswith("ptb.") for key in rows)
    assert all(r["technology_nm"] == 7 for r in rows.values())
    assert rows["ptb.reg16.rmw"]["physical_instances"] == 128
    assert rows["ptb.adder16.add"]["dynamic_energy_nJ"] is None
    assert rows["ptb.adder16.add"]["placeholder"] == harvest.PENDING
    assert rows["ptb.lif_unit.step"]["placeholder"] == harvest.PENDING
    assert rows["ptb.lif_unit.step"]["dynamic_energy_nJ"] is None
    for name in ("weight_fifo", "spike_fifo"):
        for op in ("push", "pop"):
            row = rows[f"ptb.{name}.{op}"]
            assert row["query"]["depth"] == 8 and row["query"]["width"] == 16
            assert row["count_expression"] == "B"
    output = tmp_path / "table.json"
    output.write_text('{"spinalflow.keep": {"value": 42}, "ptb.old": {}}')
    harvest.write_table(output, rows, "ptb")
    import json
    table = json.loads(output.read_text())
    assert table["spinalflow.keep"] == {"value": 42}
    assert "ptb.old" not in table


def test_ptb_rejects_non_asap7_technology(tmp_path):
    harvest.cap_threads()
    architecture = (ROOT / "ptb.architecture.yaml").read_text().replace("technology: 7", "technology: 45")
    (tmp_path / "ptb.architecture.yaml").write_text(architecture)
    with pytest.raises(ValueError, match="violates the 7 nm tech-mapping rule"):
        harvest.harvest(tmp_path, ARCHX, tmp_path / "graph", "ptb")
