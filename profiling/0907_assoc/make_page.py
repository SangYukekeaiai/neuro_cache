#!/usr/bin/env python3
"""Build the associativity review page from this stage's own CSVs.

The CSS comes from the 0907_index_policy generator rather than a copy, because
the pages are read as one family and a divergence in the palette or the chart
metrics would read as a difference in the data. That import is the only coupling
between the two stages.

Usage: conda run -n ${CONDA_ENV:-cosa_snn} python make_page.py   ->  outputs/page_assoc.html
"""
from __future__ import annotations

import collections, csv, html, pathlib, statistics, sys

STAGE  = pathlib.Path(__file__).resolve().parent
OUT    = STAGE / "outputs"
NOCSIM = STAGE.parents[1] / "profiling/0831_all_layer_streams/outputs/all_layers_vs_nocsim.csv"
sys.path.insert(0, str(STAGE.parent / "0907_index_policy"))
from make_pages import CSS, fmt  # noqa: E402

LEVELS = ["16w", "32w", "fa"]
LEVEL_NAME = {"16w": "16-way", "32w": "32-way", "fa": "Fully associative"}
ARMS = [f"{p}_{w}" for w in LEVELS for p in ("lru", "rrip")]
LABEL = {a: f"{a.split('_')[0].upper()} {LEVEL_NAME[a.split('_')[1]]}" for a in ARMS}
# Colour carries the ASSOCIATIVITY, which is what this page compares, and fill
# carries the policy: hollow LRU, solid RRIP. Three hues plus two fills beats six
# hues, and the three are the palette already validated for this page family.
TINT = {a: {"16w": "lru", "32w": "rrip", "fa": "lfu"}[a.split("_")[1]] for a in ARMS}
SOLID = {a: a.startswith("rrip") for a in ARMS}


def load():
    rows = list(csv.DictReader(open(OUT / "assoc_rows.csv")))
    by_layer = {(r["tag"], r["arm"]): r
                for r in csv.DictReader(open(OUT / "assoc_by_layer.csv"))}
    noc = {r["tag"]: float(r["nocsim_total_cycles"])
           for r in csv.DictReader(open(NOCSIM))}
    tags = sorted({tag for tag, _ in by_layer}, key=lambda t: (t[0], int(t[1:])))

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
                      "dram_bytes", "stall_total"):
                a[c] += statistics.mean(float(r[c]) for r in rs)
            a["noc"] += noc[tag]
            a["layers"] += 1
    return by_layer, acc, tags


def block(by_layer, acc, tags, kb):
    sz = f"{kb}k"
    arms = {a: acc[(f"{a}_{sz}", "all")] for a in ARMS}
    return {"kb": kb, "sz": sz, "arms": arms, "ref": arms["lru_16w"]["cyc"],
            "sets": {a: by_layer[(tags[0], f"{a}_{sz}")]["l1_num_sets"] for a in ARMS},
            "ways": {a: by_layer[(tags[0], f"{a}_{sz}")]["l1_assoc"] for a in ARMS},
            "wl": {a: {w: acc[(f"{a}_{sz}", w)] for w in ("vgg16", "resnet19")}
                   for a in ARMS}}


def dots(by_layer, tags, sz, lo, hi, ticks):
    x = lambda v: max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))
    out = [f'<div class="gridline" style="left:calc(40px + 10px + (100% - 112px) * '
           f'{x(t) / 100:.5f})"></div>' for t in ticks]
    for t in tags:
        ref = float(by_layer[(t, f"lru_16w_{sz}")]["cycles"])
        vals = {a: ref / float(by_layer[(t, f"{a}_{sz}")]["cycles"]) for a in ARMS}
        xs = [x(v) for v in vals.values()]
        tip = " / ".join(f"{LABEL[a]} {vals[a]:.4f}x" for a in ARMS)
        marks = "".join(
            f'<span class="dot {TINT[a]}{"" if SOLID[a] else " hollow"}" '
            f'style="left:{x(vals[a]):.3f}%"></span>' for a in ARMS)
        worst = min(vals.values())
        out.append(
            f'<div class="row" title="{html.escape(by_layer[(t, f"lru_16w_{sz}")]["layer"])}'
            f' &#10;{tip}">'
            f'<div class="lab">{t}</div><div class="track">'
            f'<span class="conn" style="left:{min(xs):.3f}%;width:{max(xs) - min(xs):.3f}%"></span>'
            f'{marks}</div>'
            f'<div class="val{"" if worst < 0.9995 else " tied"}">{worst:.4f}x</div></div>')
    out.append('<div class="axis"><div></div><div class="ticks">'
               + "".join(f'<span style="left:{x(t):.3f}%">{t:.2f}x</span>' for t in ticks)
               + '</div><div></div></div>')
    return "".join(out)


def build(by_layer, acc, tags):
    b16, b8 = block(by_layer, acc, tags, 16), block(by_layer, acc, tags, 8)

    tiles = ""
    for w in LEVELS:
        lru, rrip = b8["arms"][f"lru_{w}"], b8["arms"][f"rrip_{w}"]
        tiles += f"""
      <div class="tile" style="--tint:var(--{TINT[f'lru_{w}']})">
        <div class="name"><b>{LEVEL_NAME[w]}</b><span>{b8['ways'][f'lru_{w}']} ways, {b8['sets'][f'lru_{w}']} sets</span></div>
        <div class="big">{b8['ref'] / rrip['cyc']:.4f}x</div>
        <div class="cap">RRIP, accumulated cycles against 16-way LRU at 8 KB</div>
        <dl>
          <dt>LRU cycles</dt><dd>{fmt(lru['cyc'])}</dd>
          <dt>RRIP cycles</dt><dd>{fmt(rrip['cyc'])}</dd>
          <dt>LRU L1 misses</dt><dd>{fmt(lru['l1_accesses'] - lru['l1_hits'])}</dd>
          <dt>RRIP L1 misses</dt><dd>{fmt(rrip['l1_accesses'] - rrip['l1_hits'])}</dd>
          <dt>RRIP L1 hit rate</dt><dd>{rrip['l1_hits'] / rrip['l1_accesses']:.4f}</dd>
        </dl>
      </div>"""

    trows = ""
    for blk in (b16, b8):
        for a in ARMS:
            v, w = blk["arms"][a], blk["wl"][a]
            trows += (f'<tr><td>{blk["kb"]} KB</td><td>{LABEL[a]}</td>'
                      f'<td>{blk["ways"][a]}</td><td>{blk["sets"][a]}</td>'
                      f'<td>{fmt(w["vgg16"]["cyc"])}</td>'
                      f'<td>{fmt(w["resnet19"]["cyc"])}</td>'
                      f'<td>{fmt(v["cyc"])}</td>'
                      f'<td>{blk["ref"] / v["cyc"]:.4f}x</td>'
                      f'<td>{fmt(v["l1_accesses"] - v["l1_hits"])}</td>'
                      f'<td>{v["l1_hits"] / v["l1_accesses"]:.4f}</td></tr>')

    # Domain from the data, so no mark can clamp at an edge.
    allv = [float(by_layer[(t, f"lru_16w_8k")]["cycles"]) / float(by_layer[(t, f"{a}_8k")]["cycles"])
            for t in tags for a in ARMS]
    lo = (int(min(allv) * 20) - 1) / 20.0
    hi = (int(max(allv) * 20) + 2) / 20.0
    ticks = [round(lo + i * 0.05, 2) for i in range(int(round((hi - lo) / 0.05)) + 1)]

    fa16, l16 = b16["arms"]["lru_fa"], b16["arms"]["lru_16w"]
    return f"""<title>Ways at the L1</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@700;800&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{CSS}
.dot.rrip{{background:var(--rrip)}}
.dot.hollow{{background:var(--surface)!important}}
.dot.lru.hollow{{box-shadow:0 0 0 2px var(--surface), inset 0 0 0 2.5px var(--lru)}}
.dot.rrip.hollow{{box-shadow:0 0 0 2px var(--surface), inset 0 0 0 2.5px var(--rrip)}}
.dot.lfu.hollow{{box-shadow:0 0 0 2px var(--surface), inset 0 0 0 2.5px var(--lfu)}}
.row{{grid-template-columns:40px 1fr 72px}}
.axis{{grid-template-columns:40px 1fr 72px}}
.zero{{position:absolute; top:0; bottom:20px; width:1.5px; background:var(--ink-2); opacity:.45}}
.flat{{background:var(--surface); border:1px solid var(--hair); border-radius:3px;
  padding:18px 20px; display:flex; gap:16px; align-items:baseline; flex-wrap:wrap}}
.flat .n{{font-family:"IBM Plex Mono",monospace; font-size:26px; font-weight:500}}
</style>
<div class="wrap">
  <header>
    <div class="eyebrow">wcache 0907 &middot; associativity &middot; 16-way, 32-way, fully associative</div>
    <h1>How much does L1 associativity buy?</h1>
    <p class="lede">
      16-way, 32-way and fully associative, each under LRU and RRIP, at both L1
      sizes, over the same 31 layers. Capacity is fixed, so more ways means fewer
      sets. <b>16-way and 32-way are the same machine.</b> Fully associative,
      which should be the upper bound, is the <b>worst</b> arm at both sizes.
    </p>
    <dl class="spec">
      <div><dt>L1 sizes</dt><dd>16 KB &middot; 8 KB</dd></div>
      <div><dt>Ways</dt><dd>16 &middot; 32 &middot; all</dd></div>
      <div><dt>Line</dt><dd>64 B</dd></div>
      <div><dt>Layout</dt><dd>khkw_split</dd></div>
      <div><dt>L2</dt><dd>512 KB &middot; 16-way</dd></div>
      <div><dt>Cores</dt><dd>16</dd></div>
    </dl>
  </header>

  <section>
    <div class="head"><h2>16 KB: 16-way and 32-way are byte-identical</h2>
    <p>Both arms, under both policies, and equal to the 8-way number from the
    policy stage. Every way removed is a set gained, and
    <span class="mono">cin_blk</span> supplies a live index bit for each
    doubling, so the machine does not change.</p></div>
    <div class="flat">
      <span class="n">{fmt(b16['ref'])}</span>
      <span style="color:var(--muted)">cycles, identical for LRU and RRIP at both
      16-way and 32-way. Fully associative at the same 16 KB costs
      {fmt(fa16['cyc'] - l16['cyc'])} cycles more and
      <b style="color:var(--lfu)">{fa16['l1_accesses'] - fa16['l1_hits']:,.0f} L1
      misses against {l16['l1_accesses'] - l16['l1_hits']:,.0f}</b>, which is
      2.03x as many.</span>
    </div>
  </section>

  <section>
    <div class="head"><h2>Why removing the sets makes it worse</h2>
    <p>A tile sweeps <span class="mono">cin_blk</span> in order and comes back
    round, so a core's reference stream is close to a cycle over a working set of
    roughly 192 lines. When that cycle is a little larger than what the cache
    holds, LRU evicts the least recently used line, which under a cyclic sweep is
    exactly the line wanted next. One set of 256 ways is one such cycle. Splitting
    the array into sets breaks the pattern: each set sees only its share of the
    sweep, and wherever that share fits in its ways those lines survive.</p>
    <p>The DRAM traffic says the same thing. Fully associative at 16 KB fetches
    the identical {fa16['dram_bytes'] / 1e6:,.1f} MB from DRAM, so it is not
    missing on new data; it is re-fetching from the L2, whose hit rate rises from
    0.0000 to {fa16['l2_hits'] / fa16['l2_accesses']:.4f}. That is thrash, not
    capacity.</p>
    <p>RRIP is built for exactly this and it shows here for the first time in the
    study: at 16 KB it cuts the fully-associative miss count from
    {fa16['l1_accesses'] - fa16['l1_hits']:,.0f} to
    {b16['arms']['rrip_fa']['l1_accesses'] - b16['arms']['rrip_fa']['l1_hits']:,.0f},
    a 26% reduction, by inserting a line at a distant re-reference prediction so
    a line that is not reused leaves before it can displace one that is.</p></div>
  </section>

  <div class="tiles">{tiles}
  </div>

  <section>
    <div class="head">
      <h2>Per layer, at 8 KB</h2>
      <p>Cycles relative to 16-way LRU at the same size. Right of the line is
      faster. Colour is the associativity, hollow marks are LRU and solid are
      RRIP. The right column is the worst arm on that layer.</p>
    </div>
    <div class="panel">
      <div class="legend">
        <span><i style="background:var(--surface); box-shadow:inset 0 0 0 2.5px var(--lru)"></i>LRU 16-way</span>
        <span><i style="background:var(--lru)"></i>RRIP 16-way</span>
        <span><i style="background:var(--surface); box-shadow:inset 0 0 0 2.5px var(--rrip)"></i>LRU 32-way</span>
        <span><i style="background:var(--rrip)"></i>RRIP 32-way</span>
        <span><i style="background:var(--surface); box-shadow:inset 0 0 0 2.5px var(--lfu)"></i>LRU full</span>
        <span><i style="background:var(--lfu)"></i>RRIP full</span>
      </div>
      <div class="chart">
        <div class="zero" style="left:calc(40px + 10px + (100% - 112px) * {(1.0 - lo) / (hi - lo):.5f})"></div>
        {dots(by_layer, tags, "8k", lo, hi, ticks)}
      </div>
    </div>
  </section>

  <section>
    <div class="head"><h2>Accumulated cycles, both sizes</h2>
    <p>Layer totals summed over the 12 vgg16 and 19 resnet19 layers, each layer
    contributing the mean of its five samples. Hit rate is pooled over accumulated
    accesses. The reference for each size is its own 16-way LRU arm.</p></div>
    <div class="scroll"><table>
      <thead><tr><th>L1</th><th>Arm</th><th>Ways</th><th>Sets</th><th>vgg16</th>
      <th>resnet19</th><th>Total</th><th>vs 16w LRU</th><th>L1 misses</th>
      <th>L1 hit</th></tr></thead>
      <tbody>{trows}</tbody>
    </table></div>
  </section>

  <footer>
    <div>155 streams (31 layers x 5 samples) x 12 configs, 1860 rows, 0 failures,
    172.5s. Generated from <code>outputs/assoc_by_layer.csv</code> and
    <code>outputs/assoc_rows.csv</code>.</div>
    <div>Control check: <code>lru_16w_8k</code> reproduces the 8-way 8 KB makespan
    from the 0907 policy stage exactly, so the stages are comparable.</div>
    <div>Caveat: <code>l1_latency</code> is 0 in this configuration, so the model
    charges nothing for the deeper tag comparison that 32-way or a fully
    associative array would really cost.</div>
  </footer>
</div>
"""


def main():
    by_layer, acc, tags = load()
    p = OUT / "page_assoc.html"
    p.write_text(build(by_layer, acc, tags))
    print(p)


if __name__ == "__main__":
    main()
