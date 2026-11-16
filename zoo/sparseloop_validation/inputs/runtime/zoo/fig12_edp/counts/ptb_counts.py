"""PTB counts: OR-over-time fetches, per-spike accumulates, and LIF sweep."""
import spinalflow_counts as spinal

FIELDS = ("T", "CIN", "Hin", "Win", "HO", "WO", "cout_n", "S_or", "S_sum",
          "B", "A", "L", "O", "d_out", "weight_bytes")


def count_sample(trace, sample, *, cout, kernel, stride=1, cout_n=None, d_out=None):
    import numpy as np
    base = spinal.count_sample(trace, sample, cout=cout, kernel=kernel,
                               stride=stride, cout_n=cout_n)
    if base["T"] > 32:
        raise ValueError("PTB campaign time window is 32; capture exceeds it")
    active = np.asarray(trace[:, sample]) != 0
    coverage = spinal.window_coverage(base["Hin"], base["Win"], kernel, stride)
    s_or = int(np.einsum("chw,hw->", np.any(active, axis=0), coverage,
                        dtype=np.int64, optimize=False))
    if d_out is None:
        raise ValueError("d_out is required: use next-layer density, or an explicitly labeled final-layer proxy")
    density = float(d_out)
    if not 0 <= density <= 1:
        raise ValueError("d_out must be in [0, 1]")
    return {**{k: base[k] for k in FIELDS[:7]}, "S_or": s_or, "S_sum": base["S_win"],
            "B": s_or * cout // base["cout_n"], "A": base["A"], "L": base["O"],
            "O": density * base["O"], "d_out": density, "weight_bytes": s_or * cout}


if __name__ == "__main__":
    from capture_counts import main
    raise SystemExit(main("ptb", count_sample, FIELDS))
