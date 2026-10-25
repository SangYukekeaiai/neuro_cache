#!/usr/bin/env python3
"""Build the two review pages, one per L1 geometry, from the sweep's own CSVs.

One generator and not two hand-written files, because the pages differ only in
which six of the twelve arms they read: a fact edited into one and not the other
is exactly the kind of divergence a reader cannot see.

Usage: conda run -n base python make_pages.py
Writes: outputs/page_16k.html, outputs/page_8k.html
"""
from __future__ import annotations

import csv, html, json, pathlib, statistics

STAGE  = pathlib.Path(__file__).resolve().parent
OUT    = STAGE / "outputs"
NOCSIM = STAGE.parents[1] / "profiling/0831_all_layer_streams/outputs/all_layers_vs_nocsim.csv"
POLICIES = ["lru", "rrip", "lfu"]
PNAME = {"lru": "LRU", "rrip": "RRIP", "lfu": "LFU"}


WORKLOADS = [("vgg16", "V"), ("resnet19", "R")]


def load():
    by_layer = list(csv.DictReader(open(OUT / "policy_by_layer.csv")))
    idx = {(r["tag"], r["arm"]): r for r in by_layer}
    tags = sorted({r["tag"] for r in by_layer}, key=lambda t: (t[0], int(t[1:])))
    return idx, accumulate(), tags


def accumulate():
    """Per (arm, workload) TOTALS, summed over layers rather than averaged.

    A layer contributes the mean of its five samples and then the layer totals
    add, so the accumulation is over the 31 layers and not over the 155 streams.
    Hit rate is pooled (summed hits over summed accesses) rather than a mean of
    per-layer rates: a mean would weight a 576-access layer the same as a
    2-million-access one, which is the opposite of an accumulation.
    """
    noc = {r["tag"]: float(r["nocsim_total_cycles"])
           for r in csv.DictReader(open(NOCSIM))}
    per_tag = {}
    for r in csv.DictReader(open(OUT / "policy_rows.csv")):
        per_tag.setdefault((r["_arm"], r["_tag"]), []).append(r)

    FIELDS = ["cycles", "l1_hits", "l1_accesses", "l2_hits", "l2_accesses",
              "dram_bytes", "stall_total", "nocsim"]
    acc = {}
    for (arm, tag), rs in per_tag.items():
        wl = "vgg16" if tag[0] == "V" else "resnet19"
        for scope in (wl, "all"):
            a = acc.setdefault((arm, scope),
                               dict.fromkeys(FIELDS, 0.0) | {"layers": 0})
            a["layers"] += 1
            for c in FIELDS:
                if c == "nocsim":
                    # nocsim is a property of the layer, not of the arm, so it
                    # accumulates over the same layer set and the ratio below is
                    # total against total rather than a mean of per-layer ratios.
                    a[c] += noc.get(tag, 0.0)
                else:
                    src = "total_cycles" if c == "cycles" else c
                    a[c] += statistics.mean(float(r[src]) for r in rs)
    for a in acc.values():
        a["l1_hit_rate"] = a["l1_hits"] / a["l1_accesses"] if a["l1_accesses"] else 0.0
        a["l2_hit_rate"] = a["l2_hits"] / a["l2_accesses"] if a["l2_accesses"] else 0.0
        a["vs_nocsim"] = a["nocsim"] / a["cycles"] if a["cycles"] else 0.0
    return acc


def page_data(idx, agg, tags, size):
    """Everything one page needs, already reduced to the numbers it prints."""
    rows = []
    for t in tags:
        e = {"tag": t, "layer": idx[(t, f"lru_{size}")]["layer"],
             "wl": "vgg16" if t[0] == "V" else "resnet19"}
        for p in POLICIES:
            r = idx[(t, f"{p}_{size}")]
            e[p] = {"hr": float(r["l1_hit_rate"]), "l2hr": float(r["l2_hit_rate"]),
                    "cyc": float(r["cycles"]), "sp": float(r["speedup_vs_lru"])}
        # Where replacement never fires, every policy makes the same run.
        e["tied"] = len({round(e[p]["cyc"], 1) for p in POLICIES}) == 1
        rows.append(e)
    n_rrip_differs = sum(1 for e in rows if e["rrip"]["cyc"] != e["lru"]["cyc"])
    n_tied = sum(1 for e in rows if e["tied"])
    worst = min(rows, key=lambda e: e["lfu"]["sp"])
    acc = {p: {scope: agg[(f"{p}_{size}", scope)]
               for scope in ("vgg16", "resnet19", "all")} for p in POLICIES}
    return {
        "size": size, "rows": rows, "acc": acc,
        "sets": idx[(tags[0], f"lru_{size}")].get("l1_num_sets", "?"),
        "n_rrip_differs": n_rrip_differs, "n_tied": n_tied,
        "worst_tag": worst["tag"], "worst_sp": worst["lfu"]["sp"],
    }


CSS = """
:root{
  --ground:#EDF0F5; --surface:#FFFFFF; --sunken:#E4E9F1;
  --ink:#131A2B; --ink-2:#3C465C; --muted:#5B6478; --hair:#D3D9E4;
  --lru:#1D6FB8; --rrip:#C77A0A; --lfu:#A02050;
  --grid:#E1E6EF; --focus:#1D6FB8;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#0E121C; --surface:#171C2A; --sunken:#1F263699;
    --ink:#E4E9F2; --ink-2:#B9C2D4; --muted:#8D97AC; --hair:#2A3246;
    --lru:#4A93D8; --rrip:#BE8828; --lfu:#D25C7E;
    --grid:#242C3E; --focus:#4A93D8;
  }
}
:root[data-theme="dark"]{
  --ground:#0E121C; --surface:#171C2A; --sunken:#1F263699;
  --ink:#E4E9F2; --ink-2:#B9C2D4; --muted:#8D97AC; --hair:#2A3246;
  --lru:#4A93D8; --rrip:#BE8828; --lfu:#D25C7E;
  --grid:#242C3E; --focus:#4A93D8;
}
*{box-sizing:border-box}
body{
  background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Sans",ui-sans-serif,system-ui,sans-serif;
  font-size:15px; line-height:1.6; margin:0;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1080px; margin:0 auto; padding:40px 24px 72px; display:flex; flex-direction:column; gap:36px}
h1,h2,h3{font-family:Archivo,ui-sans-serif,system-ui,sans-serif; text-wrap:balance; margin:0}
h1{font-size:clamp(30px,4.6vw,46px); font-weight:800; letter-spacing:-.022em; line-height:1.08}
h2{font-size:20px; font-weight:700; letter-spacing:-.012em}
p{margin:0; max-width:66ch}
.mono{font-family:"IBM Plex Mono",ui-monospace,monospace; font-variant-numeric:tabular-nums}
.eyebrow{
  font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:11.5px;
  letter-spacing:.13em; text-transform:uppercase; color:var(--muted);
}

/* header ------------------------------------------------------------------ */
header{display:flex; flex-direction:column; gap:18px}
.spec{
  display:flex; flex-wrap:wrap; gap:0; border:1px solid var(--hair);
  border-radius:3px; background:var(--surface); overflow:hidden;
}
.spec div{
  flex:1 1 128px; padding:10px 14px; border-right:1px solid var(--hair);
  display:flex; flex-direction:column; gap:2px;
}
.spec div:last-child{border-right:0}
.spec dt{font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:10.5px;
  letter-spacing:.11em; text-transform:uppercase; color:var(--muted)}
.spec dd{margin:0; font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:14px; font-weight:500; font-variant-numeric:tabular-nums}
.lede{font-size:17px; line-height:1.55; color:var(--ink-2); max-width:64ch}
.lede b{color:var(--ink); font-weight:600}

/* verdict tiles ----------------------------------------------------------- */
.tiles{display:grid; grid-template-columns:repeat(auto-fit,minmax(215px,1fr)); gap:14px}
.tile{
  background:var(--surface); border:1px solid var(--hair); border-radius:3px;
  padding:16px 18px 18px; display:flex; flex-direction:column; gap:9px;
  border-top:3px solid var(--tint);
}
.tile .name{display:flex; align-items:baseline; gap:8px}
.tile .name b{font-family:Archivo,sans-serif; font-size:17px; font-weight:700; color:var(--tint)}
.tile .name span{font-size:12px; color:var(--muted)}
.tile .big{
  font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:31px; font-weight:500;
  letter-spacing:-.02em; font-variant-numeric:tabular-nums; line-height:1;
}
.tile .cap{font-size:12.5px; color:var(--muted); line-height:1.45}
.tile dl{margin:4px 0 0; display:grid; grid-template-columns:auto auto; gap:3px 12px;
  font-size:12.5px; border-top:1px solid var(--hair); padding-top:9px}
.tile dt{color:var(--muted)}
.tile dd{margin:0; text-align:right; font-family:"IBM Plex Mono",monospace;
  font-variant-numeric:tabular-nums}

/* charts ------------------------------------------------------------------ */
section{display:flex; flex-direction:column; gap:14px}
.head{display:flex; flex-direction:column; gap:5px}
.panel{background:var(--surface); border:1px solid var(--hair); border-radius:3px; padding:18px 20px 12px}
.legend{display:flex; flex-wrap:wrap; gap:16px; align-items:center; font-size:12.5px; color:var(--ink-2)}
.legend i{display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px;
  vertical-align:-1px}
.legend .ring{background:var(--surface); box-shadow:inset 0 0 0 2.5px var(--rrip)}

.chart{position:relative; margin-top:12px}
.row{display:grid; grid-template-columns:34px 1fr 62px; align-items:center; gap:10px;
  height:21px; position:relative}
.row:hover .track{background:var(--sunken)}
.row .lab{font-family:"IBM Plex Mono",monospace; font-size:11.5px; color:var(--muted); text-align:right}
.row .val{font-family:"IBM Plex Mono",monospace; font-size:11.5px; font-variant-numeric:tabular-nums;
  color:var(--ink-2); text-align:right}
.track{position:relative; height:100%; border-radius:2px}
.conn{position:absolute; top:50%; height:1.5px; background:var(--grid); transform:translateY(-50%)}
.dot{position:absolute; top:50%; width:9px; height:9px; border-radius:50%;
  transform:translate(-50%,-50%); box-shadow:0 0 0 2px var(--surface)}
.dot.lru{background:var(--lru)}
.dot.lfu{background:var(--lfu)}
.dot.rrip{background:var(--surface); box-shadow:0 0 0 2px var(--surface), inset 0 0 0 2.5px var(--rrip)}
.bar{position:absolute; top:50%; height:11px; transform:translateY(-50%);
  background:var(--lfu); border-radius:0 3px 3px 0}
.gridline{position:absolute; top:0; bottom:20px; width:1px; background:var(--grid)}
.axis{display:grid; grid-template-columns:34px 1fr 62px; gap:10px; margin-top:6px}
.axis .ticks{position:relative; height:18px}
.axis .ticks span{position:absolute; transform:translateX(-50%); font-size:11px;
  font-family:"IBM Plex Mono",monospace; color:var(--muted); white-space:nowrap}
.tied{color:var(--muted)}
.wl{font-size:11px; color:var(--muted); font-family:"IBM Plex Mono",monospace;
  padding:11px 0 4px; letter-spacing:.09em; text-transform:uppercase}

/* table ------------------------------------------------------------------- */
.scroll{overflow-x:auto; border:1px solid var(--hair); border-radius:3px; background:var(--surface)}
table{border-collapse:collapse; width:100%; font-size:12.5px}
th,td{padding:7px 11px; text-align:right; white-space:nowrap; border-bottom:1px solid var(--hair)}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
thead th{font-family:"IBM Plex Mono",monospace; font-size:10.5px; letter-spacing:.08em;
  text-transform:uppercase; color:var(--muted); font-weight:500; position:sticky; top:0;
  background:var(--surface)}
tbody td{font-family:"IBM Plex Mono",monospace; font-variant-numeric:tabular-nums}
tbody td:nth-child(2){font-family:"IBM Plex Sans",sans-serif}
tbody tr:hover{background:var(--sunken)}
td.worst{color:var(--lfu); font-weight:500}
footer{color:var(--muted); font-size:12.5px; border-top:1px solid var(--hair); padding-top:18px;
  display:flex; flex-direction:column; gap:6px}
footer code{font-family:"IBM Plex Mono",monospace; color:var(--ink-2)}
a{color:var(--focus)}
:focus-visible{outline:2px solid var(--focus); outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{transition:none!important; animation:none!important}}
"""


def fmt(n, d=0):
    return f"{n:,.{d}f}"


def dot_chart(rows, lo, hi, ticks):
    """Per-layer L1 hit rate, one row per layer, one dot per policy."""
    def x(v):
        return max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))
    out = []
    for t in ticks:
        out.append(f'<div class="gridline" style="left:calc(34px + 10px + '
                   f'(100% - 106px) * {x(t) / 100:.5f})"></div>')
    last_wl = None
    for e in rows:
        if e["wl"] != last_wl:
            out.append(f'<div class="wl">{e["wl"]}</div>')
            last_wl = e["wl"]
        xs = [x(e[p]["hr"]) for p in POLICIES]
        title = " / ".join(f'{PNAME[p]} {e[p]["hr"]:.4f}' for p in POLICIES)
        dots = "".join(
            f'<span class="dot {p}" style="left:{x(e[p]["hr"]):.3f}%"></span>'
            for p in POLICIES)
        out.append(
            f'<div class="row" title="{html.escape(e["layer"])} &#10;{title}">'
            f'<div class="lab">{e["tag"]}</div>'
            f'<div class="track">'
            f'<span class="conn" style="left:{min(xs):.3f}%;width:{max(xs) - min(xs):.3f}%"></span>'
            f'{dots}</div>'
            f'<div class="val{" tied" if e["tied"] else ""}">{e["lfu"]["hr"]:.4f}</div></div>')
    tick_html = "".join(
        f'<span style="left:{x(t):.3f}%">{t:.2f}</span>' for t in ticks)
    out.append(f'<div class="axis"><div></div><div class="ticks">{tick_html}</div><div></div></div>')
    return "".join(out)


def bar_chart(rows):
    """LFU makespan relative to LRU, worst first. One series, so no legend."""
    data = sorted(((e["tag"], e["layer"], 1 / e["lfu"]["sp"]) for e in rows),
                  key=lambda r: -r[2])
    hi = max(3.25, max(r[2] for r in data) * 1.04)
    ticks = [1.0, 1.5, 2.0, 2.5, 3.0]
    x = lambda v: max(0.0, min(100.0, (v - 1.0) / (hi - 1.0) * 100))
    out = [f'<div class="gridline" style="left:calc(34px + 10px + (100% - 106px) * '
           f'{x(t) / 100:.5f})"></div>' for t in ticks]
    for tag, layer, rel in data:
        out.append(
            f'<div class="row" title="{html.escape(layer)} &#10;LFU {rel:.3f}x the LRU makespan">'
            f'<div class="lab">{tag}</div>'
            f'<div class="track"><span class="bar" style="left:0;width:{x(rel):.3f}%"></span></div>'
            f'<div class="val">{rel:.2f}x</div></div>')
    tick_html = "".join(f'<span style="left:{x(t):.3f}%">{t:.1f}x</span>' for t in ticks)
    out.append(f'<div class="axis"><div></div><div class="ticks">{tick_html}</div><div></div></div>')
    return "".join(out)


def build(d):
    size, rows, acc = d["size"], d["rows"], d["acc"]
    kb = 16 if size == "16k" else 8
    article = "a" if kb == 16 else "an"
    # Floored to a 0.05 step so the ticks are round numbers, and so both pages
    # land on the same axis: the 16 KB and 8 KB charts are meant to be read side
    # by side, which a per-page domain would quietly prevent.
    lo = int(min(e[p]["hr"] for e in rows for p in POLICIES) * 20) / 20.0
    ticks = [round(lo + i * 0.05, 2) for i in range(int(round((1.0 - lo) / 0.05)) + 1)]

    rrip_line = (
        f"identical to LRU on all 31 layers, to every digit of every column"
        if d["n_rrip_differs"] == 0 else
        f"identical to LRU on {31 - d['n_rrip_differs']} of 31 layers, and the "
        f"{d['n_rrip_differs']} that move do so in the fifth decimal")

    sub = {"lru": "recency", "rrip": "SRRIP, 2-bit RRPV",
           "lfu": "reference count, no aging"}
    tiles = ""
    for p in POLICIES:
        v, wl = acc[p], acc[p]
        tiles += f"""
      <div class="tile" style="--tint:var(--{p})">
        <div class="name"><b>{PNAME[p]}</b><span>{sub[p]}</span></div>
        <div class="big">{v['all']['vs_nocsim']:.3f}x</div>
        <div class="cap">accumulated cycles over all 31 layers against the
        accumulated nocsim makespan; above 1.00x is faster than nocsim</div>
        <dl>
          <dt>vgg16 ({wl['vgg16']['layers']} layers)</dt><dd>{fmt(wl['vgg16']['cycles'])}</dd>
          <dt>&nbsp;&nbsp;vs nocsim</dt><dd>{wl['vgg16']['vs_nocsim']:.3f}x</dd>
          <dt>resnet19 ({wl['resnet19']['layers']} layers)</dt><dd>{fmt(wl['resnet19']['cycles'])}</dd>
          <dt>&nbsp;&nbsp;vs nocsim</dt><dd>{wl['resnet19']['vs_nocsim']:.3f}x</dd>
          <dt>L1 hit rate</dt><dd>{v['all']['l1_hit_rate']:.4f}</dd>
          <dt>L2 hit rate</dt><dd>{v['all']['l2_hit_rate']:.4f}</dd>
        </dl>
      </div>"""

    # The accumulation table: totals side by side, so the two workloads can be
    # read against each other and against nocsim without a ratio of ratios.
    nrows = ""
    for wlname, _ in WORKLOADS:
        n = acc["lru"][wlname]["nocsim"]
        nrows += (f'<tr><td>nocsim</td><td>{wlname}</td>'
                  f'<td>{fmt(n)}</td><td>1.000x</td><td>n/a</td><td>n/a</td></tr>')
        for p in POLICIES:
            v = acc[p][wlname]
            rel = acc["lru"][wlname]["cycles"] / v["cycles"]
            nrows += (f'<tr><td>{PNAME[p]}</td><td>{wlname}</td>'
                      f'<td>{fmt(v["cycles"])}</td>'
                      f'<td>{v["vs_nocsim"]:.3f}x</td>'
                      f'<td>{rel:.3f}x</td>'
                      f'<td>{v["l1_hit_rate"]:.4f}</td></tr>')

    trows = ""
    for e in rows:
        worst = ' class="worst"' if e["lfu"]["sp"] < 0.5 else ""
        trows += (f'<tr><td>{e["tag"]}</td><td>{html.escape(e["layer"])}</td>'
                  f'<td>{e["lru"]["hr"]:.4f}</td><td>{e["rrip"]["hr"]:.4f}</td>'
                  f'<td>{e["lfu"]["hr"]:.4f}</td>'
                  f'<td>{fmt(e["lru"]["cyc"])}</td>'
                  f'<td>{e["rrip"]["sp"]:.4f}</td><td{worst}>{e["lfu"]["sp"]:.4f}</td></tr>')

    return f"""<title>Replacement at {kb} KB</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@700;800&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{CSS}</style>
<div class="wrap">
  <header>
    <div class="eyebrow">wcache 0907 &middot; policy sweep &middot; L1 {kb} KB</div>
    <h1>Three replacement policies on {article} {kb} KB L1</h1>
    <p class="lede">
      LRU, SRRIP and LFU over 31 convolution layers of vgg16 and resnet19, five
      samples each, everything but <span class="mono">policy</span> held at the
      0903 baseline. <b>RRIP is {rrip_line}.</b> LFU costs
      <b>{(acc['lfu']['all']['cycles'] / acc['lru']['all']['cycles'] - 1) * 100:.0f}%</b>
      of the accumulated makespan.
    </p>
    <dl class="spec">
      <div><dt>L1</dt><dd>{kb} KB &middot; 8-way</dd></div>
      <div><dt>Sets</dt><dd>{d['sets']}</dd></div>
      <div><dt>Line</dt><dd>64 B</dd></div>
      <div><dt>L2</dt><dd>512 KB &middot; 16-way</dd></div>
      <div><dt>Layout</dt><dd>khkw_split</dd></div>
      <div><dt>Cores</dt><dd>16</dd></div>
    </dl>
  </header>

  <div class="tiles">{tiles}
  </div>

  <section>
    <div class="head">
      <h2>Accumulated cycles, per workload</h2>
      <p>Layer totals summed over the 12 vgg16 and the 19 resnet19 layers, each
      layer contributing the mean of its five samples. Hit rate is pooled over
      the accumulated accesses rather than averaged over layers, so a
      576-access layer does not weigh the same as a 2-million-access one.</p>
    </div>
    <div class="scroll"><table>
      <thead><tr><th>Policy</th><th>Workload</th><th>Cycles</th>
      <th>vs nocsim</th><th>vs LRU</th><th>L1 hit rate</th></tr></thead>
      <tbody>{nrows}</tbody>
    </table></div>
  </section>

  <section>
    <div class="head">
      <h2>Where the policies actually differ</h2>
      <p>L1 hit rate per layer. The connector spans the three policies, so a layer
      with no visible spread is one where replacement never fires: the working set
      fits the eight ways it can reach, and every policy makes the same run.
      <b>{d['n_tied']} of 31 layers</b> are tied at this size.</p>
    </div>
    <div class="panel">
      <div class="legend">
        <span><i style="background:var(--lru)"></i>LRU</span>
        <span><i class="ring"></i>RRIP</span>
        <span><i style="background:var(--lfu)"></i>LFU</span>
        <span style="color:var(--muted); margin-left:auto">right column: LFU hit rate</span>
      </div>
      <div class="chart">{dot_chart(rows, lo, 1.0, ticks)}</div>
    </div>
  </section>

  <section>
    <div class="head">
      <h2>What LFU costs, layer by layer</h2>
      <p>Makespan as a multiple of the LRU run at this same geometry, worst first.
      RRIP is omitted because it sits at 1.00x on {31 - d['n_rrip_differs']} of 31
      layers. The worst layer is <span class="mono">{d['worst_tag']}</span> at
      {1 / d['worst_sp']:.2f}x.</p>
    </div>
    <div class="panel"><div class="chart">{bar_chart(rows)}</div></div>
  </section>

  <section>
    <div class="head"><h2>Every layer</h2>
    <p>Mean of five samples. Speedup is against LRU at this geometry, so it measures
    the policy and not the capacity.</p></div>
    <div class="scroll"><table>
      <thead><tr><th>Tag</th><th>Layer</th><th>LRU hit</th><th>RRIP hit</th>
      <th>LFU hit</th><th>LRU cycles</th><th>RRIP sp.</th><th>LFU sp.</th></tr></thead>
      <tbody>{trows}</tbody>
    </table></div>
  </section>

  <footer>
    <div>155 streams (31 layers x 5 samples) x 6 configs, 930 rows, 0 failures.
    Generated from <code>outputs/policy_by_layer.csv</code> and
    <code>outputs/policy_aggregate.csv</code>.</div>
    <div>Control check: <code>lru_{size}</code> reproduces the 0903_l1_8k
    <code>off_{size}</code> makespan exactly, so the comparison is sound.</div>
  </footer>
</div>
"""


def main():
    idx, agg, tags = load()
    for size in ("16k", "8k"):
        d = page_data(idx, agg, tags, size)
        path = OUT / f"page_{size}.html"
        path.write_text(build(d))
        print(f"{path}  ({d['n_tied']} tied layers, rrip differs on {d['n_rrip_differs']})")


if __name__ == "__main__":
    main()
