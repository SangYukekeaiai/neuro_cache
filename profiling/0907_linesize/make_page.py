#!/usr/bin/env python3
"""Build the line-size review page from this stage's own CSVs.

CSS is imported from the 0907_index_policy generator rather than copied, so the
four pages of this campaign stay one visual family.

Usage: conda run -n base python make_page.py   ->  outputs/page_linesize.html
"""
from __future__ import annotations

import collections, csv, html, pathlib, statistics, sys

STAGE  = pathlib.Path(__file__).resolve().parent
OUT    = STAGE / "outputs"
NOCSIM = STAGE.parents[1] / "profiling/0831_all_layer_streams/outputs/all_layers_vs_nocsim.csv"
sys.path.insert(0, str(STAGE.parent / "0907_index_policy"))
from make_pages import CSS, fmt  # noqa: E402

LINES = ["64B", "32B", "16B"]
SIZES = ["16k", "8k"]
CINB  = {"64B": 16, "32B": 8, "16B": 4}
WAYS  = {"64B": 32, "32B": 64, "16B": 128}
TINT  = {"64B": "lru", "32B": "rrip", "16B": "lfu"}


def load():
    rows = list(csv.DictReader(open(OUT / "line_rows.csv")))
    by_layer = {(r["tag"], r["arm"]): r
                for r in csv.DictReader(open(OUT / "line_by_layer.csv"))}
    noc = {r["tag"]: float(r["nocsim_total_cycles"])
           for r in csv.DictReader(open(NOCSIM))}
    tags = sorted({t for t, _ in by_layer}, key=lambda t: (t[0], int(t[1:])))

    per = collections.defaultdict(list)
    for r in rows:
        per[(r["_arm"], r["_tag"])].append(r)
    acc = collections.defaultdict(collections.Counter)
    for (arm, tag), rs in per.items():
        wl = "vgg16" if tag[0] == "V" else "resnet19"
        for sc in (wl, "all"):
            a = acc[(arm, sc)]
            a["cyc"] += statistics.mean(float(r["total_cycles"]) for r in rs)
            for c in ("l1_hits", "l1_accesses", "l2_hits", "l2_accesses",
                      "dram_accesses", "dram_bytes", "stall_total", "stall_channel"):
                a[c] += statistics.mean(float(r[c]) for r in rs)
            a["noc"] += noc[tag]
    return by_layer, acc, tags


def dots(by_layer, tags, lo, hi, ticks):
    """32 B and 16 B against 64 B at the same L1 size. 64 B is the 1.00x line."""
    series = [(ln, sz) for sz in SIZES for ln in ("32B", "16B")]
    x = lambda v: max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))
    out = [f'<div class="gridline" style="left:calc(40px + 10px + (100% - 112px) * '
           f'{x(t) / 100:.5f})"></div>' for t in ticks]
    for t in tags:
        vals = {}
        for ln, sz in series:
            ref = float(by_layer[(t, f"64B_{sz}")]["cycles"])
            vals[(ln, sz)] = ref / float(by_layer[(t, f"{ln}_{sz}")]["cycles"])
        xs = [x(v) for v in vals.values()]
        tip = " / ".join(f"{ln} at {sz} {v:.4f}x" for (ln, sz), v in vals.items())
        marks = "".join(
            f'<span class="dot {TINT[ln]}{"" if sz == "16k" else " hollow"}" '
            f'style="left:{x(vals[(ln, sz)]):.3f}%"></span>' for ln, sz in series)
        out.append(
            f'<div class="row" title="{html.escape(by_layer[(t, "64B_16k")]["layer"])}'
            f' &#10;{tip}"><div class="lab">{t}</div><div class="track">'
            f'<span class="conn" style="left:{min(xs):.3f}%;width:{max(xs) - min(xs):.3f}%"></span>'
            f'{marks}</div><div class="val">{min(vals.values()):.3f}x</div></div>')
    out.append('<div class="axis"><div></div><div class="ticks">'
               + "".join(f'<span style="left:{x(t):.3f}%">{t:.2f}x</span>' for t in ticks)
               + '</div><div></div></div>')
    return "".join(out)


def build(by_layer, acc, tags):
    A = lambda ln, sz, sc="all": acc[(f"{ln}_{sz}", sc)]

    tiles = ""
    for ln in LINES:
        v16, v8 = A(ln, "16k"), A(ln, "8k")
        r16 = A("64B", "16k")["cyc"] / v16["cyc"]
        r8 = A("64B", "8k")["cyc"] / v8["cyc"]
        tiles += f"""
      <div class="tile" style="--tint:var(--{TINT[ln]})">
        <div class="name"><b>{ln} line</b><span>cin_block {CINB[ln]}, {WAYS[ln]} ways</span></div>
        <div class="big">{r16:.3f}x</div>
        <div class="cap">at 16 KB, against the 64 B line. {r8:.3f}x at 8 KB.</div>
        <dl>
          <dt>16 KB cycles</dt><dd>{fmt(v16['cyc'])}</dd>
          <dt>8 KB cycles</dt><dd>{fmt(v8['cyc'])}</dd>
          <dt>L1 misses, 16 KB</dt><dd>{fmt(v16['l1_accesses'] - v16['l1_hits'])}</dd>
          <dt>DRAM transactions</dt><dd>{fmt(v16['dram_accesses'])}</dd>
          <dt>DRAM bytes</dt><dd>{v16['dram_bytes'] / 1e6:,.1f} MB</dd>
        </dl>
      </div>"""

    mech = ""
    for sz in SIZES:
        for ln in LINES:
            v = A(ln, sz)
            ref = A("64B", sz)
            mech += (f'<tr><td>{16 if sz == "16k" else 8} KB</td><td>{ln}</td>'
                     f'<td>{by_layer[(tags[0], f"{ln}_{sz}")]["l1_num_lines"]}</td>'
                     f'<td>{by_layer[(tags[0], f"{ln}_{sz}")]["l1_num_sets"]}</td>'
                     f'<td>{fmt(v["l1_accesses"])}</td>'
                     f'<td>{v["l1_hits"] / v["l1_accesses"]:.4f}</td>'
                     f'<td>{fmt(v["l1_accesses"] - v["l1_hits"])}</td>'
                     f'<td>{fmt(v["dram_accesses"])}</td>'
                     f'<td>{v["dram_bytes"] / 1e6:,.1f} MB</td>'
                     f'<td>{fmt(v["stall_channel"])}</td>'
                     f'<td>{ref["cyc"] / v["cyc"]:.4f}x</td></tr>')

    trows = ""
    for sz in SIZES:
        for ln in LINES:
            v, ref = A(ln, sz), A("64B", sz)
            trows += (f'<tr><td>{16 if sz == "16k" else 8} KB</td><td>{ln}</td>'
                      f'<td>{fmt(A(ln, sz, "vgg16")["cyc"])}</td>'
                      f'<td>{fmt(A(ln, sz, "resnet19")["cyc"])}</td>'
                      f'<td>{fmt(v["cyc"])}</td>'
                      f'<td>{ref["cyc"] / v["cyc"]:.4f}x</td>'
                      f'<td>{v["noc"] / v["cyc"]:.3f}x</td></tr>')

    allv = [float(by_layer[(t, f"64B_{sz}")]["cycles"]) /
            float(by_layer[(t, f"{ln}_{sz}")]["cycles"])
            for t in tags for sz in SIZES for ln in ("32B", "16B")]
    lo = (int(min(allv) * 10) - 1) / 10.0
    hi = (int(max(allv) * 10) + 2) / 10.0
    ticks = [round(lo + i * 0.1, 1) for i in range(int(round((hi - lo) / 0.1)) + 1)]

    m64, m32, m16 = (A(l, "16k") for l in LINES)
    return f"""<title>Line Size at the L1</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@700;800&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{CSS}
.dot.rrip{{background:var(--rrip)}}
.dot.hollow{{background:var(--surface)!important}}
.dot.lru.hollow{{box-shadow:0 0 0 2px var(--surface), inset 0 0 0 2.5px var(--lru)}}
.dot.rrip.hollow{{box-shadow:0 0 0 2px var(--surface), inset 0 0 0 2.5px var(--rrip)}}
.dot.lfu.hollow{{box-shadow:0 0 0 2px var(--surface), inset 0 0 0 2.5px var(--lfu)}}
.row{{grid-template-columns:40px 1fr 66px}}
.axis{{grid-template-columns:40px 1fr 66px}}
.zero{{position:absolute; top:0; bottom:20px; width:1.5px; background:var(--ink-2); opacity:.45}}
</style>
<div class="wrap">
  <header>
    <div class="eyebrow">wcache 0907 &middot; line size at a fixed set count &middot; RRIP, 5-bit RRPV</div>
    <h1>The line is the unit of cost</h1>
    <p class="lede">
      64 B, 32 B and 16 B lines, set by <span class="mono">cin_block</span> 16, 8
      and 4 against a fixed <span class="mono">cout_block</span> of 4. The ways
      scale with the line (32, 64, 128) so <b>every arm has the same set
      count</b>, which leaves the line size as the only thing that varies.
      Policy is RRIP with a 5-bit RRPV. <b>64 B wins everywhere</b>, and each
      halving of the line costs more than the last: 16 B runs at
      <b>{A('64B', '16k')['cyc'] / m16['cyc']:.3f}x</b> at 16 KB and
      <b>{A('64B', '8k')['cyc'] / A('16B', '8k')['cyc']:.3f}x</b> at 8 KB.
    </p>
    <dl class="spec">
      <div><dt>Lines</dt><dd>64 B &middot; 32 B &middot; 16 B</dd></div>
      <div><dt>cin_block</dt><dd>16 &middot; 8 &middot; 4</dd></div>
      <div><dt>Ways</dt><dd>32 &middot; 64 &middot; 128</dd></div>
      <div><dt>Sets</dt><dd>8 at 16 KB, 4 at 8 KB</dd></div>
      <div><dt>Policy</dt><dd>RRIP, 5-bit RRPV</dd></div>
      <div><dt>Layout</dt><dd>khkw_split</dd></div>
    </dl>
  </header>

  <div class="tiles">{tiles}
  </div>

  <section>
    <div class="head"><h2>The same bytes, twice the transactions</h2>
    <p>The L1 sees exactly {fmt(m64['l1_accesses'])} accesses in every arm: the
    trace drives that number, not the geometry. What changes is how many of them
    miss, and each halving of the line <b>doubles the misses</b>:
    {fmt(m64['l1_accesses'] - m64['l1_hits'])} at 64 B,
    {fmt(m32['l1_accesses'] - m32['l1_hits'])} at 32 B,
    {fmt(m16['l1_accesses'] - m16['l1_hits'])} at 16 B.</p>
    <p>The DRAM traffic is the tell. All three arms move essentially the same
    volume ({m64['dram_bytes'] / 1e6:,.1f}, {m32['dram_bytes'] / 1e6:,.1f} and
    {m16['dram_bytes'] / 1e6:,.1f} MB), but the transaction count doubles with
    every halving. The model charges per transaction rather than per byte, and
    <span class="mono">stall_channel</span> follows exactly:
    {fmt(m64['stall_channel'])} to {fmt(m32['stall_channel'])} to
    {fmt(m16['stall_channel'])}.</p>
    <p>A core sweeps <span class="mono">cin</span> sequentially, so a line that
    packs 16 consecutive <span class="mono">cin</span> values serves 16 accesses
    from one fetch and a line that packs 4 serves 4. That spatial reuse is the
    whole of the effect, and it is why the trend points at lines larger than 64 B
    rather than smaller.</p></div>
    <div class="scroll"><table>
      <thead><tr><th>L1</th><th>Line</th><th>Lines</th><th>Sets</th><th>L1 accesses</th>
      <th>L1 hit</th><th>L1 misses</th><th>DRAM txns</th><th>DRAM bytes</th>
      <th>Channel stall</th><th>vs 64 B</th></tr></thead>
      <tbody>{mech}</tbody>
    </table></div>
  </section>

  <section>
    <div class="head">
      <h2>Per layer</h2>
      <p>Cycles against the 64 B line at the same L1 size, so 64 B is the line at
      1.00x and everything sits left of it. Colour is the line size, solid marks
      are 16 KB and hollow are 8 KB. The right column is the worst arm.</p>
    </div>
    <div class="panel">
      <div class="legend">
        <span><i style="background:var(--rrip)"></i>32 B at 16 KB</span>
        <span><i style="background:var(--surface); box-shadow:inset 0 0 0 2.5px var(--rrip)"></i>32 B at 8 KB</span>
        <span><i style="background:var(--lfu)"></i>16 B at 16 KB</span>
        <span><i style="background:var(--surface); box-shadow:inset 0 0 0 2.5px var(--lfu)"></i>16 B at 8 KB</span>
      </div>
      <div class="chart">
        <div class="zero" style="left:calc(40px + 10px + (100% - 112px) * {(1.0 - lo) / (hi - lo):.5f})"></div>
        {dots(by_layer, tags, lo, hi, ticks)}
      </div>
    </div>
  </section>

  <section>
    <div class="head"><h2>Accumulated cycles, per workload</h2>
    <p>Layer totals summed over the 12 vgg16 and 19 resnet19 layers, each layer
    contributing the mean of its five samples.</p></div>
    <div class="scroll"><table>
      <thead><tr><th>L1</th><th>Line</th><th>vgg16</th><th>resnet19</th><th>Total</th>
      <th>vs 64 B</th><th>vs nocsim</th></tr></thead>
      <tbody>{trows}</tbody>
    </table></div>
  </section>

  <footer>
    <div>155 streams (31 layers x 5 samples) x 6 configs, 930 rows, 0 failures,
    99.2s. Three passes per stream, one per line size: <code>cin_block</code> is a
    mapper parameter and one mapper serves a whole broadcast sweep, so
    <code>wcache_sweep</code> refuses a grid whose points disagree about it.</div>
    <div>Control check: <code>64B_16k</code> and <code>64B_8k</code> reproduce the
    RRIP 32-way rows of the 0907 associativity stage exactly.</div>
    <div>On the RRPV width: widening it from 2 bits to 5 changes nothing here.
    Every layer returns identical cycles at every width from 1 to 8 bits. The
    knob is not inert, it is verified to change victim choices on a synthetic
    hot-set-plus-scan pattern; this workload simply never uses the extra
    resolution, because a set is almost always in the three-valued state SRRIP
    collapses to (0 just hit, max - 1 just filled, max eligible).</div>
  </footer>
</div>
"""


def main():
    by_layer, acc, tags = load()
    p = OUT / "page_linesize.html"
    p.write_text(build(by_layer, acc, tags))
    print(p)


if __name__ == "__main__":
    main()
