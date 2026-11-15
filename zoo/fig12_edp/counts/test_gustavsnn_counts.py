import subprocess
import sys

import pytest
import gustavsnn_counts as gustav
import spinalflow_counts as spinal

spinal.cap_threads(1)
import numpy as np


@pytest.mark.parametrize("cout,ratio", [(8, 2), (10, 1), (11, 1)])
def test_fetch_width_and_native_ho_refetch(tmp_path, cout, ratio):
    sys.path.insert(0, str(spinal.SRC))
    from lays.weight_trace_gen import NodeTileSpec
    from lays.weight_trace_gen.gustavsnn import native_bridge as native
    # Every spike appears in overlapping windows of both HO lanes.
    trace = np.ones((2, 1, 1, 2, 2), dtype=np.uint8)
    counts = gustav.count_sample(trace, 0, cout=cout, kernel=3, d_out=0.25)
    reference = spinal.count_sample(trace, 0, cout=cout, kernel=3)
    assert counts["A"] == reference["A"] == 32 * cout
    assert counts["R_g"] == ratio * reference["R"]
    slab = counts["cout_n"]
    dims = {0: 3, 1: 3, 2: 1, 3: slab, 4: 2, 5: 1, 6: 1}
    tiles = [NodeTileSpec(i, dims, {3: co, 4: 0, 5: wo, 6: t}, True)
             for i, (co, wo, t) in enumerate((co, wo, t) for co in range(0, cout, slab)
                                              for wo in range(2) for t in range(2))]
    (tmp_path / "trace").write_bytes(trace.tobytes())
    (tmp_path / "task").write_bytes(native._pack_task(trace.shape, tiles, [0], wave_width=2))
    subprocess.run([str(native._BINARY), str(tmp_path / "trace"), str(tmp_path / "task"), str(tmp_path / "out")], check=True)
    actual = sum(len(tick["weight_addresses"])
                 for _, _, _, ticks in native._unpack_output((tmp_path / "out").read_bytes(), len(tiles), [0])
                 for tick in ticks)
    assert actual == counts["R_g"]
    with pytest.raises(ValueError, match="d_out is required"):
        gustav.count_sample(trace, 0, cout=cout, kernel=3)
