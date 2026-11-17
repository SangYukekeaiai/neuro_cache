"""Power and area breakdown table: scratchpad baseline vs cache A.

One operating point (arch loas, B09 spiking VGG16 T=4), ASAP7 1 GHz pricing
(energy_table_asap7_1ghz.json), the same Stage-B arithmetic as
asap7_reprice.py (its physical()/instances() are imported and reused).
Per category: area = deduplicated physical inventory of the arm's
operations; power = dynamic (whole-model E_dyn / whole-model T, mean over
samples) + standing leakage.
Run: conda run -n gurobi python table_power_area.py
"""
import csv
import ast
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from asap7_reprice import ROWS, NEW_TABLE, physical, instances  # noqa: E402

ARCH = "loas"
CAPTURE = "A07/spikinglm_t4_T4_n500"
ARMS = ("spad", "cacheA")
SRAMISH = ("spad", "buffer", "fifo", "queue", "sram", "rf")


def excluded(key: str) -> bool:
    return "mshr" in key


def category(key: str) -> str:
    ns, module, _ = key.split(".")
    if ns == "shared":
        if module.startswith("ddr4"):
            return "DRAM"
        if module in ("router", "link"):
            return "NoC"
        if module == "gb":
            return "Global buffer"
        return "Shared other"
    if ns == "cache":
        if "l1" in module:
            return "L1 cache"
        if "l2" in module:
            return "L2 cache"
        return "Prefetch metadata"
    if any(s in module for s in SRAMISH):
        return "Node buffers"
    return "Compute logic"


def main() -> None:
    table = json.loads(NEW_TABLE.read_text())
    # per arm/sample: E_dyn per category, T total; per arm: inventory
    dyn = defaultdict(lambda: defaultdict(float))   # (arm, sample) -> cat -> nJ
    T = defaultdict(float)                          # (arm, sample) -> s
    inv_keys = defaultdict(set)                     # arm -> union of op keys
    layers = defaultdict(set)
    for sdir in sorted(ROWS.glob("sample_*")):
        sample = sdir.name
        with (sdir / "results_ng45.csv").open(newline="") as fh:
            for r in csv.DictReader(fh):
                if r["arch"] != ARCH or r["capture"] != CAPTURE or r["arm"] not in ARMS:
                    continue
                breakdown = ast.literal_eval(r["breakdown"])
                for key, spec in breakdown.items():
                    if excluded(key):
                        continue
                    dyn[(r["arm"], sample)][category(key)] += (
                        spec["count"] * table[key]["dynamic_energy_nJ"])
                    inv_keys[r["arm"]].add(key)
                T[(r["arm"], sample)] += float(r["T_s"])
                layers[(r["arm"], sample)].add(r["layer"])
    n_layers = {len(v) for v in layers.values()}
    assert len(n_layers) == 1, n_layers
    print(f"layers per model: {n_layers}")
    samples = sorted({s for (_, s) in T})
    print(f"samples: {len(samples)}; arms: {sorted(inv_keys)}")

    # standing leakage and area per category, deduplicated per arm
    leak = defaultdict(lambda: defaultdict(float))  # arm -> cat -> mW
    area = defaultdict(lambda: defaultdict(float))  # arm -> cat -> mm2
    for arm, keys in inv_keys.items():
        seen = set()
        for key in sorted(keys):
            if excluded(key):
                continue
            row = table[key]
            name = physical(key, row)
            if name in seen:
                continue
            seen.add(name)
            cat = category(key)
            leak[arm][cat] += row["leakage_power_mW"] * instances(key, row)
            area[arm][cat] += row["area_mm2"] * instances(key, row)

    # dynamic power per category: mean over samples of E_dyn/T
    pdyn = defaultdict(lambda: defaultdict(float))
    for arm in ARMS:
        for cat in {c for s in samples for c in dyn[(arm, s)]}:
            vals = [dyn[(arm, s)].get(cat, 0.0) / T[(arm, s)] * 1e-6 for s in samples]
            pdyn[arm][cat] = sum(vals) / len(vals)   # mW

    CATS = ["Compute logic", "Node buffers", "L1 cache", "L2 cache",
            "Prefetch metadata", "Global buffer", "NoC", "DRAM"]
    print(f"\n{'Component':18s} {'Area mm2':>9s} {'Area mm2':>9s} {'Power mW':>9s} {'Power mW':>9s}")
    print(f"{'':18s} {'spad':>9s} {'cacheA':>9s} {'spad':>9s} {'cacheA':>9s}")
    tot = defaultdict(float)
    lines = []
    for cat in CATS:
        a_s, a_c = area["spad"].get(cat, 0.0), area["cacheA"].get(cat, 0.0)
        if cat == "DRAM":
            a_s = a_c = 0.0   # off-chip commodity part: power counted, area excluded
        p_s = pdyn["spad"].get(cat, 0.0) + leak["spad"].get(cat, 0.0)
        p_c = pdyn["cacheA"].get(cat, 0.0) + leak["cacheA"].get(cat, 0.0)
        if max(a_s, a_c, p_s, p_c) == 0:
            continue
        tot["as"] += a_s; tot["ac"] += a_c; tot["ps"] += p_s; tot["pc"] += p_c
        print(f"{cat:18s} {a_s:9.3f} {a_c:9.3f} {p_s:9.1f} {p_c:9.1f}")
        lines.append((cat, a_s, a_c, p_s, p_c))
    print(f"{'Total':18s} {tot['as']:9.3f} {tot['ac']:9.3f} {tot['ps']:9.1f} {tot['pc']:9.1f}")

    def fmt_a(v):
        return "--" if v == 0 else f"{v:.3f}"

    def fmt_p(v):
        return "--" if v == 0 else f"{v:.1f}"

    tex = [
        "\\begin{table}[t]",
        "    \\centering",
        "    \\caption{Power and area breakdown of the scratchpad baseline"
        " and cache~A (loas, SpikingLM, ASAP7 at 1\\,GHz; area is on-chip,"
        " off-chip DRAM contributes power only; MSHRs excluded).}",
        "    \\label{tab:power-area}",
        "    \\begingroup",
        "    \\setlength{\\tabcolsep}{3pt}",
        "    \\renewcommand{\\arraystretch}{1.0}",
        "    \\begin{adjustbox}{width=\\columnwidth}",
        "    \\begin{tabular}{@{}lrrrr@{}}",
        "        \\toprule",
        "        \\multirow{2}{*}{\\textbf{Component}} &"
        " \\multicolumn{2}{c}{\\textbf{Area [mm$^2$]}} &"
        " \\multicolumn{2}{c}{\\textbf{Power [mW]}} \\\\",
        "        \\cmidrule(lr){2-3}\\cmidrule(l){4-5}",
        "        & spad & cache A & spad & cache A \\\\",
        "        \\midrule",
    ]
    for cat, a_s, a_c, p_s, p_c in lines:
        tex.append(f"        {cat} & {fmt_a(a_s)} & {fmt_a(a_c)} & {fmt_p(p_s)} & {fmt_p(p_c)} \\\\")
    tex += [
        "        \\midrule",
        f"        \\textbf{{Total}} & {tot['as']:.3f} & {tot['ac']:.3f} & {tot['ps']:.1f} & {tot['pc']:.1f} \\\\",
        "        \\bottomrule",
        "    \\end{tabular}",
        "    \\end{adjustbox}",
        "    \\endgroup",
        "\\end{table}",
    ]
    out = HERE / "results_asap7_20261116" / "table_power_area.tex"
    out.write_text("\n".join(tex) + "\n")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
