import json
import csv
import energy_harvest as harvest
from test_energy_harvest import ROOT, ARCHX


def test_cache_inventory_and_config_geometry(tmp_path):
    harvest.cap_threads()
    rows = harvest.harvest(ROOT, ARCHX, tmp_path, "cache")
    assert rows["cache.distance_metadata.read"]["query"]["depth"] * 8 == 65536
    assert rows["cache.next_access_state.rmw"]["physical_instances"] * 4 == 192
    for level in ("l1", "l2"):
        assert rows[f"cache.{level}_tags.read"]["physical_instances"] == 0
    for row in rows.values():
        if row.get("pricing_status") == "excluded by decision (prefetch control)":
            assert not row["placeholder"]
            assert all(row[k] == 0 for k in ("dynamic_energy_nJ", "leakage_power_mW", "area_mm2"))
        elif row["placeholder"]:
            assert row["placeholder"] == harvest.PENDING
            assert all(row[k] is None for k in ("dynamic_energy_nJ", "leakage_power_mW", "area_mm2"))
        else:
            assert all(row[k] is not None and row[k] > 0 for k in ("dynamic_energy_nJ", "leakage_power_mW", "area_mm2"))


def test_cache_count_expressions_against_native_header():
    import ast
    rows = json.loads((ROOT.parent / "energy_table.json").read_text())
    expected = {'cache.l1.read': 'l1_accesses', 'cache.l1.write': 'l1_accesses-l1_hits+pf_issued-pf_dropped_array_hit-pf_dropped_matching-pf_dropped_no_slot-pf_dropped_targets_full-pf_dropped_reserve', 'cache.l2.read': 'l2_accesses', 'cache.l2.write': 'dram_accesses', 'cache.l1_tags.read': '2*pf_issued+pf_budget_exhausted', 'cache.l2_tags.read': 'l2_pf_issued+pf_issued-pf_dropped_array_hit-pf_dropped_matching-pf_dropped_no_slot-pf_dropped_targets_full-pf_dropped_reserve', 'cache.distance_metadata.read': 'l1_accesses', 'cache.distance_metadata.write': 'l1_accesses', 'cache.next_access_state.rmw': '3*pf_issued', 'cache.mshr_cam_l1.search': 'l1_accesses-l1_hits+l1_accesses-l1_hits+pf_issued-pf_dropped_array_hit-pf_dropped_matching-pf_dropped_no_slot-pf_dropped_targets_full-pf_dropped_reserve', 'cache.mshr_cam_l2.search': 'l2_accesses-l2_hits+dram_accesses', 'cache.mshr_targets_l1.write': 'l1_accesses-l1_hits', 'cache.mshr_targets_l2.write': 'l2_accesses-l2_hits', 'cache.next_access_logic.step': 'pf_issued', 'cache.distance_logic.step': 'l2_pf_issued', 'cache.next_line_l1.add': 'pf_issued', 'cache.next_line_l2.add': 'l2_pf_issued'}
    header = next(csv.reader((ROOT.parent / "fixtures/spinalflow/cache_a.csv").open()))
    for key, expression in expected.items():
        assert rows[key]["count_expression"] == expression
        names = {node.id for node in ast.walk(ast.parse(str(expression), mode="eval")) if isinstance(node, ast.Name)}
        assert names <= set(header), (key, names - set(header))
