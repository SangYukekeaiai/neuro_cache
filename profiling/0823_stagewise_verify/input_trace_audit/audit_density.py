#!/usr/bin/env python3
"""Density audit of every captured LoAS input trace.

Checks the premise that SNN input spike density should sit near 10%, across all
12 vgg16 and 19 resnet19 layers of the full 10,000-sample captures.
"""
import json, pathlib, sys, numpy as np

R = pathlib.Path('/work/hdd/bebv/yyu9/neuro_cache_trace/input_trace/loas')
OUT = pathlib.Path(__file__).resolve().parent
N = 200

lines, rows = [], {}
def p(s=""):
    lines.append(s)
    print(s, flush=True)

p("Input-trace density audit, 2026-08-23")
p(f"Source: {R}  (the full 10,000-sample captures)")
p(f"Density measured over the first {N} images of each capture.")
p("A layer's captured tensor is its INPUT, so CIN comes from that tensor and")
p("COUT from the next captured layer's CIN (archmodels/trace.py:130-138).")
p("'always' / 'never' are the fraction of neurons firing at all T / at no T.")
p()
for td in ['vgg16_T4_all', 'resnet19_T4_all']:
    m = json.load(open(R / td / 'meta.json'))
    names = list(m['layers'])
    p("=" * 100)
    p(f"{td}   captured_at {m['captured_at']}   T={m['timestep']}   dtype={m['dtype']}")
    p("=" * 100)
    p(f"{'#':>3} {'layer':32s} {'CIN':>5} {'COUT':>5} {'HO':>4} {'density':>8} "
      f"{'always':>7} {'never':>7}  verdict")
    out = []
    for i, ln in enumerate(names):
        a = np.load(R / td / f'{ln}.npy', mmap_mode='r')
        T, _B, cin, hin, _win = a.shape
        cout = m['layers'][names[i + 1]][2] if i + 1 < len(names) else cin
        x = np.asarray(a[:, :N]).astype(np.uint8)
        d = float(x.mean())
        s = x.sum(axis=0)
        always, never = float((s == T).mean()), float((s == 0).mean())
        verdict = ("OK" if d <= 0.25 else "ELEVATED" if d <= 0.40
                   else "HIGH" if d <= 0.60 else "SATURATED")
        p(f"{i+1:>3} {ln:32s} {cin:>5} {cout:>5} {hin:>4} {d:>8.4f} "
          f"{always:>7.3f} {never:>7.3f}  {verdict}")
        out.append(dict(idx=i + 1, layer=ln, cin=cin, cout=cout, ho=hin, density=d,
                        always_fire=always, never_fire=never, verdict=verdict))
    rows[td] = out
    p()

(OUT / "density_audit.txt").write_text("\n".join(lines) + "\n")
(OUT / "density_audit.json").write_text(json.dumps(rows, indent=1) + "\n")
