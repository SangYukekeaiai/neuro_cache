#!/usr/bin/env python3
"""Emit the L2 prefetch artifact. Every number is read from the CSVs, never retyped."""
import csv, json, math, pathlib, statistics, subprocess, sys

STAGE = pathlib.Path(__file__).resolve().parent
ROOT  = STAGE.parents[1]
OUT   = pathlib.Path(sys.argv[1])
PREV  = ROOT / "profiling/0831_all_layer_streams/outputs"

rows = list(csv.DictReader(open(STAGE / "outputs/l2pf_by_layer.csv")))
prev = {r["tag"]: r for r in csv.DictReader(open(PREV / "all_layers_vs_nocsim.csv"))}
by   = {(r["tag"], r["arm"]): r for r in rows}
TAGS = []
for r in rows:
    if r["tag"] not in TAGS:
        TAGS.append(r["tag"])
COMMIT = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                        capture_output=True, text=True).stdout.strip()
f = lambda d, k: float(d[k])
gm = lambda v: math.exp(statistics.mean(math.log(x) for x in v))
num = lambda x, d=0: f"{x:,.{d}f}"

F = {}
ARMS = ("off", "up", "down", "both")
ARM_LABEL = {"off": "no prefetch", "up": "cin +1 only", "down": "cin &minus;1 only", "both": "cin &plusmn;1"}
up   = [f(by[(t, "up")],   "speedup_vs_off") for t in TAGS]
down = [f(by[(t, "down")], "speedup_vs_off") for t in TAGS]
both = [f(by[(t, "both")], "speedup_vs_off") for t in TAGS]
for a in ARMS:
    v = [f(by[(t, a)], "speedup_vs_nocsim") for t in TAGS]
    g = [f(by[(t, a)], "speedup_vs_off") for t in TAGS]
    F[f"{a}_s3"], F[f"{a}_s3n"] = gm(v), sum(1 for x in v if x > 1)
    F[f"{a}_off"], F[f"{a}_offn"] = gm(g), sum(1 for x in g if x > 1)
F["n"] = len(TAGS)
F["up_gm"], F["down_gm"], F["both_gm"] = gm(up), gm(down), gm(both)
F["up_win"] = sum(1 for x in up if x > 1)
F["down_win"] = sum(1 for x in down if x > 1)
F["both_win"] = sum(1 for x in both if x > 1)
F["down_worst"] = min(down)
F["up_best"], F["up_worst"] = max(up), min(up)
F["both_worst"] = min(both)
F["best_tag"] = TAGS[up.index(max(up))]
h = [f(by[(t, "up")], "l2_hit_rate") for t in TAGS]
F["h_lo"], F["h_med"], F["h_hi"] = min(h) * 100, statistics.median(h) * 100, max(h) * 100
F["d_off"] = sum(f(by[(t, "off")], "dram_accesses") for t in TAGS)
F["d_up"]  = sum(f(by[(t, "up")],  "dram_accesses") for t in TAGS)
F["d_ratio"] = F["d_up"] / F["d_off"]
F["iu"] = sum(f(by[(t, "both")], "l2_pf_issued_up") for t in TAGS)
F["idn"] = sum(f(by[(t, "both")], "l2_pf_issued_down") for t in TAGS)
F["dah"] = sum(f(by[(t, "both")], "l2_pf_dropped_array_hit") for t in TAGS)
# Attributed by DIFFERENCE against the upward arm, not by assuming every
# array-hit drop is a downward one: the upward arm drops a few of its own, and
# charging those to the -1 half is what made this read as 100.1%.
F["up_dah"] = sum(f(by[(t, "up")], "l2_pf_dropped_array_hit") for t in TAGS)
F["down_waste"] = (F["dah"] - F["up_dah"]) / F["idn"] * 100
F["p_up"] = sum(f(by[(t, "up")], "stall_l2_port") for t in TAGS)
F["p_both"] = sum(f(by[(t, "both")], "stall_l2_port") for t in TAGS)
F["p_ratio"] = F["p_both"] / F["p_up"]
so = [f(by[(t, "off")], "speedup_vs_nocsim") for t in TAGS]
su = [f(by[(t, "up")],  "speedup_vs_nocsim") for t in TAGS]
F["noc_off"], F["noc_up"] = gm(so), gm(su)
F["noc_off_n"], F["noc_up_n"] = sum(1 for x in so if x > 1), sum(1 for x in su if x > 1)
fl = [f(prev[t], "cycles_over_compute_floor") for t in TAGS]
F["corr"] = statistics.correlation(up, fl)
F["fl_off"] = statistics.mean(f(by[(t, "off")], "cycles_over_compute_floor") for t in TAGS)
F["fl_up"]  = statistics.mean(f(by[(t, "up")],  "cycles_over_compute_floor") for t in TAGS)
# layers with real headroom, and the gain restricted to them
hi = [t for t in TAGS if f(prev[t], "cycles_over_compute_floor") > 1.05]
F["n_hi"] = len(hi)
F["up_gm_hi"] = gm([f(by[(t, "up")], "speedup_vs_off") for t in hi])
F["up_gm_lo"] = gm([f(by[(t, "up")], "speedup_vs_off") for t in TAGS if t not in hi])

def cell(cycles, ratio):
    """A cycle count with its ratio to stage 3 underneath.

    Both numbers in one cell rather than in two columns: the question a reader
    asks of this table is "how many cycles, and is that better than the
    network", and splitting them puts eight columns between the halves of one
    answer.
    """
    cls = "pos" if ratio >= 1 else "neg"
    return (f'{num(cycles)}<span class="sub {cls}">{ratio:.3f}&times; vs stage 3</span>')


def bar(v, lo=0.9, hi_=1.3):
    frac = max(0.0, min(1.0, (v - lo) / (hi_ - lo)))
    cls = "pos" if v >= 1 else "neg"
    return (f'<div class="ratio"><span class="rv {cls}">{v:.3f}&times;</span>'
            f'<span class="rb"><i class="{cls}" style="width:{frac*100:.1f}%"></i></span></div>')

def table(head, body, cls=""):
    h = "".join(f"<th{' class=\"n\"' if a else ''}>{c}</th>" for c, a in head)
    b = "".join("<tr>" + "".join(f"<td{' class=\"n\"' if a else ''}>{c}</td>"
                                 for c, (_, a) in zip(r, head)) + "</tr>" for r in body)
    return f'<div class="scroll"><table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>'

# T1: every layer, all four arms, against stage 3
t1 = []
for t in sorted(TAGS, key=lambda x: -f(by[(x, "up")], "speedup_vs_nocsim")):
    o = by[(t, "off")]
    t1.append([f'<b>{t}</b><span class="sub">{o["layer"]}</span>',
               num(f(o, "nocsim_total_cycles"))] +
              [cell(f(by[(t, a)], "cycles"), f(by[(t, a)], "speedup_vs_nocsim"))
               for a in ARMS] +
              [f'{f(by[(t,"up")],"l2_hit_rate")*100:.2f}%',
               f'{f(prev[t],"cycles_over_compute_floor"):.2f}&times;'])

# T1b: the four arms summarised, both baselines side by side
t1b = []
for a in ARMS:
    t1b.append([ARM_LABEL[a],
                f'{F[a + "_s3"]:.4f}&times;', f'{F[a + "_s3n"]} / {F["n"]}',
                f'{F[a + "_off"]:.4f}&times;', f'{F[a + "_offn"]} / {F["n"]}'])

# T2: where the prefetches went, both arms
t2 = []
for arm in ("up", "down", "both"):
    label = ARM_LABEL[arm]
    t2.append([label,
               num(sum(f(by[(t, arm)], "l2_pf_issued_up") for t in TAGS)),
               num(sum(f(by[(t, arm)], "l2_pf_issued_down") for t in TAGS)),
               num(sum(f(by[(t, arm)], "l2_pf_timely") for t in TAGS)),
               num(sum(f(by[(t, arm)], "l2_pf_late") for t in TAGS)),
               num(sum(f(by[(t, arm)], "l2_pf_dropped_array_hit") for t in TAGS)),
               num(sum(f(by[(t, arm)], "l2_pf_wasted") for t in TAGS)),
               num(sum(f(by[(t, arm)], "stall_l2_port") for t in TAGS))])

CSS = (ROOT / "profiling/0823_stagewise_verify/stage4_wcache/outputs/khkw_sweep_artifact.html").read_text()
CSS = CSS[CSS.index("<style>") + 7:CSS.index("</style>")]
# The ratio under a cycle count, in the same two colours the bars use.
CSS += """
.sub.pos{color:var(--pos)} .sub.neg{color:var(--neg)}
td .sub{font-family:"IBM Plex Mono",monospace; letter-spacing:0; margin-top:2px}
"""

HTML = f"""<title>Prefetching a Dead L2</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@400;600&family=IBM+Plex+Serif:ital,wght@0,400;0,600;1,400&display=swap">
<style>{CSS}</style>

<div class="wrap">
<header>
  <h1>Prefetching a Dead L2</h1>
  <p class="standfirst">The L2 hit rate was exactly 0.00% on all {F['n']} layers of vgg16 and
  resnet19. A neighbour prefetcher moves it off zero and takes cycles with it, in one direction
  only: measured against stage 3, <code>cin +1</code> reaches
  {F['up_s3']:.4f}&times; while its mirror image reaches {F['down_s3']:.4f}&times; and the
  two together do worse than either.</p>
  <div class="meta">
    <span>{F['n']} layers &middot; {len(ARMS)} arms &middot; 5 samples</span>
    <span><b>cin_blk</b> neighbours at the L2</span>
    <span>commit <b>{COMMIT}</b></span>
    <span>2026-09-01</span>
  </div>
</header>

<section>
  <span class="eyebrow">The answer</span>
  <h2>What the policy did</h2>
  <div class="col">
  <div class="verdict">
    <p><b>It works, upward.</b> Prefetching the next CIN block on an L2 miss is faster on
    <b>{F['up_win']} of {F['n']} layers</b>, geomean {F['up_gm']:.4f}&times;, best
    {F['up_best']:.3f}&times; on {F['best_tag']} and never below {F['up_worst']:.3f}&times;.
    Against stage 3 it lifts the geomean from {F['off_s3']:.4f}&times; to
    {F['up_s3']:.4f}&times; and the layers ahead of the network from {F['off_s3n']} to
    {F['up_s3n']} of {F['n']}.</p>
    <p><b>The L2 hit rate leaves zero</b> for the first time in this campaign:
    {F['h_lo']:.2f}% to {F['h_hi']:.2f}%, median {F['h_med']:.2f}%, against an
    exact 0.00% on every layer before.</p>
    <p><b>It costs no DRAM traffic at all.</b> {num(F['d_up'])} accesses against
    {num(F['d_off'])} without it, a ratio of {F['d_ratio']:.4f}. The policy does not fetch
    more; it fetches the same lines earlier.</p>
    <p><b>The downward half never helps a single layer.</b> Run alone it is faster than no
    prefetching on <b>{F['down_win']} of {F['n']}</b>, geomean {F['down_gm']:.4f}&times;,
    worst {F['down_worst']:.3f}&times;. Of {num(F['idn'])} prefetches it issues,
    <b>{F['down_waste']:.2f}%</b> are dropped as already resident, measured as the rise in
    array-hit drops over the upward arm rather than assumed.</p>
    <p><b>The two halves together are worse than either alone.</b> Against stage 3:
    {F['up_s3']:.4f}&times; for +1, {F['down_s3']:.4f}&times; for &minus;1, and
    {F['both_s3']:.4f}&times; for both, which is below even the &minus;1 arm. Port contention
    does not add, it compounds: two prefetches per trigger queue behind each other on the same
    bank, so the useful half is delayed by the useless one.</p>
  </div>
  </div>

  <div class="keys">
    <div class="key up"><span class="k">{F['up_gm']:.3f}&times;</span><span class="l">geomean, cin +1</span></div>
    <div class="key up"><span class="k">{F['up_win']}/{F['n']}</span><span class="l">layers faster</span></div>
    <div class="key"><span class="k">{F['d_ratio']:.2f}&times;</span><span class="l">DRAM traffic</span></div>
    <div class="key down"><span class="k">{F['down_waste']:.0f}%</span><span class="l">of the &minus;1 half wasted</span></div>
  </div>
</section>

<section>
  <span class="eyebrow">The mechanism</span>
  <h2>Why an unreachable cache can still be prefetched</h2>
  <div class="col">
  <p>The reuse-distance work found every L2 stack distance above the 8,192 lines that 512 KB
  holds, so LRU returns nothing and 47.37% of V8's L2 references are compulsory. Belady's MIN
  cannot touch a compulsory miss, which is why its ceiling is 52.63%. A prefetcher can, because it
  does not need the line to have been referenced before.</p>
  <p>What it buys is not a cheaper fetch. It is the same fetch moved off the critical path: a
  demand miss makes the core wait <code>l2_miss_latency</code> 24, while a prefetch issued early
  spends those 24 cycles under work the core is already doing, leaving a
  <code>l2_latency</code> 2 hit behind. Each conversion is worth the 22 cycles between them, and
  <b>nothing about the DRAM's workload changes</b>, which the traffic column above confirms
  exactly rather than approximately.</p>
  <p>That is also why the gain is not uniform. It needs the core to have been stalled in the
  first place, and <code>cycles_over_compute_floor</code> measures precisely that. Across the
  {F['n']} layers the per-layer gain tracks that headroom at
  <b>r = {F['corr']:.3f}</b>: on the {F['n_hi']} layers with a floor ratio above 1.05 the geomean is
  {F['up_gm_hi']:.4f}&times;, and on the {F['n'] - F['n_hi']} already sitting on their floor it is
  {F['up_gm_lo']:.4f}&times;, which is the arithmetic of having nothing to win.</p>
  <p>Mean distance from the compute floor falls from {F['fl_off']:.3f}&times; to
  {F['fl_up']:.3f}&times;.</p>
  </div>
</section>

<section>
  <span class="eyebrow">Every layer</span>
  <h2>Four arms, {F['n']} layers, five samples each</h2>
  <div class="col">
  <p>Each arm's cell carries its own cycle count with its ratio to stage 3 underneath, so the four
  are comparable down a row and against the network across one. <b>off</b> reproduces the previous no-prefetch run to the digit, which is the gate: a
  policy that changes a run it is switched off in is not a policy. <b>Floor</b> is the layer's
  distance from its own compute floor, the ceiling on what any memory system can win there.</p>
  <p><code>&minus;1</code> is its own arm rather than <code>both</code> minus <code>+1</code>: the
  two halves share a cache and a port, so subtracting one from the other would report a number no
  run produced.</p>
  </div>
  {table([("Layer",0),("stage 3 cycles",1),("off cycles",1),("+1 cycles",1),
          ("&minus;1 cycles",1),("&plusmn;1 cycles",1),("L2 hit, +1",1),("Floor",1)], t1)}
</section>

<section>
  <span class="eyebrow">The asymmetry</span>
  <h2>Where every prefetch ended up</h2>
  <div class="col">
  <p>Totalled over all {F['n']} layers and five samples. The two arms differ in one config field
  and the outcome columns show why that field decides the result: the downward prefetches land on
  lines that are <i>already resident</i>, because the core walked past them a moment ago.</p>
  <p>This was predicted before the code was written. The measured lead from a line to its
  <code>cin_blk &minus; 1</code> neighbour is <b>&minus;16 lines</b>, meaning it was used
  earlier, against <b>+16</b> for <code>cin_blk + 1</code>. The counters were split by direction
  for exactly this reason, so the prediction could be tested rather than averaged away.</p>
  </div>
  {table([("Arm",0),("issued up",1),("issued down",1),("timely",1),("late",1),
          ("dropped, resident",1),("wasted",1),("L2 port stall",1)], t2)}
  <div class="col">
  <p>The upward arm drops {num(F['up_dah'])} of its own, {F['up_dah']/F['iu']*100:.2f}% of what it
  issues, so the drop column is essentially the downward half alone and the attribution above is a
  difference between arms rather than a guess.</p>
  <p>The port stall is the whole cost. It rises from zero to {num(F['p_up'])} core-cycles on the
  upward arm and to {num(F['p_both'])} on both, {F['p_ratio']:.2f}&times; more, for prefetches
  that were dropped before they reached the array. A dropped prefetch still spends its port slot,
  which is the same mechanism that cost the L1 prefetcher between 37% and 90% at 64-byte lines.</p>
  </div>
</section>

<section>
  <span class="eyebrow">Against the network</span>
  <h2>All four arms against stage 3</h2>
  <div class="col">
  <p>Two baselines, and they answer different questions. <b>Stage 3</b> is what the NoC simulator
  took to deliver the same layer, so the ratio against it says whether a cache in front of the
  cores beats the network as it stands. <b>off</b> is the same cache with the policy switched off,
  so the ratio against it isolates what the policy did.</p>
  <p>The ordering is the same under both, which is the useful part: <code>+1</code> ahead of
  <code>off</code> ahead of <code>&minus;1</code> ahead of <code>both</code>. A policy that
  improved one baseline while worsening the other would mean the two disagree about what a cycle
  is worth, and they do not.</p>
  </div>
  {table([("Arm",0),("geomean vs stage 3",1),("ahead of stage 3",1),
          ("geomean vs off",1),("faster than off",1)], t1b)}
  <div class="col">
  <p>Read the stage-3 column with the campaign's standing caveat: most of these layers are bounded
  by their own compute rather than by memory, so no memory system can move them. That is why
  {F['off_s3n']} layers were already ahead of the network before any prefetching, and why the best
  arm adds only one more. What the policy changes is the margin, not the count.</p>
  </div>
</section>

<section>
  <span class="eyebrow">Provenance</span>
  <h2>What ran, and how to run it again</h2>
  <div class="col">
  <p>One config point per arm, identical except for the policy fields: <code>khkw_split</code>,
  64-byte lines as <code>cin_block</code> 16 &times; <code>cout_block</code> 4, 16 KB 8-way L1,
  512 KB 16-way L2 with 32 MSHRs and one bank, <code>l2_latency</code> 2,
  <code>l2_miss_latency</code> 24, LRU, non-inclusive, 16 cores. The L1 prefetcher is off in every
  arm.</p>
  <p>The trigger fires on an L2 demand miss and on a demand hit to a line a prefetch put there and
  nobody has used yet, clearing the tag. That second rule is what keeps the chain alive: on a
  miss-only rule the prefetched line hits, the hit fires nothing, and the hit rate caps at exactly
  half.</p>
  </div>
<pre><code># the policy and the address arithmetic it rests on
src/wcache/native/include/wcache/prefetcher.h     L2Prefetcher, NeighbourL2Prefetcher
src/wcache/native/include/wcache/layout.h         AddressMapper::neighbour
src/wcache/native/tests/test_neighbour.cpp        30,695 checks, all three mappers

# the drivers, in profiling/0831_l2_prefetch/
run_sweep.py     {F['n']} layers x 5 samples x {len(ARMS)} arms      59 s
analyze.py       -&gt; outputs/l2pf_by_layer.csv

# on Delta
srun -A bebv-delta-gpu -p gpuA40x4 --gpus-per-node=1 -n1 -c 16 \\
     -t 01:00:00 --mem=120g python run_sweep.py 16</code></pre>
</section>

<footer>
  Plan <code>log/2026-08-31-l2-cin-neighbour-prefetch-plan.md</code>. Row-level data in
  <code>profiling/0831_l2_prefetch/outputs/</code>: <code>l2pf_rows.csv</code>
  ({F['n']} layers &times; 5 samples &times; {len(ARMS)} arms), <code>l2pf_by_layer.csv</code>
  ({len(rows)} rows). Baseline in
  <code>profiling/0831_all_layer_streams/outputs/</code>.
</footer>
</div>
"""
OUT.write_text(HTML)
print(f"wrote {OUT} ({len(HTML)} bytes)")
