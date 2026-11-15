"""Regression checks, including an actual Rust-backed archx graph harvest."""

import json
from pathlib import Path

import pytest

import energy_harvest as harvest


ROOT = Path(__file__).resolve().parent
ARCHX = ROOT.parents[2]


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    harvest.cap_threads()
    return harvest.harvest(ROOT, ARCHX, tmp_path_factory.mktemp("archx"))


def test_real_graph_has_all_modules(rows):
    assert len(rows) == 18
    assert {r["source"] for r in rows.values()} == {"archx_query_module_metric", harvest.PENDING}
    assert sum(bool(r["placeholder"]) for r in rows.values()) == 4
    for row in rows.values():
        assert row["technology_nm"] == row["query"]["technology"] == 7
        for key in ("dynamic_energy_nJ", "leakage_power_mW", "area_mm2"):
            if row["placeholder"]:
                assert row["placeholder"] == harvest.PENDING
                assert row[key] is None
            else:
                assert row[key] > 0


def test_width_and_pending_tree_geometry(rows):
    reg = rows["spinalflow.reg32.rmw"]
    add = rows["spinalflow.adder32.add"]
    cmp = rows["spinalflow.cmp32.compare"]
    tree = rows["spinalflow.min_tree4.compare"]
    for row in (reg, add):
        assert row["placeholder"] == harvest.PENDING
        assert all(row[k] is None for k in ("dynamic_energy_nJ", "leakage_power_mW", "area_mm2"))
        assert row["query"]["frequency"] == 500
    assert cmp["process"] == tree["process"] == "ASAP7"
    assert cmp["target_width_bits"] == 32
    assert tree["target_width_bits"] == 32
    assert tree["num_units"] == 3
    for key in ("dynamic_energy_nJ", "leakage_power_mW", "area_mm2"):
        assert tree[key] is None and cmp[key] is None


def test_queue_capacity_and_synthetic_voltage(rows):
    for module in ("input_spike_buffer", "output_spike_queue"):
        row = rows[f"spinalflow.{module}.read"]
        assert row["query"]["width"] == 32
        assert row["query"]["depth"] * 32 / 8 == 1024
        assert "synthetic" in row["voltage_model"]
        assert "assumed" in row["word_assumption"]
        assert row["query"]["interface"] == "cacti_fn"
        assert row["query"]["class"] == "sram"
    assert rows["spinalflow.input_spike_buffer.read"]["count_expression"] == "R"
    assert rows["spinalflow.input_spike_buffer.write"]["count_expression"] == "R"
    assert rows["spinalflow.output_spike_queue.write"]["count_expression"] == "O"
    assert rows["spinalflow.output_spike_queue.read"]["count_expression"] == "0"


def test_merge_preserves_other_designs_and_is_repeatable(tmp_path, rows):
    output = tmp_path / "energy.json"
    ptb = {"dynamic_energy_nJ": 1.23, "nested": [1, {"keep": True}]}
    output.write_text(json.dumps({"ptb.adder.add": ptb, "spinalflow.obsolete": {}}))
    harvest.write_table(output, rows)
    first = output.read_bytes()
    assert json.loads(first)["ptb.adder.add"] == ptb
    assert "spinalflow.obsolete" not in json.loads(first)
    harvest.write_table(output, rows)
    assert output.read_bytes() == first


def test_failure_does_not_overwrite_table(tmp_path, monkeypatch):
    output = tmp_path / "table.json"
    output.write_text('{"ptb.keep": 3}\n')
    def fail(*args):
        raise RuntimeError("graph failed")
    monkeypatch.setattr(harvest, "harvest", fail)
    with pytest.raises(RuntimeError, match="graph failed"):
        harvest.main(["--output", str(output)])
    assert output.read_text() == '{"ptb.keep": 3}\n'


def test_csv_provenance_rejects_missing_technology():
    with pytest.raises(ValueError, match="expected one"):
        harvest.csv_provenance(ARCHX, {"class": "tnn_reg", "technology": 45, "width": 32})


def test_upstream_cacti_report_parser(tmp_path):
    from archx.interface.cacti_fn.cacti_fn import parse_report_sram
    report = tmp_path / "memory.rpt"
    report.write_text("Number of banks: 2\nCycle time (ns): 2\n"
                      "Total dynamic read energy per access (nJ): 1.5e-3\n"
                      "Total dynamic write energy per access (nJ): 2e-3\n"
                      "Total leakage power of a bank (mW): 0.2\n"
                      "Cache height x width (mm): 0.1 x 0.3\n")
    assert parse_report_sram(str(report)) == pytest.approx((0.0015, 0.002, 0.4, 0.03, 500))
    report.write_text("Total dynamic read energy per access (nJ): invalid\n")
    with pytest.raises(AssertionError):
        parse_report_sram(str(report))
