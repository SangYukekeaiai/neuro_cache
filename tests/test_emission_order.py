"""Task 6: the arch binaries must emit sample-outer, tile-inner.

A stream consumer sees one sample's tiles contiguously, which is what lets it
emit a tile the moment every core has reported it. Under the old tile-outer
order it would have to buffer every sample before it could emit tile 1.
"""
import os
import struct
import sys


def record_order(path):
    """[(tile_idx, sample_idx), ...] in emission order, from out.bin."""
    out = []
    with open(path, "rb") as fh:
        data = fh.read()
    off = 0
    while off < len(data):
        tile_idx, sample_idx, _mac, n_ticks = struct.unpack_from("<iiii", data, off)
        off += 16
        for _ in range(n_ticks):
            _tick, n_addr = struct.unpack_from("<ii", data, off)
            off += 8 + 20 * n_addr
        out.append((tile_idx, sample_idx))
    return out


def test_sample_outer(path):
    order = record_order(path)
    samples = [s for _t, s in order]
    # Sample-outer means the sample index is non-decreasing over the whole file.
    assert samples == sorted(samples), f"not sample-outer: {samples[:20]}"
    # And within one sample the tile index ascends from 0.
    seen = {}
    for tile_idx, sample_idx in order:
        prev = seen.get(sample_idx, -1)
        assert tile_idx > prev, f"tiles out of order in sample {sample_idx}"
        seen[sample_idx] = tile_idx
    print(f"emission order: sample-outer over {len(set(samples))} samples, OK")


def main(argv):
    """Check the trace named on the command line, or skip saying why.

    The input is an `out.bin` an arch binary wrote, and none is checked in:
    producing one means running a binary over a corpus. So an absent input is a
    skip, not a failure, and the run stays green and unattended either way.
    """
    if len(argv) > 2:
        sys.exit(f"usage: {argv[0]} [out.bin]")
    path = argv[1] if len(argv) == 2 else os.environ.get("EMISSION_TRACE")
    if path is None:
        print("emission order: SKIP, no trace given. Pass an out.bin as the "
              "first argument or set EMISSION_TRACE.")
        return
    if not os.path.exists(path):
        print(f"emission order: SKIP, no such trace: {path}")
        return
    test_sample_outer(path)


if __name__ == "__main__":
    main(sys.argv)
