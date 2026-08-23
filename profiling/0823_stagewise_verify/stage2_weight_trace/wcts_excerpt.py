#!/usr/bin/env python3
"""Decode a WCTS v1 dump into a readable excerpt.

Layout is src/tracegen.py's writer: write_stream_header:397, write_tile_frame:436,
write_stream_trailer:466. Wire dim codes are 0=KH 1=KW 2=CIN 3=COUT 4=HO 5=WO 6=T.
"""
import struct, sys

DIM = {0: "KH", 1: "KW", 2: "CIN", 3: "COUT", 4: "HO", 5: "WO", 6: "T"}
FIELD = {0: "kh", 1: "kw", 2: "cin", 3: "run_start", 4: "run_end"}


def main(path, max_tiles=2, max_cores=2, max_bursts=6):
    b = open(path, "rb").read()
    out = []
    assert b[:8] == b"WCTRACE1", b[:8]
    (ver, hdr_bytes, n_tiles, n_cores, wbytes, burst_dim, burst_stride,
     burst_span, n_addr, n_spatial, n_dims, ident_bytes) = struct.unpack_from("<IIiiiiiiiiii", b, 8)
    off = 56
    fields = struct.unpack_from(f"<{n_addr}i", b, off); off += 4 * n_addr
    spatial = {}
    for _ in range(n_spatial):
        d, v = struct.unpack_from("<ii", b, off); off += 8
        spatial[d] = v
    dims = {}
    for _ in range(n_dims):
        d, v = struct.unpack_from("<ii", b, off); off += 8
        dims[d] = v
    ident = b[off:off + ident_bytes].split(b"\0")[:4]; off += ident_bytes
    assert off == hdr_bytes, (off, hdr_bytes)

    out.append(f"file           {path}")
    out.append(f"total bytes    {len(b):,}")
    out.append("")
    out.append("HEADER")
    out.append(f"  magic/version    WCTRACE1 v{ver}   header_bytes={hdr_bytes}")
    out.append(f"  identity         arch={ident[0].decode()} workload={ident[1].decode()} "
               f"layer={ident[2].decode()} sample={ident[3].decode()}")
    out.append(f"  n_tiles          {n_tiles}")
    out.append(f"  n_cores          {n_cores}")
    out.append(f"  weight_bytes     {wbytes}")
    out.append(f"  burst_dim        {burst_dim} ({DIM[burst_dim]})   burst_stride={burst_stride}   "
               f"burst_span={burst_span}")
    out.append(f"  addr fields      {[FIELD[f] for f in fields]}")
    out.append(f"  spatial_factors  {{{', '.join(f'{DIM[d]}:{v}' for d, v in sorted(spatial.items()))}}}"
               f"   product={eval('*'.join(str(v) for v in spatial.values()))}")
    out.append(f"  dims             {{{', '.join(f'{DIM[d]}:{v}' for d, v in sorted(dims.items()))}}}")
    out.append("")

    out.append(f"TILE FRAMES (first {max_tiles} of {n_tiles}; "
               f"first {max_cores} cores each; first {max_bursts} bursts each)")
    grand = 0
    for ti in range(n_tiles):
        tile_index, n_frame_cores, mac_cycles, payload = struct.unpack_from("<iiqQ", b, off)
        off += 24
        show_tile = ti < max_tiles
        if show_tile:
            out.append(f"  tile {tile_index}: cores={n_frame_cores} mac_cycles={mac_cycles} "
                       f"payload_bytes={payload}")
        for ci in range(n_frame_cores):
            core_id, n_bursts = struct.unpack_from("<ii", b, off); off += 8
            grand += n_bursts
            if show_tile and ci < max_cores:
                out.append(f"    core {core_id}: bursts={n_bursts}")
            for bi in range(n_bursts):
                tick, kh, kw, cin, rs, re = struct.unpack_from("<q5i", b, off); off += 28
                if show_tile and ci < max_cores and bi < max_bursts:
                    out.append(f"      tick={tick:<5} kh={kh} kw={kw} cin={cin:<4} "
                               f"cout=[{rs},{re})  span={re - rs}")
            if show_tile and ci < max_cores and n_bursts > max_bursts:
                out.append(f"      ... {n_bursts - max_bursts} more bursts")
        if show_tile and n_frame_cores > max_cores:
            out.append(f"    ... {n_frame_cores - max_cores} more cores")
        if show_tile:
            out.append("")
    end_magic, total_bursts = struct.unpack_from("<iQ", b, off); off += 12
    out.append("TRAILER")
    out.append(f"  end_magic        {end_magic} (expected -1)")
    out.append(f"  total_bursts     {total_bursts:,}")
    out.append(f"  recount walking  {grand:,}   "
               f"{'MATCH' if grand == total_bursts else 'MISMATCH'}")
    out.append(f"  bytes consumed   {off:,} of {len(b):,}   "
               f"{'MATCH' if off == len(b) else 'MISMATCH'}")
    return "\n".join(out)


if __name__ == "__main__":
    print(main(sys.argv[1]))
