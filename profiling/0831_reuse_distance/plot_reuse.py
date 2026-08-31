#!/usr/bin/env python3
"""Reuse-distance histograms as SVG, generated from outputs/reuse_hist.csv.

Part of plan unit U5. Emits outputs/spectra.svg as a fragment the artifact
embeds, so every bar on the page is drawn from the measured data rather than
hand-placed.

TWO LOG AXES, both forced by the data rather than chosen for effect:

  x, distance.  The buckets span 0 to 3,071. A linear axis puts every L1 bucket
                in the leftmost 9% of the panel. Plotted as log10(d+1), which
                keeps d=0 on the axis instead of at negative infinity.
  y, share.     One bucket holds 84% and another holds 0.03%. On a linear axis
                the small ones have no height at all.

COLD sits outside the frame, past a divider. It has no distance, so placing it
anywhere on the distance axis would assert something false about it.
"""
import collections
import csv
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
OUT  = HERE / "outputs"
TAGS = ["V8", "V9", "R9", "R16"]
TITLE = {"V8": "V8 · vgg16 features_27", "V9": "V9 · vgg16 features_30",
         "R9": "R9 · resnet19 layer2_0_conv2", "R16": "R16 · resnet19 layer3_0_conv2"}
# Lines each level actually held at the execution config, 64 B lines.
CAP = {"l1": 256, "l2": 8192}
CAPLBL = {"l1": "L1 = 256 lines", "l2": "L2 = 8192 lines"}

W, H = 430, 168          # panel box
PX, PY = 62, 20          # plot origin inside the panel
PW, PH = 320, 84         # plot area
XMAX = 4.3               # log10(d+1) ceiling, d ~ 20000
YMIN = -4.3              # log10(share) floor, ~0.005%


def load():
    agg = collections.defaultdict(collections.Counter)
    for r in csv.DictReader((OUT / "reuse_hist.csv").open()):
        if r["_sample"] != "0":
            continue
        agg[(r["_tag"], r["level"])][int(r["distance"])] += int(r["count"])
    return agg


def sx(d):
    import math
    return PX + (math.log10(d + 1) / XMAX) * PW


def sy(share):
    import math
    if share <= 0:
        return PY + PH
    v = max(math.log10(share), YMIN)
    return PY + PH - (v - YMIN) / (0 - YMIN) * PH


def panel(tag, level, buckets, ox, oy):
    import math
    total = sum(buckets.values())
    cold = buckets.get(-1, 0)
    finite = sorted((d, c) for d, c in buckets.items() if d >= 0)
    g = [f'<g transform="translate({ox},{oy})">']
    g.append(f'<text class="pt" x="0" y="12">{tag} — {level.upper()}'
             f' <tspan class="pd">{total:,} refs</tspan></text>')

    # y gridlines at 100%, 10%, 1%, 0.1%, 0.01%
    for e in range(0, -5, -1):
        y = sy(10.0 ** e)
        g.append(f'<line class="gl" x1="{PX}" y1="{y:.1f}" x2="{PX+PW}" y2="{y:.1f}"/>')
        lab = f"{100*10.0**e:g}%" if e > -4 else "0.01%"
        g.append(f'<text class="ax" x="{PX-6:.0f}" y="{y+3:.1f}" text-anchor="end">{lab}</text>')

    # x ticks at d = 0, 1, 10, 100, 1000, 10000
    for d in (0, 1, 10, 100, 1000, 10000):
        x = sx(d)
        g.append(f'<line class="tk" x1="{x:.1f}" y1="{PY+PH}" x2="{x:.1f}" y2="{PY+PH+4}"/>')
        g.append(f'<text class="ax" x="{x:.1f}" y="{PY+PH+15}" text-anchor="middle">{d}</text>')
    g.append(f'<line class="fr" x1="{PX}" y1="{PY+PH}" x2="{PX+PW}" y2="{PY+PH}"/>')

    # capacity marker
    cx = sx(CAP[level])
    g.append(f'<line class="caprule" x1="{cx:.1f}" y1="{PY-2}" x2="{cx:.1f}" y2="{PY+PH}"/>')
    anchor = "end" if cx > PX + PW * 0.62 else "start"
    dx = -4 if anchor == "end" else 4
    g.append(f'<text class="capt" x="{cx+dx:.1f}" y="{PY+6}" text-anchor="{anchor}">'
             f'{CAPLBL[level]}</text>')

    # the bars
    for d, c in finite:
        share = c / total
        x, y = sx(d), sy(share)
        g.append(f'<rect class="bar" x="{x-2.2:.1f}" y="{y:.1f}" width="4.4" '
                 f'height="{PY+PH-y:.1f}"><title>distance {d}: {c:,} references, '
                 f'{100*share:.2f}%</title></rect>')

    # label the two largest, plus the largest distance
    tops = sorted(finite, key=lambda kv: -kv[1])[:2]
    mark = {d for d, _ in tops}
    if finite:
        mark.add(finite[-1][0])
    for d, c in finite:
        if d not in mark:
            continue
        share = c / total
        x, y = sx(d), sy(share)
        a = "end" if x > PX + PW * 0.75 else "start"
        g.append(f'<text class="bl" x="{x + (-4 if a=="end" else 4):.1f}" y="{y-3:.1f}" '
                 f'text-anchor="{a}">d={d} · {100*share:.1f}%</text>')

    # cold, outside the frame
    g.append(f'<line class="div" x1="{PX-52}" y1="{PY}" x2="{PX-52}" y2="{PY+PH}"/>')
    if cold:
        cy = sy(cold / total)
        g.append(f'<rect class="cold" x="{PX-46}" y="{cy:.1f}" width="9" '
                 f'height="{PY+PH-cy:.1f}"><title>cold: {cold:,} first references, '
                 f'{100*cold/total:.2f}%</title></rect>')
        g.append(f'<text class="bl cold-t" x="{PX-41.5:.1f}" y="{cy-3:.1f}" '
                 f'text-anchor="middle">{100*cold/total:.1f}%</text>')
    g.append(f'<text class="ax" x="{PX-41.5:.0f}" y="{PY+PH+15}" text-anchor="middle">cold</text>')
    g.append(f'<text class="ax" x="{PX+PW/2:.0f}" y="{PY+PH+31}" text-anchor="middle">'
             f'reuse distance, in distinct lines</text>')
    g.append("</g>")
    return "\n".join(g)


def main():
    agg = load()
    rows = []
    for i, tag in enumerate(TAGS):
        ox = (i % 2) * (W + 16)
        oy = (i // 2) * (2 * H + 26)
        rows.append(f'<text class="ph" x="{ox}" y="{oy-8}">{TITLE[tag]}</text>')
        rows.append(panel(tag, "l1", agg[(tag, "l1")], ox, oy))
        rows.append(panel(tag, "l2", agg[(tag, "l2")], ox, oy + H))
    total_w = 2 * W + 16
    total_h = 2 * (2 * H + 26) + 10
    svg = (f'<svg viewBox="-2 -22 {total_w+4} {total_h+8}" role="img" '
           f'aria-label="Reuse-distance histograms for four layers, L1 and L2, on log axes.">\n'
           + "\n".join(rows) + "\n</svg>\n")
    (OUT / "spectra.svg").write_text(svg)
    print(f"wrote {OUT/'spectra.svg'}  ({len(svg):,} bytes)")

    # The numbers the artifact quotes, printed so they can be checked by eye.
    for tag in TAGS:
        for lv in ("l1", "l2"):
            b = agg[(tag, lv)]
            tot = sum(b.values())
            fin = sorted(d for d in b if d >= 0)
            print(f"  {tag:>4} {lv}: {len(fin):>2} buckets "
                  f"{'(' + ', '.join(str(d) for d in fin[:6]) + ('...' if len(fin)>6 else '') + ')':<34}"
                  f" cold {100*b.get(-1,0)/tot:5.2f}%  max d={fin[-1] if fin else 'n/a'}")


if __name__ == "__main__":
    main()
