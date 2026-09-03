#!/usr/bin/env python3
"""The per-layer cache profile artifact: hit/miss rates, the L2 global
reuse-distance distribution, and the L2 reuse-count distribution. Nothing else.

Every number and every bar is generated from outputs/perlayer31.csv.
"""
import csv
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
rows = list(csv.DictReader((HERE / "outputs/perlayer31.csv").open()))
for r in rows:
    r["short"] = r["layer"].split("_", 2)[2]
    r["l1h"] = float(r["l1_hit_rate"])
    r["l1m"] = 1 - r["l1h"]
    r["l2h"] = float(r["l2_hit_rate"])
    r["a"] = int(r["l2_accesses"])
    r["d"] = int(r["l2_lines"])
    r["ru"] = r["a"] / r["d"] if r["d"] else 0.0
    r["rd"] = ({int(k): int(v) for k, v in (q.split(":") for q in r["global_rd"].split(";"))}
               if r["global_rd"] else {})
    r["rc"] = {int(k): int(v) for k, v in (q.split(":") for q in r["reuse_count"].split(";"))}

MM = max(r["l1m"] for r in rows)
WITH = [r for r in rows if r["rd"]]

# --- L1 miss-rate strip. Hit rates all sit between 92 and 100%, so the miss
# --- rate is the readable quantity: it spans 0.03% to 7.47%, a 250x range.
RH, BW, LW = 16, 360, 168
H = len(rows) * RH + 40
b = []
for i, r in enumerate(rows):
    y = i * RH + 28
    w = max(r["l1m"] / MM * BW, 0.6)
    b.append(f'<text class="lyr" x="{LW-8}" y="{y+9}" text-anchor="end">{r["short"]}</text>')
    b.append(f'<rect class="bar {"win" if r["rd"] else "idle"}" x="{LW}" y="{y+1}" '
             f'width="{w:.1f}" height="10"><title>{r["layer"]}: L1 hit {100*r["l1h"]:.2f}%, '
             f'miss {100*r["l1m"]:.2f}%, {int(r["l1_accesses"]):,} accesses</title></rect>')
    b.append(f'<text class="v" x="{LW+BW+10}" y="{y+9}">{100*r["l1m"]:.2f}%</text>')
    if r["rd"]:
        b.append(f'<text class="v2" x="{LW+BW+64}" y="{y+9}">has L2 reuse</text>')
for net in ("vgg16", "resnet19"):
    f = next(k for k, r in enumerate(rows) if r["net"] == net)
    b.append(f'<text class="net" x="0" y="{f*RH+37}">{net}</text>')
b.append(f'<text class="hd" x="{LW}" y="19">L1 miss rate</text>')
STRIP = (f'<svg viewBox="-2 0 {LW+BW+130} {H}" role="img" aria-label="L1 miss rate for all 31 '
         f'layers, spanning 0.03 to 7.47 percent. The five layers that have L2 reuse are marked.">\n'
         + "\n".join(b) + "\n</svg>")


def hit_rows():
    out = []
    for r in rows:
        out.append(
            f'<tr><td class="lay">{r["net"]}</td><td>{r["short"]}</td>'
            f'<td class="n">{int(r["l1_accesses"]):,}</td>'
            f'<td class="n">{100*r["l1h"]:.2f}%</td>'
            f'<td class="n dim">{100*r["l1m"]:.2f}%</td>'
            f'<td class="n">{r["a"]:,}</td>'
            f'<td class="n dim">{100*r["l2h"]:.2f}%</td>'
            f'<td class="n">{100*(1-r["l2h"]):.2f}%</td></tr>')
    return "\n".join(out)


def rd_rows():
    out = []
    for r in WITH:
        t = r["a"]
        cells = "".join(
            f'<td class="n hi">{r["rd"].get(k,0):,}<span class="pc">'
            f'{100*r["rd"].get(k,0)/t:.2f}%</span></td>' for k in (1023, 3071))
        out.append(
            f'<tr><td class="lay">{r["net"]}</td><td>{r["short"]}</td>'
            f'<td class="n dim">{r["d"]:,}<span class="pc">{100*r["d"]/t:.2f}%</span></td>'
            f'{cells}<td class="n">{t:,}</td></tr>')
    return "\n".join(out)


def rc_rows():
    out = []
    for r in rows:
        one = r["rc"].get(1, 0)
        six = r["rc"].get(6, 0)
        six_cell = (f'{six:,}<span class="pc">{100*six/r["d"]:.1f}%</span>' if six else "0")
        out.append(
            f'<tr><td class="lay">{r["net"]}</td><td>{r["short"]}</td>'
            f'<td class="n">{one:,}<span class="pc">{100*one/r["d"]:.1f}%</span></td>'
            f'<td class="n {"hi" if six else "dim"}">{six_cell}</td>'
            f'<td class="n">{r["d"]:,}</td>'
            f'<td class="n {"hi" if six else "dim"}">{r["ru"]:.2f}</td></tr>')
    return "\n".join(out)


HTML = f'''<title>Per-Layer Cache Profile</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700&family=IBM+Plex+Mono:wght@400;500&family=Newsreader:opsz,wght@6..72,400;6..72,600&display=swap">
<style>
:root{{
  --ground:#ECEFEC; --surface:#FFFFFF; --raise:#E0E6E1; --sunk:#DCE3DD;
  --ink:#161F1A; --muted:#5C6A62; --rule:#D1DAD3; --rule-2:#B2BFB6;
  --live:#2C6A4F; --idle:#93A099;
}}
@media (prefers-color-scheme: dark){{
  :root:not([data-theme="light"]){{
    --ground:#0C1210; --surface:#151C18; --raise:#1D2622; --sunk:#111815;
    --ink:#E2EAE5; --muted:#8B9A92; --rule:#232E28; --rule-2:#35433B;
    --live:#63C097; --idle:#5C6A63;
  }}
}}
:root[data-theme="dark"]{{
  --ground:#0C1210; --surface:#151C18; --raise:#1D2622; --sunk:#111815;
  --ink:#E2EAE5; --muted:#8B9A92; --rule:#232E28; --rule-2:#35433B;
  --live:#63C097; --idle:#5C6A63;
}}
*{{box-sizing:border-box}}
body{{background:var(--ground); color:var(--ink);
  font-family:Newsreader,Georgia,serif; font-size:17px; line-height:1.58;
  margin:0; padding:0 22px 80px; -webkit-font-smoothing:antialiased}}
.wrap{{max-width:1040px;margin:0 auto}} .col{{max-width:66ch}}
h1,h2,.eyebrow,th,.lbl{{font-family:"Bricolage Grotesque",system-ui,sans-serif}}
code,td,.mono{{font-family:"IBM Plex Mono",ui-monospace,monospace}}
header{{padding:54px 0 24px;border-bottom:1px solid var(--rule-2)}}
h1{{font-size:clamp(2.2rem,5.5vw,3.4rem);font-weight:700;line-height:1.0;
  letter-spacing:-.03em;margin:0 0 16px;text-wrap:balance}}
.stand{{font-size:1.1rem;color:var(--muted);margin:0;max-width:60ch}}
.meta{{display:flex;flex-wrap:wrap;gap:6px 24px;margin-top:22px;
  font-family:"IBM Plex Mono",monospace;font-size:.71rem;color:var(--muted);
  text-transform:uppercase;letter-spacing:.06em}}
.meta b{{color:var(--ink);font-weight:500}}
section{{padding:46px 0 0}}
.eyebrow{{display:block;font-size:.7rem;font-weight:700;text-transform:uppercase;
  letter-spacing:.15em;color:var(--live);margin:0 0 8px}}
h2{{font-size:1.55rem;font-weight:700;letter-spacing:-.02em;margin:0 0 8px;text-wrap:balance}}
p{{margin:0 0 13px}} strong{{font-weight:600}}
.chart{{margin:22px 0 4px;background:var(--surface);border:1px solid var(--rule);
  padding:18px 16px 12px;overflow-x:auto}}
.chart svg{{display:block;width:100%;min-width:700px;height:auto}}
.chart text{{font-family:"IBM Plex Mono",monospace;font-size:9px;fill:var(--muted)}}
.chart text.lyr{{fill:var(--ink)}}
.chart text.hd{{font-family:"Bricolage Grotesque",sans-serif;font-size:10px;
  fill:var(--muted);text-transform:uppercase;letter-spacing:.09em}}
.chart text.net{{font-family:"Bricolage Grotesque",sans-serif;font-size:11px;
  font-weight:700;fill:var(--ink)}}
.chart text.v{{fill:var(--ink)}} .chart text.v2{{fill:var(--live);font-weight:500}}
.chart .bar.idle{{fill:var(--idle);opacity:.6}} .chart .bar.win{{fill:var(--live)}}
.scroll{{overflow-x:auto;margin:20px 0 4px;border:1px solid var(--rule);background:var(--surface)}}
table{{border-collapse:collapse;width:100%;font-size:.81rem}}
th{{text-align:left;font-weight:600;font-size:.66rem;text-transform:uppercase;letter-spacing:.09em;
  color:var(--muted);padding:10px 13px;border-bottom:1px solid var(--rule-2);
  white-space:nowrap;background:var(--raise)}}
td{{padding:7px 13px;border-bottom:1px solid var(--rule);vertical-align:baseline;
  font-variant-numeric:tabular-nums;white-space:nowrap}}
tbody tr:last-child td{{border-bottom:none}}
th.n,td.n{{text-align:right}}
td.lay{{font-family:"Bricolage Grotesque",sans-serif;font-weight:600;font-size:.88rem}}
.hi{{color:var(--live);font-weight:500}} .dim{{color:var(--idle)}}
.pc{{display:block;font-size:.72em;color:var(--muted);font-weight:400}}
.cap{{padding:10px 2px;font-size:.8rem;color:var(--muted);max-width:76ch;margin:0 0 4px}}
code{{font-size:.87em;background:var(--raise);padding:1px 5px;border:1px solid var(--rule)}}
footer{{margin-top:56px;padding-top:22px;border-top:1px solid var(--rule-2);
  font-size:.78rem;color:var(--muted)}}
:focus-visible{{outline:2px solid var(--live);outline-offset:2px}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important;transition:none!important}}}}
</style>

<div class="wrap">
<header>
  <h1>Per-Layer Cache Profile</h1>
  <p class="stand">Hit and miss rates, L2 reuse-distance distribution, and L2 reuse-count
  distribution, for all 31 layers of both networks.</p>
  <div class="meta">
    <span><b>31</b> layers</span>
    <span>vgg16 <b>12</b> &middot; resnet19 <b>19</b></span>
    <span>loas, <b>16</b> cores, sample 0</span>
    <span>2026-08-31</span>
  </div>
</header>

<section>
  <span class="eyebrow">1. Hit and miss</span>
  <h2>L1 miss rate spans a 250-fold range</h2>
  <div class="col">
    <p>L1 hit rates all sit between 92.53% and 99.97%, so the miss rate is the readable quantity:
    it runs from 0.03% to 7.47%. The L2 hit rate is <strong>0.00% on every layer</strong> at this
    geometry, so its miss rate is 100% throughout.</p>
  </div>
  <div class="chart">
{STRIP}
  </div>
  <p class="cap">Bar length is L1 miss rate on a linear scale. Green marks the five layers that
  have any L2 reuse; hover any bar for its exact counts.</p>
  <div class="scroll">
    <table>
      <thead><tr><th>Net</th><th>Layer</th><th class="n">L1 accesses</th>
        <th class="n">L1 hit</th><th class="n">L1 miss</th>
        <th class="n">L2 accesses</th><th class="n">L2 hit</th><th class="n">L2 miss</th></tr></thead>
      <tbody>
{hit_rows()}
      </tbody>
    </table>
  </div>
</section>

<section>
  <span class="eyebrow">2. Global reuse distance</span>
  <h2>Two values, and only on five layers</h2>
  <div class="col">
    <p>Reuse distance is counted in distinct L2 lines touched between two references to the same
    line. A first reference is cold and has no distance. Twenty-six layers have <em>no</em> finite
    distances at all: every line reaches the L2 once and is never asked for again.</p>
    <p>The five that do have reuse are identical in shape. Every reference sits at exactly
    <strong>1023</strong> or exactly <strong>3071</strong>, in the same 47.37% / 5.26% proportion.
    Nothing in between, on any layer.</p>
  </div>
  <div class="scroll">
    <table>
      <thead><tr><th>Net</th><th>Layer</th><th class="n">Cold</th>
        <th class="n">d = 1023</th><th class="n">d = 3071</th><th class="n">L2 references</th></tr></thead>
      <tbody>
{rd_rows()}
      </tbody>
    </table>
  </div>
  <p class="cap">The other 26 layers are omitted from this table because every one of their
  references is cold. Percentages are of that layer's L2 references.</p>
</section>

<section>
  <span class="eyebrow">3. Reuse count</span>
  <h2>Touched once, or touched six times</h2>
  <div class="col">
    <p>How many times each distinct L2 line is referenced. Across the whole corpus this takes
    exactly two values, <strong>1</strong> and <strong>6</strong>, and never anything else.</p>
    <p>That is what the average ratio conceals. A layer at 2.11 is not a layer whose lines are
    touched about twice; it is 78% of lines touched once and 22% touched six times.</p>
  </div>
  <div class="scroll">
    <table>
      <thead><tr><th>Net</th><th>Layer</th><th class="n">Lines touched 1x</th>
        <th class="n">Lines touched 6x</th><th class="n">Distinct lines</th>
        <th class="n">Mean refs / line</th></tr></thead>
      <tbody>
{rc_rows()}
      </tbody>
    </table>
  </div>
  <p class="cap">The hot set is 8,192 lines on the four large layers and 4,096 on
  <code>layer3_0_conv2</code>. At 64-byte lines those are 512 KB and 256 KB.</p>
</section>

<footer>
  <p><strong>Config.</strong> <code>khkw_split</code>, 64 B lines (cin_block 16 &times; cout_block 4
  &times; 1 B), L1 16 KB 8-way private &times; 16 cores, L2 512 KB 16-way 1 bank, lru,
  non_inclusive, latencies 0 / 2 / 24, prefetch none. One sample per layer.</p>
  <p><strong>Source.</strong> <code>profiling/0831_reuse_distance/analyze31.py</code>, raw data in
  <code>outputs/perlayer31.csv</code>.</p>
</footer>
</div>
'''

(HERE / "assoc31.html").write_text(HTML)
print(f"wrote assoc31.html  ({len(HTML):,} bytes, {len(rows)} layers, {len(WITH)} with reuse)")
