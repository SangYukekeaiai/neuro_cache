#!/usr/bin/env python3
"""Is there a hot cin? Counted on the weight trace itself, no simulator.

A burst is emitted when input channel `cin` has a spike, so the per-cin burst
count IS the per-channel spike count the weight stream inherits. If it is flat,
no cin is hot and no cin-indexed pinning or hot-line policy can pay; if it is
skewed, the second question decides everything: is the SAME cin hot across
different input images, or does each image pick its own? Only a cin that is hot
across samples is addressable by a static policy.

Reads the WCTS v1 wire format directly (src/wcache/native/include/wcache/
stream_format.h; the reference Python decode is stage2_weight_trace/
wcts_excerpt.py). Every file's walk is checked against its own trailer.
"""
from __future__ import annotations

import json, pathlib, struct, sys
import numpy as np

STAGE   = pathlib.Path(__file__).resolve().parent
ROOT    = STAGE.parents[1]
STREAMS = ROOT / "profiling/0823_stagewise_verify/stage4_wcache/inputs/streams"
OUT     = STAGE / "outputs"

CIN_BLOCK  = 16         # the line's cin grouping under khkw_split
COUT_BLOCK = 4          # and its cout grouping; 16 x 4 x 1 byte = a 64 B line
L2_LINES   = 8192       # 512 KB / 64 B
L1_LINES   = 256        # 16 KB / 64 B
BURST = np.dtype([("tick", "<i8"), ("kh", "<i4"), ("kw", "<i4"),
                  ("cin", "<i4"), ("rs", "<i4"), ("re", "<i4")])
assert BURST.itemsize == 28


def read_stream(path):
    """-> (header dict, burst record array). Walk is verified against the trailer."""
    b = pathlib.Path(path).read_bytes()
    assert b[:8] == b"WCTRACE1", b[:8]
    (ver, hdr_bytes, n_tiles, n_cores, wbytes, burst_dim, burst_stride,
     burst_span, n_addr, n_spatial, n_dims, ident_bytes) = struct.unpack_from("<IIiiiiiiiiii", b, 8)
    off = 56 + 4 * n_addr + 8 * n_spatial
    dims = {}
    for _ in range(n_dims):
        d, v = struct.unpack_from("<ii", b, off); off += 8
        dims[d] = v
    ident = b[off:off + ident_bytes].split(b"\0")[:4]; off += ident_bytes
    assert off == hdr_bytes, (off, hdr_bytes)

    chunks, cores, tiles = [], [], []
    for _ in range(n_tiles):
        tile_index, n_frame_cores, _, _ = struct.unpack_from("<iiqQ", b, off); off += 24
        for _ in range(n_frame_cores):
            core_id, n_bursts = struct.unpack_from("<ii", b, off); off += 8
            n = n_bursts * BURST.itemsize
            chunks.append(np.frombuffer(b, BURST, count=n_bursts, offset=off)); off += n
            cores.append(np.full(n_bursts, core_id, np.int32))
            tiles.append(np.full(n_bursts, tile_index, np.int32))
    end_magic, total_bursts = struct.unpack_from("<iQ", b, off); off += 12
    assert end_magic == -1 and off == len(b), (end_magic, off, len(b))

    bursts = np.concatenate(chunks)
    assert len(bursts) == total_bursts, (len(bursts), total_bursts)
    hdr = {"layer": ident[2].decode(), "workload": ident[1].decode(),
           "sample": int(ident[3]), "n_tiles": n_tiles, "n_cores": n_cores,
           "CIN": dims[2], "COUT": dims[3], "KH": dims[0], "KW": dims[1],
           "bursts": int(total_bursts)}
    return hdr, bursts, np.concatenate(cores), np.concatenate(tiles)


def gini(x):
    x = np.sort(np.asarray(x, np.float64))
    n = len(x)
    if n == 0 or x.sum() == 0:
        return 0.0
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))


def skew_stats(counts):
    """Concentration of a count vector against the flat reference."""
    c = np.asarray(counts, np.float64)
    n, tot = len(c), c.sum()
    if tot == 0:
        return {}
    s = np.sort(c)[::-1]
    p = c[c > 0] / tot
    top = lambda f: float(s[:max(1, int(round(n * f)))].sum() / tot)
    return {"n": n, "total": int(tot), "mean": tot / n, "max": float(s[0]),
            "min": float(s[-1]), "zero_bins": int((c == 0).sum()),
            "max_over_mean": float(s[0] / (tot / n)),
            "cv": float(c.std() / c.mean()),
            "gini": gini(c),
            "top1pct_share": top(0.01), "top10pct_share": top(0.10),
            "top25pct_share": top(0.25),
            # 1.0 = perfectly flat; how much of a uniform layer's entropy survives
            "entropy_ratio": float(-(p * np.log2(p)).sum() / np.log2(n))}


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)).astype(float), np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    d = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d else 0.0


def analyse(tag, paths):
    per_sample, hdr = [], None
    for p in paths:
        hdr, bursts, _, _ = read_stream(p)
        cin = bursts["cin"].astype(np.int64)
        per_sample.append(np.bincount(cin, minlength=hdr["CIN"])[: hdr["CIN"]])
    counts = np.vstack(per_sample)
    pooled = counts.sum(0)
    blocks = pooled.reshape(-1, CIN_BLOCK).sum(1)

    # Is the same cin hot in every image? Rank agreement between sample pairs.
    pairs = [spearman(counts[i], counts[j])
             for i in range(len(counts)) for j in range(i + 1, len(counts))]
    # And the payoff a static top-k pin would actually capture, per sample,
    # when the top-k is chosen on OTHER samples (leave-one-out, no oracle).
    loo = []
    for i in range(len(counts)):
        others = np.delete(counts, i, 0).sum(0)
        for f in (0.10, 0.25):
            k = max(1, int(round(hdr["CIN"] * f)))
            hot = np.argsort(others)[::-1][:k]
            loo.append((f, float(counts[i][hot].sum() / counts[i].sum())))
    loo_share = {f: float(np.mean([v for g, v in loo if g == f])) for f in (0.10, 0.25)}

    return {"tag": tag, "layer": hdr["layer"], "workload": hdr["workload"],
            "CIN": hdr["CIN"], "COUT": hdr["COUT"], "n_samples": len(paths),
            "bursts_per_sample": [int(c.sum()) for c in counts],
            "per_cin": skew_stats(pooled),
            "per_cin_block16": skew_stats(blocks),
            "cross_sample_spearman": {"min": min(pairs), "mean": float(np.mean(pairs)),
                                      "max": max(pairs)},
            "static_topk_share": loo_share}


def fmt(r):
    c, bl = r["per_cin"], r["per_cin_block16"]
    L = [f"{r['tag']}  {r['workload']}/{r['layer']}  CIN={r['CIN']} COUT={r['COUT']} "
         f"samples={r['n_samples']}  bursts={sum(r['bursts_per_sample']):,}",
         f"  per cin          mean {c['mean']:>12,.0f}   max {c['max']:>12,.0f}   "
         f"min {c['min']:>10,.0f}   max/mean {c['max_over_mean']:5.2f}   dead {c['zero_bins']}",
         f"                   CV {c['cv']:.3f}   Gini {c['gini']:.3f}   "
         f"entropy {c['entropy_ratio']:.4f} of flat",
         f"                   share held by hottest  1% {c['top1pct_share']:6.2%}   "
         f"10% {c['top10pct_share']:6.2%}   25% {c['top25pct_share']:6.2%}",
         f"  per cin block16  CV {bl['cv']:.3f}   Gini {bl['gini']:.3f}   "
         f"max/mean {bl['max_over_mean']:5.2f}   top10% {bl['top10pct_share']:6.2%}",
         f"  same cin hot across images?  spearman min {r['cross_sample_spearman']['min']:.3f} "
         f"mean {r['cross_sample_spearman']['mean']:.3f} max {r['cross_sample_spearman']['max']:.3f}",
         f"  static top-k pin, chosen leave-one-out:  k=10% captures "
         f"{r['static_topk_share'][0.10]:6.2%}   k=25% captures {r['static_topk_share'][0.25]:6.2%}"]
    return "\n".join(L)


def demo():
    """Self-check: the stats separate a flat vector from a hot one, and rank
    correlation separates a stable hot set from a per-sample random one."""
    flat, hot = np.full(512, 100), np.r_[np.full(51, 1000), np.full(461, 10)]
    assert skew_stats(flat)["cv"] == 0 and abs(skew_stats(flat)["entropy_ratio"] - 1) < 1e-12
    assert skew_stats(flat)["top10pct_share"] < 0.11 < skew_stats(hot)["top10pct_share"]
    assert skew_stats(hot)["gini"] > 0.5 > skew_stats(flat)["gini"]
    rng = np.random.default_rng(0)
    base = rng.integers(0, 1000, 512)
    assert spearman(base, base) > 0.999
    assert abs(spearman(rng.permutation(base), rng.permutation(base))) < 0.2
    print("demo ok")


def main(argv):
    if argv[1:2] == ["--demo"]:
        return demo()
    tile_scope, reuse_scope = argv[1:2] == ["--tiles"], argv[1:2] == ["--reuse"]
    times_scope = argv[1:2] == ["--reuse-times"]
    topn_scope  = argv[1:2] == ["--topn"]
    hot_scope   = argv[1:2] == ["--hot"]
    OUT.mkdir(exist_ok=True)
    rows = []
    for tag in ("V8", "V9", "R9", "R16"):
        paths = sorted(STREAMS.glob(f"{tag}_s*.wcts"))
        if not paths:
            print(f"{tag}: no streams under {STREAMS}", file=sys.stderr)
            continue
        if hot_scope:
            r, show = analyse_hot(tag, paths), fmt_hot
        elif topn_scope:
            r, show = analyse_topn(tag, paths), fmt_topn
        elif times_scope:
            r, show = analyse_reuse_times(tag, paths), fmt_reuse_times
        elif reuse_scope:
            r, show = analyse_reuse(tag, paths[0]), fmt_reuse
        elif tile_scope:
            r, show = analyse_tiles(tag, paths), fmt_tiles
        else:
            r, show = analyse(tag, paths), fmt
        rows.append(r)
        print(show(r), flush=True)
        print()
    name = ("hot_cin_hotset.json" if hot_scope else
            "hot_cin_topn.json" if topn_scope else
            "hot_cin_reuse_times.json" if times_scope else
            "hot_cin_reuse.json" if reuse_scope else
            "hot_cin_per_tile.json" if tile_scope else "hot_cin.json")
    (OUT / name).write_text(json.dumps(rows, indent=2, default=str))




# ---------------------------------------------------------------- tile scope

def tile_matrix(hdr, bursts, tiles, width, key):
    """(n_tiles, width) count matrix of `key` per tile."""
    return np.bincount(tiles.astype(np.int64) * width + key,
                       minlength=hdr["n_tiles"] * width).reshape(hdr["n_tiles"], width)


def topk_capture(learn, apply_, k):
    """Share of `apply_`'s refs landing in the top-k bins of `learn`. The
    realizable policy: the hot set is chosen on a window the cache has already
    seen, never on the one it is about to serve."""
    tot = apply_.sum()
    if tot == 0:
        return None
    hot = np.argpartition(learn, -k)[-k:]
    return float(apply_[hot].sum() / tot)


def analyse_tiles(tag, paths):
    present, amongst, refs_tile, reuse_pc = [], [], [], []
    seq_rho, adapt, oracle, adapt_blk = [], {0.10: [], 0.25: []}, {0.10: [], 0.25: []}, {0.10: [], 0.25: []}
    line_repeat, lines_tile, hdr = [], [], None

    for p in paths:
        hdr, bursts, cores, tiles = read_stream(p)
        CIN, NB = hdr["CIN"], hdr["CIN"] // CIN_BLOCK
        cin = bursts["cin"].astype(np.int64)
        M  = tile_matrix(hdr, bursts, tiles, CIN, cin)
        MB = tile_matrix(hdr, bursts, tiles, NB, cin // CIN_BLOCK)

        for row in M:
            tot = row.sum()
            if tot == 0:
                continue
            nz = row[row > 0]
            refs_tile.append(tot)
            present.append(len(nz) / CIN)
            reuse_pc.append(tot / len(nz))
            amongst.append(skew_stats(nz))
        # Does the hot set survive into the next tile?
        for t in range(1, hdr["n_tiles"]):
            if M[t].sum() and M[t - 1].sum():
                seq_rho.append(spearman(M[t - 1], M[t]))
                for f in (0.10, 0.25):
                    k = max(1, int(round(CIN * f)))
                    v = topk_capture(M[t - 1], M[t], k)
                    if v is not None: adapt[f].append(v)
                    v = topk_capture(M[t], M[t], k)
                    if v is not None: oracle[f].append(v)
                    kb = max(1, int(round(NB * f)))
                    v = topk_capture(MB[t - 1], MB[t], kb)
                    if v is not None: adapt_blk[f].append(v)

        # Line-level: how often is the SAME weight line re-read inside one tile?
        # A line is (kh, kw, cin_block, cout_block); one core owns one cout
        # block for the whole tile, so (tile, core, kh, kw, cin_block) names it.
        key = ((((tiles.astype(np.int64) * hdr["n_cores"] + cores) * hdr["KH"]
                 + bursts["kh"]) * hdr["KW"] + bursts["kw"]) * (CIN // CIN_BLOCK)
               + cin // CIN_BLOCK)
        _, counts = np.unique(key, return_counts=True)
        line_repeat.append((float(counts.mean()), float((counts == 1).mean()),
                            float(np.percentile(counts, 99)), int(counts.max())))
        # Distinct LINES a tile touches, cache-wide: (kh, kw, cin_block, cout_block),
        # with no core in the key because the L2 is shared. This is what must fit
        # for any cross-tile retention -- hot or not -- to be possible at all.
        shared = (((bursts["kh"].astype(np.int64) * hdr["KW"] + bursts["kw"])
                   * (CIN // CIN_BLOCK) + cin // CIN_BLOCK) * (hdr["COUT"] // COUT_BLOCK)
                  + bursts["rs"] // COUT_BLOCK)
        lines_tile.extend(len(np.unique(shared[tiles == t])) for t in range(hdr["n_tiles"]))

    mean = lambda xs: float(np.mean(xs)) if len(xs) else float("nan")
    agg = lambda k: mean([a[k] for a in amongst])
    lr = np.array(line_repeat)
    return {"tag": tag, "layer": hdr["layer"], "CIN": hdr["CIN"],
            "n_tiles": hdr["n_tiles"], "n_samples": len(paths),
            "refs_per_tile": mean(refs_tile),
            "cin_present_frac": mean(present),
            "refs_per_present_cin": mean(reuse_pc),
            "among_present": {"max_over_mean": agg("max_over_mean"), "cv": agg("cv"),
                              "gini": agg("gini"), "top10pct_share": agg("top10pct_share"),
                              "entropy_ratio": agg("entropy_ratio")},
            "spearman_t_tplus1": mean(seq_rho),
            "adaptive_capture": {f: mean(v) for f, v in adapt.items()},
            "oracle_capture":   {f: mean(v) for f, v in oracle.items()},
            "adaptive_capture_block16": {f: mean(v) for f, v in adapt_blk.items()},
            "lines_per_tile": mean(lines_tile),
            "line_repeat": {"mean": float(lr[:, 0].mean()), "once_frac": float(lr[:, 1].mean()),
                            "p99": float(lr[:, 2].mean()), "max": int(lr[:, 3].max())}}


def fmt_tiles(r):
    a, lrp = r["among_present"], r["line_repeat"]
    return "\n".join([
        f"{r['tag']}  {r['layer']}  CIN={r['CIN']}  {r['n_tiles']} tiles x {r['n_samples']} samples",
        f"  refs per tile           {r['refs_per_tile']:>10,.0f}",
        f"  cin present in a tile   {r['cin_present_frac']:>10.2%} of the axis   "
        f"refs per present cin {r['refs_per_present_cin']:.1f}",
        f"  skew among those cins   max/mean {a['max_over_mean']:5.2f}   CV {a['cv']:.3f}   "
        f"Gini {a['gini']:.3f}   entropy {a['entropy_ratio']:.4f}   top10% {a['top10pct_share']:6.2%}",
        f"  hot set survives?       spearman(tile t, t+1) = {r['spearman_t_tplus1']:.3f}",
        f"  top-k learned on tile t-1, applied to tile t:",
        f"      k=10%  adaptive {r['adaptive_capture'][0.10]:6.2%}  "
        f"(oracle {r['oracle_capture'][0.10]:6.2%}, flat 10.00%)   "
        f"block16 {r['adaptive_capture_block16'][0.10]:6.2%}",
        f"      k=25%  adaptive {r['adaptive_capture'][0.25]:6.2%}  "
        f"(oracle {r['oracle_capture'][0.25]:6.2%}, flat 25.00%)   "
        f"block16 {r['adaptive_capture_block16'][0.25]:6.2%}",
        f"  distinct lines per tile {r['lines_per_tile']:>10,.0f}   "
        f"= {r['lines_per_tile'] / L2_LINES:5.1f}x the 8,192 lines of a 512 KB L2",
        f"  same LINE re-read in a tile:  mean {lrp['mean']:.3f} touches   "
        f"{lrp['once_frac']:.2%} touched exactly once   p99 {lrp['p99']:.0f}   max {lrp['max']}"])


# ------------------------------------------------------- reuse, trace-only

def reference_order(hdr, bursts, cores, tiles):
    """The order the trace itself implies: tiles in order, ticks in order, and
    the 16 cores of a tick together (verified: every core fires the same
    (kh,kw,cin) at a tick, at 16 different cout blocks). Returns the sort."""
    return np.lexsort((cores, bursts["tick"], tiles))


def line_ids(hdr, bursts, cores=None):
    """One burst is exactly one line: span is always 4 and cout-aligned.
    A line is (kh, kw, cin_block, cout_block) -- what a shared L2 sees."""
    NB, NC = hdr["CIN"] // CIN_BLOCK, hdr["COUT"] // COUT_BLOCK
    return ((((bursts["kh"].astype(np.int64) * hdr["KW"] + bursts["kw"]) * NB
              + bursts["cin"] // CIN_BLOCK) * NC) + bursts["rs"] // COUT_BLOCK)


def reuse_gaps(ids):
    """Exact gap in REFERENCES between consecutive touches of the same line.
    The LRU stack distance is <= this gap (a gap of g spans at most g distinct
    lines), so `gap < C` proves a fully-associative C-line cache holds it. Pure
    counting on the address sequence; no cache is modelled."""
    order = np.argsort(ids, kind="stable")
    s = ids[order]
    same = np.r_[False, s[1:] == s[:-1]]
    return order[same] - order[np.r_[same[1:], False]], int((~same).sum())


def window_union(hdr, ids, tiles, widths):
    """Distinct lines touched by W consecutive tiles. Exact, and an upper bound
    on the stack distance of any reuse that spans W tiles."""
    out = {}
    for w in widths:
        if w > hdr["n_tiles"]:
            continue
        sizes = [len(np.unique(ids[(tiles >= a) & (tiles < a + w)]))
                 for a in range(0, hdr["n_tiles"] - w + 1, max(1, w))]
        out[w] = float(np.mean(sizes))
    return out


def analyse_reuse(tag, path):
    hdr, bursts, cores, tiles = read_stream(path)
    o = reference_order(hdr, bursts, cores, tiles)
    bursts, cores, tiles = bursts[o], cores[o], tiles[o]
    ids = line_ids(hdr, bursts)

    shared_gap, shared_cold = reuse_gaps(ids)
    # Per-core view: what one core's private L1 sees, in that core's own order.
    per_core, cold_core, n_core = [], 0, 0
    for c in range(hdr["n_cores"]):
        m = cores == c
        n_core += int(m.sum())
        g, cold = reuse_gaps(ids[m])
        per_core.append(g); cold_core += cold
    core_gap = np.concatenate(per_core)

    def buckets(gaps, cold, total, caps):
        r = {"references": total, "compulsory": cold / total,
             "reused": len(gaps) / total}
        r["gap_eq_1"] = float((gaps == 1).sum() / total)
        for c in caps:
            r[f"gap_lt_{c}"] = float((gaps < c).sum() / total)
        r["gap_p50"] = float(np.median(gaps)) if len(gaps) else float("nan")
        r["gap_p90"] = float(np.percentile(gaps, 90)) if len(gaps) else float("nan")
        return r

    return {"tag": tag, "layer": hdr["layer"], "sample": hdr["sample"],
            "n_cores": hdr["n_cores"], "total_lines": int(len(np.unique(ids))),
            "shared": buckets(shared_gap, shared_cold, len(ids), (1, 16, 256, L2_LINES)),
            "per_core": buckets(core_gap, cold_core, n_core, (1, 16, 256, L1_LINES)),
            "window_union_lines": window_union(hdr, ids, tiles, (1, 2, 4, 8, 16, 32))}


def fmt_reuse(r):
    s, c = r["shared"], r["per_core"]
    wu = "   ".join(f"{w}t {v:,.0f}" for w, v in r["window_union_lines"].items())
    return "\n".join([
        f"{r['tag']}  {r['layer']}  sample {r['sample']}   "
        f"{s['references']:,} references over {r['total_lines']:,} distinct lines",
        f"  shared (one L2 sees every core)",
        f"      compulsory {s['compulsory']:6.2%}   reused {s['reused']:6.2%}   "
        f"gap p50 {s['gap_p50']:,.0f}  p90 {s['gap_p90']:,.0f}",
        f"      reuse gap < 16 lines {s['gap_lt_16']:6.2%}   < 256 {s['gap_lt_256']:6.2%}   "
        f"< 8,192 {s[f'gap_lt_{L2_LINES}']:6.2%}",
        f"  per core (its own private L1, its own reference order)",
        f"      compulsory {c['compulsory']:6.2%}   reused {c['reused']:6.2%}   "
        f"gap p50 {c['gap_p50']:,.0f}  p90 {c['gap_p90']:,.0f}",
        f"      immediate repeat (gap 1) {c['gap_eq_1']:6.2%}"
        f"   gap < 16 {c['gap_lt_16']:6.2%}   < 256 {c[f'gap_lt_{L1_LINES}']:6.2%}",
        f"  distinct lines in a window of consecutive tiles:  {wu}"])



# ------------------------------------- reuse TIMES of one cin inside one tile

def analyse_reuse_times(tag, paths):
    """Inside ONE tile, how many times is ONE cin referenced, and how do those
    references distribute over cache lines under the current khkw_split layout?

    A cin's touches inside a tile are indexed by (core, kh, kw): the core picks
    the cout block, (kh, kw) the kernel position. `(tile, core, kh, kw, cin)`
    never repeats (measured), so refs = distinct (core, kh, kw) pairs exactly.

    khkw_split puts kh, kw and the cout block in the address, so each of those
    touches is a DIFFERENT line. The count is therefore also the number of
    lines one cin's traffic spreads over, and the reuse a line gets from that
    cin alone is exactly 1.0 whatever the reuse times."""
    per_tile_cin, khkw, cores_n, hdr = [], [], [], None
    for p in paths:
        hdr, bursts, cores, tiles = read_stream(p)
        CIN, NB, NC = hdr["CIN"], hdr["CIN"] // CIN_BLOCK, hdr["COUT"] // COUT_BLOCK
        cin = bursts["cin"].astype(np.int64)
        g = tiles.astype(np.int64) * CIN + cin          # the (tile, cin) group
        n_groups = hdr["n_tiles"] * CIN

        refs = np.bincount(g, minlength=n_groups)
        # distinct (kh, kw) and distinct cores that touch this cin in this tile
        kk = bursts["kh"].astype(np.int64) * hdr["KW"] + bursts["kw"]
        d_kk = np.bincount(np.unique(g * (hdr["KH"] * hdr["KW"]) + kk)
                           // (hdr["KH"] * hdr["KW"]), minlength=n_groups)
        d_co = np.bincount(np.unique(g * hdr["n_cores"] + cores) // hdr["n_cores"],
                           minlength=n_groups)
        live = refs > 0
        per_tile_cin.append(refs[live]); khkw.append(d_kk[live]); cores_n.append(d_co[live])

    refs = np.concatenate(per_tile_cin)
    d_kk = np.concatenate(khkw)
    d_co = np.concatenate(cores_n)
    assert (refs >= d_kk).all() and (refs >= d_co).all()
    # refs == distinct (core, kh, kw); the layout scatters every one onto its
    # own line, so lines-per-cin == refs and per-cin line reuse == 1.0.
    hist = np.bincount(np.minimum(refs, 200))
    q = lambda v: {"mean": float(v.mean()), "p50": float(np.median(v)),
                   "p90": float(np.percentile(v, 90)), "max": int(v.max()),
                   "min": int(v.min())}
    return {"tag": tag, "layer": hdr["layer"], "CIN": hdr["CIN"],
            "n_cores": hdr["n_cores"], "KHKW": hdr["KH"] * hdr["KW"],
            "live_tile_cin_pairs": int(len(refs)),
            "reuse_times": q(refs), "distinct_khkw": q(d_kk), "distinct_cores": q(d_co),
            "frac_reused_once_or_more": float((refs > 1).mean()),
            "hist_head": {int(i): int(n) for i, n in enumerate(hist[:17]) if n},
            # what the touches would collapse onto if the line changed shape
            "lines_khkw_split": float(refs.mean()),
            "lines_if_khkw_in_offset": float(d_co.mean()),
            "reuse_if_khkw_in_offset": float((refs / np.maximum(d_co, 1)).mean())}


def fmt_reuse_times(r):
    rt, kk, co = r["reuse_times"], r["distinct_khkw"], r["distinct_cores"]
    return "\n".join([
        f"{r['tag']}  {r['layer']}  CIN={r['CIN']}  {r['n_cores']} cores x "
        f"{r['KHKW']} (kh,kw)  ->  {r['n_cores'] * r['KHKW']} touches possible per cin per tile",
        f"  reuse times of one cin in one tile   mean {rt['mean']:6.1f}   p50 {rt['p50']:5.0f}   "
        f"p90 {rt['p90']:5.0f}   max {rt['max']:4d}   min {rt['min']}",
        f"      touched more than once           {r['frac_reused_once_or_more']:6.2%} of "
        f"{r['live_tile_cin_pairs']:,} live (tile, cin) pairs",
        f"      decomposes as   distinct cout blocks {co['mean']:5.1f}  x  "
        f"distinct (kh,kw) {kk['mean']:4.1f}",
        f"  where those touches land under khkw_split:",
        f"      lines the cin spreads over        {r['lines_khkw_split']:6.1f}   "
        f"=> line reuse from this cin  1.00",
        f"      if (kh,kw) moved into the offset  {r['lines_if_khkw_in_offset']:6.1f}   "
        f"=> line reuse from this cin  {r['reuse_if_khkw_in_offset']:.2f}"])



# ------------------------------------------------- top-N channels inside a tile

TOPN = (1, 2, 5, 10, 16, 32, 64)


def analyse_topn(tag, paths):
    """Direct question: inside ONE tile, how many bursts do the top N cins hold?
    Measured on every (tile, sample) pair; N is a count of channels, not a
    fraction of the axis."""
    tot, cum, live, hdr = [], [], [], None
    peak, tied = [], []          # the per-tile max count, and how many cins reach it
    for p in paths:
        hdr, bursts, _, tiles = read_stream(p)
        M = tile_matrix(hdr, bursts, tiles, hdr["CIN"], bursts["cin"].astype(np.int64))
        for row in M:
            t = row.sum()
            if t == 0:
                continue
            s = np.sort(row)[::-1]
            c = np.cumsum(s)
            tot.append(t)
            live.append(int((row > 0).sum()))
            peak.append(int(s[0]))
            tied.append(int((row == s[0]).sum()))
            cum.append([c[min(n, len(s)) - 1] for n in TOPN])
    tot, cum, live = np.array(tot, np.float64), np.array(cum, np.float64), np.array(live)
    share = cum / tot[:, None]
    q = lambda a, p: float(np.percentile(a, p))
    return {"tag": tag, "layer": hdr["layer"], "CIN": hdr["CIN"],
            "n_tiles": hdr["n_tiles"], "n_samples": len(paths),
            "tiles_measured": len(tot),
            "bursts_per_tile": {"mean": float(tot.mean()), "p50": q(tot, 50),
                                "min": float(tot.min()), "max": float(tot.max())},
            "live_cins_per_tile": {"mean": float(live.mean()), "min": int(live.min()),
                                   "max": int(live.max())},
            # Is there a peak, or a plateau? `tied` counts the cins sharing the max.
            "peak_count": {"mean": float(np.mean(peak)), "min": int(min(peak)),
                           "max": int(max(peak))},
            "cins_tied_at_peak": {"mean": float(np.mean(tied)), "min": int(min(tied)),
                                  "max": int(max(tied))},
            "top10_all_tied_frac": float(np.mean([t >= 10 for t in tied])),
            "topn": {n: {"bursts_mean": float(cum[:, i].mean()),
                         "share_mean": float(share[:, i].mean()),
                         "share_p10": q(share[:, i], 10), "share_p50": q(share[:, i], 50),
                         "share_p90": q(share[:, i], 90),
                         "share_min": float(share[:, i].min()),
                         "share_max": float(share[:, i].max()),
                         "flat": n / hdr["CIN"]}
                     for i, n in enumerate(TOPN)}}


def fmt_topn(r):
    L = [f"{r['tag']}  {r['layer']}  CIN={r['CIN']}   {r['tiles_measured']} tiles "
         f"({r['n_tiles']} x {r['n_samples']} samples)",
         f"  bursts in a tile   mean {r['bursts_per_tile']['mean']:>10,.0f}   "
         f"p50 {r['bursts_per_tile']['p50']:>10,.0f}   "
         f"range {r['bursts_per_tile']['min']:,.0f} - {r['bursts_per_tile']['max']:,.0f}",
         f"  live cins in a tile  mean {r['live_cins_per_tile']['mean']:.1f} of {r['CIN']}",
         f"  peak cin count     mean {r['peak_count']['mean']:.1f} bursts   "
         f"range {r['peak_count']['min']}-{r['peak_count']['max']}   "
         f"cins TIED at it {r['cins_tied_at_peak']['mean']:.1f} "
         f"({r['cins_tied_at_peak']['min']}-{r['cins_tied_at_peak']['max']})   "
         f"top-10 all tied in {r['top10_all_tied_frac']:.1%} of tiles",
         "  top N cins of a tile hold:",
         "      N   bursts     share    p10     p50     p90     flat   x flat"]
    for n in TOPN:
        t = r["topn"][n]
        L.append(f"    {n:>3}  {t['bursts_mean']:>8,.0f}  {t['share_mean']:6.2%}  "
                 f"{t['share_p10']:6.2%}  {t['share_p50']:6.2%}  {t['share_p90']:6.2%}  "
                 f"{t['flat']:6.2%}  {t['share_mean'] / t['flat']:5.2f}x")
    return "\n".join(L)


# ------------------------------------------ the hot set, and what makes a cin hot

HOTN = (8, 16, 32, 64)


def analyse_hot(tag, paths):
    """Two questions, one pass.

    1. Is there a hot set that survives an unseen image? The top N cins are
       ranked on the OTHER four samples and scored on the held-out fifth, all
       five folds averaged. Flat is N / CIN, so `x_flat` is the only number
       that matters.
    2. What makes a cin hot? A cin's bursts in a tile are exactly
       16 cores x (distinct kernel positions it fires at), so hotness IS that
       position count. The histogram is over cins, of the per-cin mean position
       count averaged over ALL tiles -- a tile where the cin never fires
       counts 0, which is what makes the axis 0..9.
    """
    per_sample, pos_tot, n_tiles, hdr = [], None, 0, None
    for p in paths:
        hdr, bursts, _, tiles = read_stream(p)
        CIN, KH, KW = hdr["CIN"], hdr["KH"], hdr["KW"]
        per_sample.append(np.bincount(bursts["cin"].astype(np.int64),
                                      minlength=CIN)[:CIN])
        key = ((tiles.astype(np.int64) * CIN + bursts["cin"]) * (KH * KW)
               + bursts["kh"].astype(np.int64) * KW + bursts["kw"])
        u = np.unique(key)
        pc = np.bincount((u // (KH * KW)) % CIN, minlength=CIN)
        pos_tot = pc if pos_tot is None else pos_tot + pc
        n_tiles += hdr["n_tiles"]

    C = np.vstack(per_sample).astype(np.float64)
    CIN = hdr["CIN"]
    cap = {}
    for n in HOTN:
        folds = []
        for i in range(len(C)):
            others = np.delete(C, i, 0).sum(0)
            hot = np.argsort(others)[::-1][:n]
            folds.append(float(C[i][hot].sum() / C[i].sum()))
        flat = n / CIN
        cap[n] = {"share": float(np.mean(folds)), "share_min": min(folds),
                  "share_max": max(folds), "flat": flat,
                  "x_flat": float(np.mean(folds)) / flat}

    mean_pos = pos_tot / n_tiles
    hist = np.bincount(np.rint(mean_pos).astype(int), minlength=KH * KW + 1)
    return {"tag": tag, "layer": hdr["layer"], "CIN": CIN, "n_samples": len(paths),
            "loo_capture": cap,
            "mean_positions_per_cin": float(mean_pos.mean()),
            "position_hist": [int(v) for v in hist[: KH * KW + 1]],
            # the tail is what separates a hot layer from a warm one
            "tail_cins_ge7": int(hist[7:].sum())}


def fmt_hot(r):
    L = [f"{r['tag']}  {r['layer']}  CIN={r['CIN']}  {r['n_samples']} samples",
         "  hot set ranked on 4 images, scored on the 5th it never saw:",
         "      N    share    flat   x flat   (worst fold)"]
    for n in HOTN:
        c = r["loo_capture"][n]
        L.append(f"    {n:>3}  {c['share']:7.2%} {c['flat']:7.2%}  {c['x_flat']:5.2f}x"
                 f"   {c['share_min']:7.2%}")
    L += [f"  what makes a cin hot: kernel positions it fires at "
          f"(mean {r['mean_positions_per_cin']:.2f} of {len(r['position_hist']) - 1})",
          "      positions  " + " ".join(f"{i:>5}" for i in range(len(r["position_hist"]))),
          "      cins       " + " ".join(f"{v:>5}" for v in r["position_hist"]),
          f"      tail (>=7 positions): {r['tail_cins_ge7']} cins"]
    return "\n".join(L)


if __name__ == "__main__":
    main(sys.argv)
