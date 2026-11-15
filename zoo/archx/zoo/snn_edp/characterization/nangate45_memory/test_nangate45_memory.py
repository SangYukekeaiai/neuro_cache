"""Checks for geometry preservation, report identities and excluded operations."""
import importlib.util
import json
from pathlib import Path
import re
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("memory45", HERE.parent / "nangate45_memory.py")
memory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory)


class MemoryPricesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = json.loads((HERE / "memory_prices.json").read_text())
        cls.table = json.loads((HERE / "source_table.json").read_text())
        cls.policy = json.loads((HERE / "source_policy.json").read_text())
        cls.queries = json.loads((HERE / "queries.json").read_text())

    def test_complete_coverage_and_exclusions(self):
        expected = set(memory.selected_rows(self.table, self.policy)) | {"shared.link.hop"}
        self.assertEqual(set(self.result["operations"]), expected)
        self.assertEqual(len(expected), 39)
        self.assertEqual(len(self.policy["excluded_operations"]), 9)
        self.assertFalse(expected & set(self.policy["excluded_operations"]))
        self.assertFalse(any("ddr4" in key for key in expected))

    def test_cache_geometry_and_ports(self):
        base = (memory.CACTI / "sram.cfg").read_text()
        for key, size, ways in (("cache.l1.read", 16384, 8), ("cache.l2.read", 524288, 16)):
            g = memory.geometry(self.table[key]["query"])
            self.assertEqual((g["size_bytes"], g["block_bytes"], g["bank"], g["associativity"]), (size, 64, 1, ways))
            cfg = memory.config_text(g, base)
            for line in ('-cache type "cache"', '-read-write port 1', '-exclusive read port 0', '-exclusive write port 0'):
                self.assertIn(line, cfg.splitlines())
            self.assertEqual(len(re.findall(r"^-technology ", cfg, re.M)), 1)

    def test_no_implicit_byte_rounding(self):
        with self.assertRaises(ValueError):
            memory.geometry({"class": "sram", "width": 13, "depth": 256, "bank": 1})

    def test_native_report_and_config_identities(self):
        for query in self.queries.values():
            report = HERE / query["report"]
            cfg = HERE / query["config"]
            metrics = memory.parse_report(report.read_text(), query["geometry"])
            self.assertEqual(metrics, query["metrics"])
            self.assertEqual(memory.sha(report), query["report_sha256"])
            self.assertEqual(memory.sha(cfg), query["config_sha256"])
            self.assertAlmostEqual(metrics["fmax_MHz"] * metrics["cycle_time_ns"], 1000)
            self.assertEqual(metrics["area_mm2"], metrics["height_mm"] * metrics["width_mm"])
            self.assertEqual(metrics["leakage_power_mW"], (metrics["leakage_per_bank_mW"] + metrics["gate_leakage_per_bank_mW"]) * query["geometry"]["bank"])

    def test_wrong_technology_report_rejected(self):
        query = next(iter(self.queries.values()))
        text = (HERE / query["report"]).read_text()
        with self.assertRaises(ValueError):
            memory.parse_report(text.replace("Technology size (nm): 45", "Technology size (nm): 7"), query["geometry"])
        with self.assertRaises(ValueError):
            memory.report_number("Associativity: 8\nAssociativity: 16\n", "Associativity")

    def test_price_per_access_and_physical_unit(self):
        for key, row in self.result["operations"].items():
            if key == "shared.link.hop":
                continue
            evidence = row["provenance"]
            metric = evidence["reported_metrics"]
            self.assertEqual(row["dynamic_energy_nJ"], metric[self.table[key]["operation"] + "_nJ"])
            self.assertEqual(row["area_mm2"], metric["area_mm2"])
            self.assertEqual(row["leakage_power_mW"], metric["leakage_power_mW"])
            self.assertEqual(evidence["characterization_technology_nm"], 45)
            self.assertEqual(evidence["geometry_scaling"], 1)
        self.assertEqual(self.result["operations"]["cache.l1.read"]["provenance"]["physical_instances"], 16)

    def test_wire_capacitance_and_packet_units(self):
        wire = self.result["operations"]["shared.link.hop"]
        p = wire["provenance"]
        # Independent substitution of conservative/global column6 of45nm.dat.
        cap = 2 * 8.854e-18 * 3.9 * 0.18 / 0.55 + 2 * 8.854e-18 * 1.5 * 2.46 * 0.396 / 0.18 + 1.15e-16
        self.assertAlmostEqual(p["capacitance_F_per_um"] / cap, 1)
        self.assertAlmostEqual(wire["dynamic_energy_nJ"] / (0.5 * cap * 1000 * 0.7**2 * 320 * 1e9), 1)
        self.assertEqual((wire["area_mm2"], wire["leakage_power_mW"]), (0, 0))
        self.assertEqual(p["characterization_technology_nm"], 45)


if __name__ == "__main__":
    unittest.main()
