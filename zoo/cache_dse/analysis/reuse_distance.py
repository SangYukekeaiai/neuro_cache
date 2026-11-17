"""Exact LRU reuse (stack) distance over one WCTS weight trace.

Reads one .wcts stream (format: src/lays/cachesim/stream.py), linearizes each
COUT burst to 64-byte lines of the canonical row-major [KH][KW][CIN][COUT]
weight layout at 1 byte/weight (the campaign's weight_bytes), merges cores
within a tile by local_tick (the order a shared cache sees), and computes the
exact LRU stack distance of every line access: the number of DISTINCT lines
touched since that line's previous access. First-ever accesses count as cold.

Output: one CSV `layer,sample,kind,bin_lo,count` where kind is "reuse"
(log2 bin: bin_lo <= d < 2*bin_lo, with bin_lo=0 meaning d==0) or "cold"
(bin_lo=-1). Distances are in units of 64-byte lines.

Stdlib only. Usage: python reuse_distance.py TRACE.wcts LAYER SAMPLE OUT.csv
"""
import struct
import sys
from array import array

LINE_BYTES = 64


def parse_accesses(path):
    """Yields line ids in replay order (tiles in order; cores tick-merged)."""
    with open(path, "rb") as fh:
        magic = fh.read(8)
        assert magic == b"WCTRACE1", magic
        fixed = struct.unpack("<IIiiiiiiiiii", fh.read(48))
        (_ver, header_bytes, n_tiles, _n_cores, weight_bytes, _bdim, _bstride,
         _bspan, n_addr, n_spatial, n_dims, ident_bytes) = fixed
        assert weight_bytes == 1, weight_bytes
        fh.read(4 * n_addr)
        fh.read(8 * n_spatial)
        dims = {}
        for _ in range(n_dims):
            d, extent = struct.unpack("<ii", fh.read(8))
            dims[d] = extent
        fh.read(ident_bytes)
        # wire codes: 0=KH 1=KW 2=CIN 3=COUT
        kw_e, cin_e, cout_e = dims[1], dims[2], dims[3]

        burst = struct.Struct("<q5i")
        for _tile in range(n_tiles):
            head = fh.read(4)
            first = struct.unpack("<i", head)[0]
            if first == -1:
                break
            _n_tc, _mac, _payload = struct.unpack("<iqQ", fh.read(20))
            entries = []  # (tick, core_id, seq, kh, kw, cin, c0, c1)
            for _ in range(_n_tc):
                core_id, n_bursts = struct.unpack("<ii", fh.read(8))
                raw = fh.read(burst.size * n_bursts)
                for j in range(n_bursts):
                    tick, kh, kw, cin, c0, c1 = burst.unpack_from(raw, j * burst.size)
                    entries.append((tick, core_id, kh, kw, cin, c0, c1))
            entries.sort(key=lambda e: (e[0], e[1]))
            for tick, core_id, kh, kw, cin, c0, c1 in entries:
                base = ((kh * kw_e + kw) * cin_e + cin) * cout_e
                lo = (base + c0) // LINE_BYTES
                hi = (base + c1 - 1) // LINE_BYTES
                for line in range(lo, hi + 1):
                    yield line


def stack_distances(accesses):
    """Exact LRU stack distance per access; yields -1 for cold."""
    stream = array("q", accesses)
    n = len(stream)
    bit = array("q", bytes(8 * (n + 1)))  # Fenwick over access positions

    def add(i, v):
        i += 1
        while i <= n:
            bit[i] += v
            i += i & (-i)

    def prefix(i):  # sum of positions [0, i]
        i += 1
        s = 0
        while i > 0:
            s += bit[i]
            i -= i & (-i)
        return s

    last = {}
    out = array("q", bytes(8 * n))
    for t in range(n):
        b = stream[t]
        p = last.get(b)
        if p is None:
            out[t] = -1
        else:
            # distinct lines touched strictly between p and t
            out[t] = prefix(t - 1) - prefix(p)
            add(p, -1)
        add(t, 1)
        last[b] = t
    return out, n


def main():
    trace, layer, sample, out_csv = sys.argv[1:5]
    dists, n = stack_distances(parse_accesses(trace))
    cold = 0
    bins = {}  # log2 bin_lo -> count
    for d in dists:
        if d < 0:
            cold += 1
        elif d == 0:
            bins[0] = bins.get(0, 0) + 1
        else:
            lo = 1 << (d.bit_length() - 1)
            bins[lo] = bins.get(lo, 0) + 1
    with open(out_csv, "w") as fh:
        fh.write("layer,sample,kind,bin_lo,count\n")
        fh.write(f"{layer},{sample},cold,-1,{cold}\n")
        for lo in sorted(bins):
            fh.write(f"{layer},{sample},reuse,{lo},{bins[lo]}\n")
    print(f"{trace}: {n} line accesses, {cold} cold, {n - cold} reuses")


if __name__ == "__main__":
    main()
