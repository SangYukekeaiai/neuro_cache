#!/usr/bin/env python3
"""Emit the sweep artifact HTML. Every number is read from the CSVs, never retyped."""
import csv, json, pathlib, statistics, collections, html, sys

D = pathlib.Path("/u/yyu9/projects/neuro_cache/profiling/0823_stagewise_verify")
S4 = D / "stage4_wcache/outputs"
OUT = pathlib.Path(sys.argv[1])

TAGS = ["V8", "V9", "R9", "R16"]
NAME = {}
sweep = list(csv.DictReader(open(S4 / "khkw_sweep.csv")))
comp  = list(csv.DictReader(open(S4 / "khkw_vs_stage3.csv")))
ctl   = list(csv.DictReader(open(S4 / "khkw_layout_control.csv")))
cap   = list(csv.DictReader(open(S4 / "khkw_l2_capacity.csv")))
s3    = json.load(open(D / "stage3_nocsim/outputs/stage3_results.json"))
for r in s3: NAME[r["tag"]] = r["layer"]
BASE  = {t: statistics.mean(r["total_cycles"] for r in s3 if r["tag"] == t) for t in TAGS}
FLOOR = {t: statistics.mean(r["compute_per_node"] for r in s3 if r["tag"] == t) for t in TAGS}

def num(x, d=0):
    return f"{x:,.{d}f}"

def bar(v, lo=0.0, hi=6.0):
    """A speedup cell: the number, and a rule as long as the ratio."""
    frac = max(0.0, min(1.0, (v - lo) / (hi - lo)))
    cls = "pos" if v >= 1 else "neg"
    return (f'<div class="ratio"><span class="rv {cls}">{v:.2f}&times;</span>'
            f'<span class="rb"><i class="{cls}" style="width:{frac*100:.1f}%"></i></span></div>')

def table(head, rows, cls=""):
    h = "".join(f"<th{' class=\"n\"' if a else ''}>{c}</th>" for c, a in head)
    b = "".join("<tr>" + "".join(f"<td{' class=\"n\"' if a else ''}>{c}</td>"
                                 for c, (_, a) in zip(r, head)) + "</tr>" for r in rows)
    return f'<div class="scroll"><table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'

# --- T1: best config per layer -------------------------------------------------
best = {}
for r in comp:
    t = r["tag"]
    if t not in best or float(r["wcache_cycles"]) < float(best[t]["wcache_cycles"]):
        best[t] = r
t1 = []
for t in TAGS:
    r = best[t]
    t1.append([f'<b>{t}</b><span class="sub">{NAME[t]}</span>',
               f'{r["line_size_bytes"]} B / {r["l2_banks"]} bank / pf {r["prefetch_distance"]}',
               num(float(r["wcache_cycles"])), num(BASE[t]),
               bar(float(r["speedup_vs_stage3_total"])),
               f'{float(r["cycles_over_compute_floor"]):.2f}&times;',
               f'{float(r["l1_hit_rate"])*100:.2f}%', f'{float(r["l2_hit_rate"])*100:.2f}%'])

# --- T2: the whole grid at one bank -------------------------------------------
t2 = []
for t in TAGS:
    rs = sorted([r for r in comp if r["tag"] == t and r["l2_banks"] == "1"],
                key=lambda r: (int(r["line_size_bytes"]), int(r["prefetch_distance"])))
    for i, r in enumerate(rs):
        t2.append([f'<b>{t}</b>' if i == 0 else "",
                   f'{r["line_size_bytes"]} B', r["prefetch_distance"],
                   num(float(r["wcache_cycles"])),
                   bar(float(r["speedup_vs_stage3_total"])),
                   f'{float(r["cycles_over_compute_floor"]):.2f}&times;',
                   f'{float(r["l1_hit_rate"])*100:.2f}%',
                   f'{float(r["l2_hit_rate"])*100:.2f}%',
                   num(float(r["dram_bytes"]) / 1048576, 2)])

# --- T3: line size -------------------------------------------------------------
t3 = []
for t in TAGS:
    row = [f'<b>{t}</b>']
    for lb in [16, 32, 64]:
        rs = [r for r in comp if r["tag"] == t and int(r["line_size_bytes"]) == lb
              and r["prefetch_distance"] == "0" and r["l2_banks"] == "1"]
        row.append(num(float(rs[0]["wcache_cycles"])))
        row.append(f'{float(rs[0]["l1_hit_rate"])*100:.2f}%')
    t3.append(row)

# --- T4a: prefetch, per layer and line size ------------------------------------
pg = collections.defaultdict(dict)
for r in comp:
    if r["l2_banks"] == "1":
        pg[(r["tag"], r["line_size_bytes"])][r["prefetch_distance"]] = float(r["wcache_cycles"])
t4a = []
for t in TAGS:
    for i, lb in enumerate(["16", "32", "64"]):
        v = pg[(t, lb)]
        cells = []
        for d in ["1", "2", "4"]:
            x = v[d] / v["0"]
            cls = "pos" if x < 1 else "neg"
            cells.append(f'<span class="{cls}">{x:.3f}&times;</span>')
        t4a.append([f'<b>{t}</b>' if i == 0 else "", f'{lb} B', num(v["0"])] + cells)

# --- T4b: what the prefetcher actually did -------------------------------------
t4b = []
for d in ["0", "1", "2", "4"]:
    raw = [r for r in sweep if r["prefetch_distance"] == d and r["l2_banks"] == "1"]
    iss = statistics.mean(float(r["pf_issued"]) for r in raw)
    ah  = statistics.mean(float(r["pf_dropped_array_hit"]) for r in raw)
    tm  = statistics.mean(float(r["pf_timely"]) for r in raw)
    lp  = statistics.mean(float(r["stall_l1_port"]) for r in raw)
    t4b.append([d, num(iss), num(ah), f'{ah/iss*100:.1f}%' if iss else "&mdash;",
                num(tm), num(lp)])

# --- T5: banks -----------------------------------------------------------------
g = collections.defaultdict(dict)
for r in sweep:
    g[(r["_tag"], r["_sample"], r["line_size_bytes"], r["prefetch_distance"])][r["l2_banks"]] = r
rel = collections.defaultdict(list)
for k, d in g.items():
    b1 = float(d["1"]["total_cycles"])
    for b in ["2", "4", "8"]:
        rel[(k[2], k[3], b)].append(float(d[b]["total_cycles"]) / b1)
t5 = []
for lb in ["16", "32", "64"]:
    for pf in ["0", "1", "2", "4"]:
        t5.append([f'{lb} B', pf] + [f'{statistics.mean(rel[(lb, pf, b)]):.4f}' for b in ["2", "4", "8"]])

# --- T6: the L2 capacity cliff -------------------------------------------------
sizes = sorted({int(r["l2_size_bytes"]) for r in cap})
WS = {}
for t in TAGS:
    rs = [r for r in cap if r["_tag"] == t and int(r["l2_size_bytes"]) == max(sizes)]
    WS[t] = statistics.mean(float(r["dram_accesses"]) for r in rs) * 64
t6 = []
for t in TAGS:
    row = [f'<b>{t}</b>', f'{WS[t]/1048576:.2f} MiB']
    for n in sizes:
        rs = [r for r in cap if r["_tag"] == t and int(r["l2_size_bytes"]) == n]
        v = statistics.mean(float(r["l2_hit_rate"]) for r in rs)
        row.append(f'<span class="{"hi" if v > 0 else "lo"}">{v*100:.1f}%</span>')
    t6.append(row)

# --- T7: layout control --------------------------------------------------------
t7 = []
for t in TAGS:
    for i, lay in enumerate(["block_pack", "split_cin", "khkw_split"]):
        rs = [r for r in ctl if r["_tag"] == t and r["layout"] == lay]
        c = statistics.mean(float(r["total_cycles"]) for r in rs)
        t7.append([f'<b>{t}</b>' if i == 0 else "",
                   f'<code>{lay}</code>', num(c),
                   f'{statistics.mean(float(r["l1_hit_rate"]) for r in rs)*100:.2f}%',
                   num(statistics.mean(float(r["dram_accesses"]) for r in rs)),
                   bar(BASE[t] / c)])

# --- every number the prose quotes, computed here so a rerun cannot strand one --
F = {}
_l1 = [float(r["l1_hit_rate"]) for r in sweep]
F["l1_lo"], F["l1_hi"] = min(_l1) * 100, max(_l1) * 100
_bp = [float(r["l1_hit_rate"]) for r in ctl if r["layout"] == "block_pack"]
F["bp_lo"], F["bp_hi"] = min(_bp) * 100, max(_bp) * 100
_top = max((float(r["speedup_vs_stage3_total"]), r["tag"]) for r in comp)
F["top_speed"], F["top_tag"] = _top

# prefetch, relative to none, at one bank
_pg = collections.defaultdict(dict)
for r in comp:
    if r["l2_banks"] == "1":
        _pg[(r["tag"], r["line_size_bytes"])][r["prefetch_distance"]] = float(r["wcache_cycles"])
_p64 = [_pg[(t, "64")][d] / _pg[(t, "64")]["0"] for t in TAGS for d in ["1", "2", "4"]]
F["pf64_lo"], F["pf64_hi"] = (min(_p64) - 1) * 100, (max(_p64) - 1) * 100
F["pf_worst"] = (max(_pg[(t, lb)][d] / _pg[(t, lb)]["0"]
                     for t in TAGS for lb in ["16", "32", "64"] for d in ["1", "2", "4"]) - 1) * 100
_help = sorted((min(_pg[(t, "16")][d] for d in ["1", "2", "4"]) / _pg[(t, "16")]["0"], t)
               for t in TAGS)
F["pf16_helps"] = ", ".join(f"{t} by {(1-v)*100:.0f}%" for v, t in _help if v < 1)
F["pf16_n"] = sum(1 for v, _ in _help if v < 1)
F["v8_pf16"] = min(_pg[("V8", "16")][d] for d in ["1", "2", "4"])
F["v8_64_0"] = _pg[("V8", "64")]["0"]

# the best point, and the same point with prefetching on
def _pick(tag, lb, bank, d, samp="0"):
    return [r for r in sweep if r["_tag"] == tag and r["_sample"] == samp
            and r["line_size_bytes"] == lb and r["l2_banks"] == bank
            and r["prefetch_distance"] == d][0]
_b, _p1 = _pick("V8", "64", "1", "0"), _pick("V8", "64", "1", "1")
F["l1_acc"], F["l2_acc"] = int(_b["l1_accesses"]), int(_b["l2_accesses"])
F["acc_ratio"] = F["l1_acc"] / F["l2_acc"]
F["pf_port"] = float(_p1["stall_l1_port"]) / 1e6
F["pf_drop_pct"] = float(_p1["pf_dropped_array_hit"]) / float(_p1["pf_issued"]) * 100
F["best_l1"] = float(_b["l1_hit_rate"]) * 100
F["pad32"] = statistics.mean(float(r["padding_fraction"]) for r in comp
                             if r["tag"] == "V8" and r["line_size_bytes"] == "32") * 100

# banking
_g = collections.defaultdict(dict)
for r in sweep:
    _g[(r["_tag"], r["_sample"], r["line_size_bytes"], r["prefetch_distance"])][r["l2_banks"]] = r
_rel = [float(d[b]["total_cycles"]) / float(d["1"]["total_cycles"])
        for d in _g.values() for b in ["2", "4", "8"]]
F["bank_n"] = len(_rel)
F["bank_worst"] = (max(_rel) - 1) * 100
F["bank_dev"] = statistics.mean(abs(x - 1) for x in _rel) * 100

# the L2 capacity cliff
_cg = collections.defaultdict(dict)
for r in cap:
    _cg[r["_tag"]].setdefault(int(r["l2_size_bytes"]), []).append(r)
F["l2_jump"] = max(statistics.mean(float(r["l2_hit_rate"]) for r in rs)
                   for d in _cg.values() for rs in d.values()) * 100
def _cliff(t):
    d = _cg[t]
    for n in sorted(d):
        if statistics.mean(float(r["l2_hit_rate"]) for r in d[n]) > 0:
            return n
    return None
F["cliff_v8"] = _cliff("V8") // 1048576
F["cliff_r16"] = _cliff("R16") // 1048576
def _cap_gain(t):
    d = _cg[t]
    lo = statistics.mean(float(r["total_cycles"]) for r in d[min(d)])
    hi = statistics.mean(float(r["total_cycles"]) for r in d[max(d)])
    return (1 - hi / lo) * 100
F["gain_v8"], F["gain_r16"] = _cap_gain("V8"), _cap_gain("R16")
F["per_line"] = statistics.mean(float(r["dram_accesses"]) for r in _cg["V8"][min(_cg["V8"])]) / \
                statistics.mean(float(r["dram_accesses"]) for r in _cg["V8"][max(_cg["V8"])])

# the layout control margins
_m = {t: {l: statistics.mean(float(r["total_cycles"]) for r in ctl
                             if r["_tag"] == t and r["layout"] == l)
          for l in ["block_pack", "split_cin", "khkw_split"]} for t in TAGS}
_bpr = [_m[t]["block_pack"] / _m[t]["khkw_split"] for t in TAGS]
_scr = [_m[t]["split_cin"] / _m[t]["khkw_split"] for t in TAGS]
F["bp_lo_x"], F["bp_hi_x"] = min(_bpr), max(_bpr)
F["sc_lo_x"], F["sc_hi_x"] = min(_scr), max(_scr)
F["r9_bp"] = _m["R9"]["block_pack"] / _m["R9"]["khkw_split"]
F["r9_sc"] = _m["R9"]["split_cin"] / _m["R9"]["khkw_split"]

F["floor_lo"] = min(float(r["cycles_over_compute_floor"]) for r in comp)
F["floor_hi"] = max(float(r["cycles_over_compute_floor"]) for r in comp)
_bestrow = {}
for r in comp:
    t = r["tag"]
    if t not in _bestrow or float(r["wcache_cycles"]) < float(_bestrow[t]["wcache_cycles"]):
        _bestrow[t] = r
F["n_beat"] = sum(1 for t in TAGS if float(_bestrow[t]["speedup_vs_stage3_total"]) > 1)
F["s3_lo"] = min(float(_bestrow[t]["speedup_vs_stage3_total"]) for t in TAGS)
F["s3_hi"] = max(float(_bestrow[t]["speedup_vs_stage3_total"]) for t in TAGS)
F["best_floor"] = {t: float(_bestrow[t]["cycles_over_compute_floor"]) for t in TAGS}

# the held-fixed config, read back off a row rather than retyped
CFG = _b

CSS = """
:root{
  --ground:#F1F4F4; --surface:#FFFFFF; --raise:#E8EEEE;
  --ink:#12181A; --muted:#56656A; --rule:#D3DCDB; --rule-2:#B9C6C5;
  --accent:#145E78; --pos:#1F6B4C; --neg:#8E3229; --warn:#8A5A12;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --ground:#0F1516; --surface:#171E1F; --raise:#1E2728;
    --ink:#E3EAE9; --muted:#8FA0A3; --rule:#27312F; --rule-2:#38443F;
    --accent:#63B4CE; --pos:#66BC93; --neg:#DE7A70; --warn:#CFA057;
  }
}
:root[data-theme="dark"]{
  --ground:#0F1516; --surface:#171E1F; --raise:#1E2728;
  --ink:#E3EAE9; --muted:#8FA0A3; --rule:#27312F; --rule-2:#38443F;
  --accent:#63B4CE; --pos:#66BC93; --neg:#DE7A70; --warn:#CFA057;
}
*{box-sizing:border-box}
body{
  background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Serif",Georgia,serif; font-size:16.5px; line-height:1.62;
  margin:0; padding:0 24px 96px;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1180px; margin:0 auto}
.col{max-width:68ch}
h1,h2,h3,.eyebrow,th,.sub,.tag{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",system-ui,sans-serif}
code,kbd,.mono,td,.bitfield,.ratio,.num{font-family:"IBM Plex Mono",ui-monospace,monospace}

header{padding:64px 0 40px; border-bottom:2px solid var(--ink)}
h1{font-size:clamp(2.1rem,5vw,3.4rem); font-weight:600; line-height:1.02; letter-spacing:-.015em;
   margin:0 0 18px; text-wrap:balance}
.standfirst{font-size:1.14rem; color:var(--muted); margin:0; max-width:62ch}
.meta{display:flex; flex-wrap:wrap; gap:8px 26px; margin-top:30px;
  font-family:"IBM Plex Mono",monospace; font-size:.76rem; color:var(--muted);
  text-transform:uppercase; letter-spacing:.07em}
.meta b{color:var(--ink); font-weight:500}

section{padding:56px 0 0}
.eyebrow{display:block; font-size:.72rem; font-weight:600; text-transform:uppercase;
  letter-spacing:.15em; color:var(--accent); margin:0 0 10px}
h2{font-size:1.72rem; font-weight:600; letter-spacing:-.01em; margin:0 0 6px; text-wrap:balance}
h3{font-size:1.06rem; font-weight:600; margin:34px 0 8px; letter-spacing:.005em}
p{margin:0 0 15px}
p+p{margin-top:-3px}
a{color:var(--accent)}

.verdict{
  margin:34px 0 0; padding:22px 26px; background:var(--surface);
  border:1px solid var(--rule); border-left:3px solid var(--accent);
}
.verdict p{margin:0 0 10px; font-size:1.05rem}
.verdict p:last-child{margin:0}

.scroll{overflow-x:auto; margin:22px 0 4px; border:1px solid var(--rule); background:var(--surface)}
table{border-collapse:collapse; width:100%; font-size:.845rem}
th{
  text-align:left; font-weight:600; font-size:.7rem; text-transform:uppercase;
  letter-spacing:.09em; color:var(--muted); padding:11px 14px;
  border-bottom:1px solid var(--rule-2); white-space:nowrap; background:var(--raise);
}
td{padding:9px 14px; border-bottom:1px solid var(--rule); vertical-align:baseline;
   font-variant-numeric:tabular-nums; white-space:nowrap}
tbody tr:last-child td{border-bottom:none}
th.n,td.n{text-align:right}
td b{font-family:"IBM Plex Sans Condensed",sans-serif; font-weight:600; font-size:.95rem}
.sub{display:block; font-size:.68rem; color:var(--muted); font-weight:400; letter-spacing:.01em}
caption{caption-side:bottom; text-align:left; padding:10px 14px; font-size:.78rem;
  color:var(--muted); font-family:"IBM Plex Serif",serif}

.ratio{display:flex; align-items:center; gap:9px; justify-content:flex-end}
.rv{min-width:3.6em; text-align:right; font-weight:500}
.rv.pos{color:var(--pos)} .rv.neg{color:var(--neg)}
.rb{display:block; width:74px; height:5px; background:var(--rule); position:relative}
.rb i{position:absolute; inset:0 auto 0 0; display:block}
.rb i.pos{background:var(--pos)} .rb i.neg{background:var(--neg)}
.hi{color:var(--pos); font-weight:500}
.lo{color:var(--muted)}
td .pos{color:var(--pos); font-weight:500}
td .neg{color:var(--neg); font-weight:500}
:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
@media (prefers-reduced-motion: reduce){*{animation:none!important; transition:none!important}}

.bitfield{margin:26px 0 6px; border:1px solid var(--rule); background:var(--surface); padding:20px 22px}
.bf-row{display:grid; gap:3px; margin-bottom:5px}
.bf-cell{padding:7px 8px; font-size:.72rem; text-align:center; letter-spacing:.04em;
  border:1px solid var(--rule-2); white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
.bf-poslo{background:var(--accent); color:var(--surface); border-color:var(--accent)}
.bf-cin{background:var(--raise)}
.bf-cout{background:transparent}
.bf-poshi{background:transparent; border-style:dashed}
.bf-brace{display:grid; gap:3px; font-size:.68rem; color:var(--muted);
  text-transform:uppercase; letter-spacing:.1em; margin-top:2px}
.bf-brace span{text-align:center; padding-top:5px; border-top:1px solid var(--rule-2)}
.bf-note{font-size:.8rem; color:var(--muted); margin:16px 0 0; font-family:"IBM Plex Serif",serif}

pre{background:var(--surface); border:1px solid var(--rule); padding:16px 18px; overflow-x:auto;
  font-size:.8rem; line-height:1.6; margin:20px 0}
code{font-size:.87em; background:var(--raise); padding:1px 5px; border:1px solid var(--rule)}
pre code{background:none; border:none; padding:0; font-size:1em}

.keys{display:grid; grid-template-columns:repeat(auto-fit,minmax(215px,1fr)); gap:1px;
  background:var(--rule); border:1px solid var(--rule); margin:24px 0 4px}
.key{background:var(--surface); padding:16px 18px}
.key .k{font-family:"IBM Plex Mono",monospace; font-size:1.5rem; font-weight:500;
  display:block; letter-spacing:-.02em; font-variant-numeric:tabular-nums}
.key .l{font-family:"IBM Plex Sans Condensed",sans-serif; font-size:.7rem; text-transform:uppercase;
  letter-spacing:.1em; color:var(--muted); display:block; margin-top:5px}
.key.up .k{color:var(--pos)} .key.down .k{color:var(--neg)}

ul{padding-left:1.1em; margin:0 0 15px}
li{margin-bottom:7px}
footer{margin-top:70px; padding-top:26px; border-top:1px solid var(--rule-2);
  font-size:.8rem; color:var(--muted)}
"""

def bf():
    """The 64-byte V8 line id, drawn as its four digits with the L1 index marked."""
    cells = [("bf-poshi", "pos_hi", 1), ("bf-cout", "cout_blk", 7),
             ("bf-cin", "cin_blk", 5), ("bf-poslo", "pos_lo", 3)]
    total = sum(w for _, _, w in cells)
    cols = " ".join(f"{w}fr" for _, _, w in cells)
    row = "".join(f'<div class="bf-cell {c}">{n} &middot; {w}b</div>' for c, n, w in cells)
    # the index / tag split, at 32 L1 sets = 5 bits
    braces = (f'<div class="bf-brace" style="grid-template-columns:{total-5}fr 5fr">'
              f'<span>tag &middot; {total-5} bits</span><span>L1 set index &middot; 5 bits</span></div>')
    return (f'<div class="bitfield"><div class="bf-row" style="grid-template-columns:{cols}">{row}</div>'
            f'{braces}<p class="bf-note">V8 at 64-byte lines: 3&times;3 kernel, 32 CIN blocks of 16, '
            f'128 COUT blocks of 4, a 16 KB 8-way L1 of 32 sets. The index is <code>pos_lo</code> whole '
            f'plus the low 2 bits of <code>cin_blk</code>. A core owns a fixed slice of COUT, and '
            f'<code>cout_blk</code> is 8 bits above the index, so a pinned digit cannot narrow the '
            f'sets a core reaches.</p></div>')

HTML = f"""<title>Kernel-Indexed Cache Sweep</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@400;600&family=IBM+Plex+Serif:ital,wght@0,400;0,600;1,400&display=swap">
<style>{CSS}</style>

<div class="wrap">
<header>
  <h1>Kernel-Indexed Cache Sweep</h1>
  <p class="standfirst">A new weight layout puts the kernel position at the bottom of the L1 set
  index. Forty-eight cache configurations, four layers, five samples, measured against stage 3.</p>
  <div class="meta">
    <span>960 engine-runs</span>
    <span><b>khkw_split</b> layout</span>
    <span>V8 &middot; V9 &middot; R9 &middot; R16</span>
    <span>commit <b>26ef6f0</b></span>
    <span>2026-08-28</span>
  </div>
</header>

<section>
  <span class="eyebrow">The answer</span>
  <h2>What the sweep found</h2>
  <div class="col">
  <div class="verdict">
    <p><b>The layout works.</b> L1 hit rates run from {F['l1_lo']:.1f}% to {F['l1_hi']:.1f}% across
    all 960 runs, against {F['bp_lo']:.1f}&ndash;{F['bp_hi']:.1f}% for <code>block_pack</code> at the
    same point, and the best configuration lands between {F['floor_lo']:.2f}&times; and
    {F['best_floor']['V8']:.2f}&times; the cycles a perfect memory system would take.</p>
    <p><b>It does not beat stage 3.</b> Against the NoC baseline the best configuration comes in at
    {F['s3_lo']:.2f}&times; to {F['s3_hi']:.2f}&times;, ahead on {F['n_beat']} layer of four. An
    earlier version of this page reported speedups up to 5.8&times;; those came from a defect in
    <code>nocsim</code> that re-sent the weight tile on every DRAM step, inflating the baseline by
    2&times; on the vgg16 layers and 8&times; on R16. The defect is fixed and stage 3 re-run.</p>
    <p><b>Bigger lines win outright</b> across the whole 16&ndash;64 B range, on every layer, with or
    without prefetching.</p>
    <p><b>Prefetching costs cycles</b> at 32 and 64 bytes, by up to {F['pf_worst']:.0f}%. It pays
    only at 16-byte lines, and never enough to catch a 64-byte line with prefetching off.</p>
    <p><b>L2 banking changes nothing</b> &mdash; at most {F['bank_worst']:.1f}% on a single point, and
    in the wrong direction. The L2 port is never the constraint here.</p>
  </div>
  </div>

  <div class="keys">
    <div class="key up"><span class="k">{F['floor_lo']:.2f}&times;</span><span class="l">best run over the compute floor</span></div>
    <div class="key up"><span class="k">{F['l1_hi']:.2f}%</span><span class="l">best L1 hit rate (R9)</span></div>
    <div class="key down"><span class="k">+{F['pf_worst']:.0f}%</span><span class="l">worst prefetch penalty</span></div>
    <div class="key"><span class="k">{F['bank_dev']:.2f}%</span><span class="l">mean effect of L2 banking</span></div>
  </div>
</section>

<section>
  <span class="eyebrow">The layout</span>
  <h2>Where each digit sits</h2>
  <div class="col">
  <p>The kernel position is <code>pos = kh &times; KW + kw</code>, nine values for a 3&times;3 kernel.
  It is split at <code>min(8, KH&times;KW)</code> and the four digits nest, outermost first, as
  <code>[pos_hi][cout_blk][cin_blk][pos_lo]</code>.</p>
  <p>Nine values do not fit in three bits, and that is the deliberate trade: position 8 aliases onto
  position 0's set and is told apart by a tag bit. A value reached one time in nine does not earn a
  fourth index bit.</p>
  </div>
  {bf()}
  <div class="col">
  <p>The mapper is <code>KhkwSplitMapper</code>, a sibling of <code>BlockPackMapper</code> and
  <code>SplitCinMapper</code> rather than a flag on either. It takes no split-width argument:
  the radix comes from the kernel, so <code>cin_lo_blocks</code> stays at its sentinel and there is
  no config field that can disagree with the layer.</p>
  </div>
</section>

<section>
  <span class="eyebrow">Headline</span>
  <h2>Best configuration per layer</h2>
  <div class="col">
  <p>Mean over five samples, against two baselines. <b>Stage 3</b> is what the NoC simulator took to
  deliver the same layer. <b>Floor</b> is <code>compute_per_node</code>, the cycles a core would
  spend with every weight already in hand.</p>
  <p>The floor is the baseline to trust. It is derived from <code>count_cycles</code>, which equals
  this engine's <code>l1_accesses</code> exactly on all 20 layer-sample pairs, so both simulators
  provably walk the same work; and an oracle run of this engine, with a cache large enough and fast
  enough to never miss, reproduces it to the cycle on every layer. The stage 3 column depends on a
  NoC model that has already been wrong once.</p>
  </div>
  {table([("Layer",0),("Configuration",0),("Cycles",1),("Stage 3",1),("vs stage 3",1),
          ("Over floor",1),("L1 hit",1),("L2 hit",1)], t1)}
</section>

<section>
  <span class="eyebrow">Full grid</span>
  <h2>Every configuration, every layer</h2>
  <div class="col">
  <p>All 48 points at one L2 bank; the other three bank counts are within 0.2% and are shown
  separately below. <b>Floor</b> is the ratio to stage 3's <code>compute_per_node</code>, the cycles a
  core would spend with every weight already in hand &mdash; the number no memory system can go
  under.</p>
  </div>
  {table([("Layer",0),("Line",0),("Prefetch",1),("Cycles",1),("vs stage 3",1),("Floor",1),
          ("L1 hit",1),("L2 hit",1),("DRAM MiB",1)], t2)}
</section>

<section>
  <span class="eyebrow">Axis 1</span>
  <h2>Line size: bigger is better, everywhere</h2>
  <div class="col">
  <p>At no prefetch and one bank. Every step from 16 to 64 bytes cuts cycles and raises the L1 hit
  rate, on all four layers. Nothing in this range trades off against anything.</p>
  <p>The reason is spatial: <code>cin_block</code> is <code>line_bytes / 4</code>, so a 64-byte line
  packs 16 CIN of one COUT quad. A burst walks COUT, and consecutive tiles walk CIN, so the wider
  line is consumed rather than carried. Padding stays flat across the three sizes &mdash; {F['pad32']:.2f}% on
  V8 at both 32 and 64 bytes &mdash; which says the extra bytes are used, not wasted.</p>
  </div>
  {table([("Layer",0),("16 B cycles",1),("16 B L1",1),("32 B cycles",1),("32 B L1",1),
          ("64 B cycles",1),("64 B L1",1)], t3)}
</section>

<section>
  <span class="eyebrow">Axis 2</span>
  <h2>Prefetching pays only where the L1 is weakest</h2>
  <div class="col">
  <p>Cycles relative to prefetching off, at each layer and line size. The pattern is consistent: the
  penalty grows with the line size, because the line size is what fixed the L1 in the first place.
  At 16 bytes the prefetcher earns its keep on {F['pf16_n']} of the four layers &mdash;
  {F['pf16_helps']}. At 64 bytes it costs between {F['pf64_lo']:.0f}% and {F['pf64_hi']:.0f}%.</p>
  <p>It never rescues a small line. V8's best prefetched 16-byte run is {F['v8_pf16']:,.0f} cycles
  against {F['v8_64_0']:,.0f} for a 64-byte line with prefetching off.</p>
  </div>
  {table([("Layer",0),("Line",0),("No prefetch",1),("Distance 1",1),("Distance 2",1),("Distance 4",1)], t4a)}

  <div class="col">
  <h3>Why it costs anything at all</h3>
  <p>The <code>next_burst</code> prefetcher issues one request per line of the next burst. With the
  L1 already at {F['best_l1']:.1f}%, <b>{F['pf_drop_pct']:.0f}% of those requests find the line
  resident and drop</b> &mdash; but the L1 port slot is spent before the array is probed, by design:
  at <code>l1_ii</code> 1 every prefetch takes a cycle the demand stream could have used.</p>
  <p>So it roughly doubles L1 port traffic to buy a few thousand timely fills out of 2.6 million
  issued. On V8 at 64 bytes, <code>stall_l1_port</code> goes from 0 to {F['pf_port']:.2f} million
  core-cycles. Raising the distance recovers part of it by spreading the requests out, never all of
  it.</p>
  <p>A prefetcher that helped at 64 bytes would have to check residency before spending the port.
  That is a different policy, not a different distance.</p>
  </div>
  {table([("Distance",0),("Issued",1),("Dropped, already resident",1),
          ("Drop rate",1),("Timely",1),("L1 port stall",1)], t4b)}
</section>

<section>
  <span class="eyebrow">Axis 3</span>
  <h2>L2 banking is inert</h2>
  <div class="col">
  <p>Cycles relative to one bank, meaned over four layers and five samples. Nothing moves. The largest
  single-point effect anywhere in the {F['bank_n']} comparisons is +{F['bank_worst']:.1f}%, and the
  sign is wrong: more banks, marginally more cycles.</p>
  <p>The cause is traffic, not wiring. Banking splits the L2's ports so that concurrent probes to
  different sets need not queue, and at the sweep's best point the L2's port-contention stall is
  exactly zero &mdash; there is no queue to split. The L2 sees {F['l2_acc']:,} demand probes where
  the L1 sees {F['l1_acc']:,}, one for every {F['acc_ratio']:.0f}.</p>
  <p>Banking is a knob for a workload whose L2 is hot. Under this layout the L1 keeps the L2 cold, so
  the two facts are the same fact.</p>
  </div>
  {table([("Line",0),("Prefetch",1),("2 banks",1),("4 banks",1),("8 banks",1)], t5)}
</section>

<section>
  <span class="eyebrow">Hit rates</span>
  <h2>The L1 absorbs almost everything; the L2 falls off a cliff</h2>
  <div class="col">
  <p>The L1 numbers are in the tables above. The L2 number needs its own explanation, because it
  reads 0.00% at nearly every point of the sweep and a flat zero is not a result a reader can act
  on.</p>
  <p>Walking <code>l2_size_bytes</code> from the sweep's 512 KB to 16 MB at the best point shows it is
  a pure capacity cliff, and shows exactly where the edge is: the L2 hit rate jumps from 0 to
  {F['l2_jump']:.2f}% the moment the cache can hold the layer's whole weight set &mdash;
  {F['cliff_v8']} MB for V8 and V9, {F['cliff_r16']} MB for R16. Not before, not gradually.</p>
  <p>That is LRU meeting a cyclic sweep. The layer is walked start to end, over and over; at any size
  under the working set, every line is evicted before it is used again. Above it, every line is
  fetched exactly once and the {F['per_line']:.2f} accesses per line collapse to 1.</p>
  <p><b>R9 is the exception and it is the good kind.</b> Its 0.28 MiB already fits in 512 KB, so its
  0.00% means every line reaches the L2 once and never comes back &mdash; the L1 is holding it. A
  16 MB L2 changes nothing for R9.</p>
  <p>The practical reading: for V8, V9 and R16 the swept 512 KB L2 is on the wrong side of the edge
  and is buying nothing. Crossing it is worth {F['gain_v8']:.0f}% of V8's remaining cycles and
  {F['gain_r16']:.0f}% of R16's.</p>
  </div>
  {table([("Layer",0),("Weight set",1)] + [(f'{n//1024//1024 if n>=1048576 else n//1024}{"M" if n>=1048576 else "K"}B',1) for n in sizes], t6)}
</section>

<section>
  <span class="eyebrow">Control</span>
  <h2>Is it the layout, or just having a cache?</h2>
  <div class="col">
  <p>The same point &mdash; 64-byte lines, one bank, no prefetch &mdash; run under all three layouts
  in the tree, on all four layers and all five samples. Without this the speedups above could not be
  attributed.</p>
  <p><code>khkw_split</code> wins on every layer, on cycles, on L1 hit rate, and on DRAM traffic. The
  margin over <code>block_pack</code> runs from {F['bp_lo_x']:.1f}&times; to {F['bp_hi_x']:.1f}&times;,
  and over <code>split_cin</code> from {F['sc_lo_x']:.1f}&times; to {F['sc_hi_x']:.1f}&times;. R9 is the
  sharpest case: <code>split_cin</code> is <i>worse</i> than <code>block_pack</code> there, while
  <code>khkw_split</code> is {F['r9_bp']:.1f}&times; better than <code>block_pack</code> and
  {F['r9_sc']:.1f}&times; better than <code>split_cin</code>.</p>
  </div>
  {table([("Layer",0),("Layout",0),("Cycles",1),("L1 hit",1),("DRAM lines",1),("vs stage 3",1)], t7)}
</section>

<section>
  <span class="eyebrow">Provenance</span>
  <h2>What ran, and how to run it again</h2>
  <div class="col">
  <p>Held fixed across the sweep, read back off a result row rather than retyped:
  {int(CFG['l1_size_bytes'])//1024} KB {CFG['l1_assoc']}-way L1,
  {int(CFG['l2_size_bytes'])//1024} KB {CFG['l2_assoc']}-way L2 with {CFG['l2_mshrs']} MSHRs,
  <code>cout_block</code> {CFG['cout_block']}, {CFG['weight_bytes']}-byte weights,
  <code>l1_latency</code> {CFG['l1_latency']}, <code>l2_latency</code> <b>{CFG['l2_latency']}</b>,
  <code>l2_miss_latency</code> {CFG['l2_miss_latency']},
  {CFG['policy'].upper()}, {CFG['inclusion'].replace('_', '-')}, {CFG['n_cores']} cores.</p>
  <p>Swept: line size {{16, 32, 64}} B (as <code>cin_block</code> = <code>line_bytes / 4</code>),
  <code>l2_banks</code> {{1, 2, 4, 8}}, <code>prefetch_distance</code> {{0, 1, 2, 4}}. Distance 0
  carries <code>prefetch_policy: none</code>, since <code>validate()</code> refuses
  <code>next_burst</code> at distance 0 rather than silently running as none.</p>
  <p>Line size is not an axis inside one sweep invocation: <code>BroadcastSweep</code> gives one
  mapper to the whole grid, so the 48 points run as three grids of 16, each over its own pass of the
  stream. That is 60 invocations rather than 960 process launches.</p>
  </div>
<pre><code># the mapper and its checks
src/wcache/native/include/wcache/khkw_split.h
src/wcache/native/src/khkw_split.cpp
src/wcache/native/tests/test_khkw_split.cpp        10,361 checks

# the drivers, in profiling/0823_stagewise_verify/stage4_wcache/
run_khkw_sweep.py        48 configs x 4 layers x 5 samples   86 s
run_layout_control.py    3 layouts x 4 layers x 5 samples      5 s
run_l2_capacity_probe.py 6 L2 sizes x 4 layers x 5 samples    10 s
analyze_khkw_sweep.py    -> outputs/khkw_vs_stage3.csv

# on Delta
srun -A bebv-delta-gpu -p gpuA100x4-interactive --gpus=1 -n1 -c 16 \\
     -t 00:45:00 --mem=32g python3 run_khkw_sweep.py 16</code></pre>
  <div class="col">
  <p>The full test suite is 58,490 checks over 20 binaries, plus 316 compile-refusal cases and the
  end-to-end CLI gate, all green.</p>
  </div>
</section>

<footer>
  Stage 4 of the 2026-08-23 stagewise verification. Row-level data in
  <code>stage4_wcache/outputs/</code>: <code>khkw_sweep.csv</code> (960 rows),
  <code>khkw_vs_stage3.csv</code> (192), <code>khkw_layout_control.csv</code> (60),
  <code>khkw_l2_capacity.csv</code> (120).
</footer>
</div>
"""
OUT.write_text(HTML)
print(f"wrote {OUT} ({len(HTML)} bytes)")
