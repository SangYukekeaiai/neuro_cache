"""Read stored per-step MAC maxima without materializing WCTS addresses."""

import math
import struct
from pathlib import Path

from lays.cachesim.stream import WCTS_ADDR_FIELDS, WCTS_DIM_CODES, WCTS_MAGIC
from lays.nocsim.step_cycles import StepCycles
from lays.weight_trace_gen import ComputeCycles


def load_wcts_cycles(path, artifact, schedule):
    """Read native WCTS v2/v3, checking identity, framing and burst totals.

    Frames are dram-major/noc-minor. Their mac_cycles is already MAX over
    cores, including idle cycles; burst counts/ticks are never cycle proxies.
    Address records are skipped using checked lengths. This is a cycle
    reader, not an address-semantic validator. WCTS carries no separate LIF
    duration: None preserves the upstream generated-step convention (zero
    extra LIF COUNT time, with real k/t-chain traffic still emitted).
    """
    path = Path(path)
    length = path.stat().st_size
    with path.open("rb") as stream:
        def read(fmt):
            n = struct.calcsize(fmt)
            data = stream.read(n)
            if len(data) != n:
                raise ValueError(f"{path}: truncated WCTS")
            return struct.unpack(fmt, data)

        if stream.read(8) != WCTS_MAGIC:
            raise ValueError(f"{path}: invalid WCTS magic")
        (version, header_bytes, n_tiles, n_cores, weight_bytes, burst_dim,
         stride, span, n_fields, n_spatial, n_dims, identity_bytes) = read("<II10i")
        if (version not in (2, 3) or n_tiles < 1 or n_cores < 1
                or weight_bytes < 1 or burst_dim not in range(4)
                or stride < 1 or span < 1 or n_fields != 5
                or not 0 <= n_spatial <= 7 or n_dims != 7
                or not 4 <= identity_bytes <= 1024 * 1024
                or header_bytes != 56 + 4 * n_fields + 8 * (n_spatial + n_dims) + identity_bytes
                or header_bytes > length - 12):
            raise ValueError(f"{path}: invalid WCTS header")
        if read("<5i") != WCTS_ADDR_FIELDS:
            raise ValueError(f"{path}: invalid address fields")

        def dimensions(n):
            pairs = [read("<ii") for _ in range(n)]
            if (len({k for k, _ in pairs}) != n
                    or any(k not in range(7) or v < 1 for k, v in pairs)):
                raise ValueError(f"{path}: invalid dimensions/spatial factors")
            return dict(pairs)

        spatial = dimensions(n_spatial)
        dims = dimensions(n_dims)
        if math.prod(spatial.values()) != n_cores:
            raise ValueError(f"{path}: spatial product differs from n_cores")
        if any(spatial.get(k, 1) != schedule.spatial_factors[k] for k in range(7)):
            raise ValueError(f"{path}: WCTS spatial factors differ from schedule")
        raw = stream.read(identity_bytes)
        fields = raw.split(b"\0")
        if len(raw) != identity_bytes or len(fields) != 5 or fields[-1] != b"":
            raise ValueError(f"{path}: malformed WCTS identity")
        arch, workload, layer, sample = (f.decode("utf-8") for f in fields[:4])
        sample = int(sample)
        if sample < 0 or n_tiles != schedule.dram_num_steps * schedule.noc_num_steps:
            raise ValueError(f"{path}: sample/tile count does not match schedule")
        expected_dims = artifact.workload.get("problem", artifact.workload)
        if any(dims[code] != expected_dims[name] for name, code in WCTS_DIM_CODES.items()):
            raise ValueError(f"{path}: workload dimensions differ from schedule")
        by_step, total_bursts = {}, 0
        for expected in range(n_tiles):
            tile, n_blocks, mac_cycles, payload = read("<iiqQ")
            end = stream.tell() + payload
            if (tile != expected or not 0 <= n_blocks <= n_cores or mac_cycles < 0
                    or end > length - 12 or payload < 8 * n_blocks):
                raise ValueError(f"{path}: invalid tile frame {expected}")
            previous = -1
            for _ in range(n_blocks):
                if stream.tell() + 8 > end:
                    raise ValueError(f"{path}: truncated core header")
                core, bursts = read("<ii")
                if not previous < core < n_cores or bursts < 1 or stream.tell() + bursts * 28 > end:
                    raise ValueError(f"{path}: invalid core block in tile {tile}")
                previous = core
                total_bursts += bursts
                stream.seek(bursts * 28, 1)
            if stream.tell() != end:
                raise ValueError(f"{path}: tile payload length mismatch")
            by_step[divmod(tile, schedule.noc_num_steps)] = ComputeCycles(mac_cycles, None)
        marker, declared = read("<iQ")
        if marker != -1 or declared != total_bursts or stream.read(1):
            raise ValueError(f"{path}: invalid WCTS trailer/burst count")
    cycles = StepCycles(by_step, arch, workload, layer, sample, expected_dims,
                        schedule.dram_num_steps, schedule.noc_num_steps)
    cycles.check_against(artifact, schedule)
    return cycles
