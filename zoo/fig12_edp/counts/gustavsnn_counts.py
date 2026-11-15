"""GustavSNN per-spike fetches at the realized two-COUT slab width."""
import spinalflow_counts as spinal

FIELDS = ("T", "CIN", "Hin", "Win", "HO", "WO", "cout_n", "S_win", "A", "B",
          "R_g", "R_spinalflow", "fetch_ratio", "L", "O", "W_o", "d_out", "weight_bytes")


def count_sample(trace, sample, *, cout, kernel, stride=1, cout_n=None, d_out=None):
    slab = spinal.effective_cout_n(cout, 2)
    if cout_n is not None and cout_n != slab:
        raise ValueError("GustavSNN cout_n must match the campaign divisor capped at two")
    base = spinal.count_sample(trace, sample, cout=cout, kernel=kernel, stride=stride, cout_n=slab)
    if d_out is None:
        raise ValueError("d_out is required: use next-layer density, or an explicitly labeled final-layer proxy")
    density = float(d_out)
    if not 0 <= density <= 1:
        raise ValueError("d_out must be in [0,1]")
    spinal_slab = spinal.effective_cout_n(cout)
    return {**{k: base[k] for k in FIELDS[:9]}, "B": base["R"], "R_g": base["R"],
            "R_spinalflow": base["A"] // spinal_slab, "fetch_ratio": spinal_slab / slab,
            "L": base["O"], "O": density * base["O"], "W_o": density * base["O"],
            "d_out": density, "weight_bytes": base["A"]}


if __name__ == "__main__":
    from capture_counts import main
    raise SystemExit(main("gustavsnn", count_sample, FIELDS))
