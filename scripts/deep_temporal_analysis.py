#!/usr/bin/env python3
"""
deep_temporal_analysis.py

Three-part analysis of deep_conv subset sweep results.

Req 1  Within-mode conditional distributions for each mode bucket.
Req 2  GB-level temporal tiling: both_dram_oooo vs both_dram_ootk.
Req 3  Minimal decisive multi-knob hardware combinations.

Output: outputs/deep_temporal_analysis.txt
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from itertools import combinations as combns
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.parse_output import (  # noqa: E402
    classify_t_in_loop, extract_best_block, kb_str_to_int,
)

SWEEP_DIR    = PROJECT_ROOT / "outputs" / "subset_sweep"
OUT_PATH     = PROJECT_ROOT / "outputs" / "deep_temporal_analysis.txt"

# ── parsing ────────────────────────────────────────────────────────────────────

def parse_file(path: Path) -> dict | None:
    m = re.match(
        r"deep_T(\d+)__nodes_(\d+)__gb_(\w+)__l1_(\w+)__pe_(\d+)__split_(\w+)",
        path.stem,
    )
    if not m:
        return None
    T, nodes, gb_str, l1_str, pe, split = m.groups()

    text = path.read_text()
    best, block = extract_best_block(text, text.splitlines())
    if not best or not block:
        return None

    dram_l = next((s for s in block if s.startswith("dram:")), "")
    gb_l   = next((s for s in block if s.startswith("gb:")),   "")

    return {
        "T":         int(T),
        "nodes":     int(nodes),
        "gb_bytes":  kb_str_to_int(gb_str),
        "l1_bytes":  kb_str_to_int(l1_str),
        "pe":        int(pe),
        "split":     split,
        "best":      best,
        "dram_t":    classify_t_in_loop(dram_l),
        "gb_t":      classify_t_in_loop(gb_l),
        "gb_body":   re.sub(r"^\s*gb:\s*",   "", gb_l).strip()   if gb_l   else "none",
        "dram_body": re.sub(r"^\s*dram:\s*", "", dram_l).strip() if dram_l else "none",
    }

# ── helpers ────────────────────────────────────────────────────────────────────

def bstr(b: int) -> str:
    if b >= 2**20: return f"{b>>20}MB"
    if b >= 1024:  return f"{b>>10}KB"
    return f"{b}B"

ALL_PARAMS = ["T", "nodes", "gb_bytes", "l1_bytes", "pe", "split"]

PARAM_LABEL = {
    "T":        "T (timesteps)",
    "nodes":    "nodes",
    "gb_bytes": "GB size",
    "l1_bytes": "L1 size",
    "pe":       "PEs/node",
    "split":    "mem split",
}

def pval(param: str, v) -> str:
    if param in ("gb_bytes", "l1_bytes"): return bstr(v)
    if param == "T":     return f"T={v}"
    if param == "nodes": return f"N={v}"
    if param == "pe":    return f"PE={v}"
    return str(v)

BUCKETS = ["both_gb_oooo", "both_dram_oooo", "both_dram_ootk", "psum_gb_ootk", "others"]

def bucket(mode: str) -> str:
    return mode if mode in BUCKETS[:-1] else "others"

# ── load records ──────────────────────────────────────────────────────────────

records = []
for f in sorted(SWEEP_DIR.glob("deep_*.txt")):
    r = parse_file(f)
    if r:
        records.append(r)

total = len(records)
out: list[str] = []

def w(s: str = "") -> None:
    out.append(s)

BAR = "═" * 78
SEP = "─" * 78

# ══════════════════════════════════════════════════════════════════════════════
# REQ 1 — within-mode conditional distributions
# ══════════════════════════════════════════════════════════════════════════════

w(BAR)
w("REQ 1  WITHIN-MODE CONDITIONAL DISTRIBUTIONS")
w(f"       deep_conv · {total} total configs")
w(BAR)

for bkt in BUCKETS:
    grp = [r for r in records if bucket(r["best"]) == bkt]
    n = len(grp)
    if n == 0:
        continue
    w()
    w(SEP)
    w(f"  [ {bkt.upper()} ]   {n} / {total} = {100*n/total:.1f}%")
    w(SEP)
    for param in ALL_PARAMS:
        vals = sorted({r[param] for r in records},
                      key=lambda x: x if isinstance(x, (int, float)) else x)
        counts = Counter(r[param] for r in grp)
        cells  = [f"{pval(param, v)}: {100*counts[v]/n:4.0f}%" for v in vals]
        w(f"  {PARAM_LABEL[param]:<16}  " + "   ".join(cells))

# ══════════════════════════════════════════════════════════════════════════════
# REQ 2 — GB-level temporal tiling comparison
# ══════════════════════════════════════════════════════════════════════════════

w()
w(BAR)
w("REQ 2  GB-LEVEL TEMPORAL TILING — both_dram_oooo  vs  both_dram_ootk")
w(BAR)

for bkt in ("both_dram_oooo", "both_dram_ootk"):
    grp = [r for r in records if r["best"] == bkt]
    n   = len(grp)
    w()
    w(f"  [ {bkt} ]   ({n} configs)")

    # dram_t / gb_t classification
    w(f"  {'dram_t':<10}" +
      "  ".join(f"{t}: {c} ({100*c/n:.0f}%)"
                for t, c in Counter(r["dram_t"] for r in grp).most_common()))
    w(f"  {'gb_t':<10}" +
      "  ".join(f"{t}: {c} ({100*c/n:.0f}%)"
                for t, c in Counter(r["gb_t"] for r in grp).most_common()))

    # Most common DRAM loop outermost 2 dims
    def outer2(body: str) -> str:
        parts = [p.strip() for p in body.split("→") if p.strip()]
        return " → ".join(parts[-2:]) if len(parts) >= 2 else body
    outer_ctr = Counter(outer2(r["dram_body"]) for r in grp)
    w(f"  Top outermost 2 DRAM dims:")
    for pat, cnt in outer_ctr.most_common(5):
        w(f"    {cnt:5d} ({100*cnt/n:5.1f}%)   dram: … → {pat}")

    # GB body distribution
    gb_ctr = Counter(r["gb_body"] for r in grp)
    w(f"  Top gb: line bodies:")
    for body, cnt in gb_ctr.most_common(5):
        w(f"    {cnt:5d} ({100*cnt/n:5.1f}%)   gb: {body}")

w()
w("  COMPARISON SUMMARY")
w(SEP)
w("  both_dram_oooo:  DRAM loops are purely SPATIAL (no T).  GB has T=2 alone")
w("                   → T is tiled ONCE at the GB level (GB_ooot).  Weight")
w("                     dominates GB footprint; psum/vmem are tiny.")
w("  both_dram_ootk:  GB is empty (none).  DRAM has T=2 in the middle with")
w("                   CIN=2 as the outermost loop: dram: … → T=2 → CIN=2.")
w("                   → T and K (CIN) are both tiled at the DRAM level (ootk).")
w("                     psum dominates GB footprint.")
w()
w("  Shared trait : both always tile T=2 — the factor is identical.")
w("  Key contrast : WHERE that T=2 tile lives differs entirely —")
w("                 GB level (both_dram_oooo)  vs  DRAM level (both_dram_ootk).")
w("                 both_dram_ootk additionally co-tiles CIN outside T in DRAM,")
w("                 enabling weight streaming across the CIN dimension.")

# ══════════════════════════════════════════════════════════════════════════════
# REQ 3 — minimal decisive multi-knob combinations
# ══════════════════════════════════════════════════════════════════════════════

w()
w(BAR)
w("REQ 3  MINIMAL DECISIVE MULTI-KNOB HARDWARE COMBINATIONS")
w(BAR)
w()
w("  Definition:")
w("    decisive  — every deep config matching a (param=value, …) subset picks")
w("                the same mode (100% mode purity, ≥1 config).")
w("    minimal   — no proper subset of the constraints is also decisive.")
w("    multi-knob— k ≥ 2 parameter constraints.")
w()

# ── find all decisive combos ───────────────────────────────────────────────────

decisive: dict[tuple, tuple] = {}   # (param_tuple, val_tuple) -> (mode, count)

for k in range(1, len(ALL_PARAMS) + 1):
    for ps in combns(ALL_PARAMS, k):
        groups: dict[tuple, list] = defaultdict(list)
        for r in records:
            groups[tuple(r[p] for p in ps)].append(r)
        for vk, grp in groups.items():
            modes = {r["best"] for r in grp}
            if len(modes) == 1:
                decisive[(ps, vk)] = (next(iter(modes)), len(grp))

w(f"  Total decisive constraint sets found (all k): {len(decisive)}")
for k in range(1, len(ALL_PARAMS) + 1):
    kc = sum(1 for (ps, _) in decisive if len(ps) == k)
    w(f"    k={k}: {kc}")

# ── filter to minimal multi-knob ──────────────────────────────────────────────

def proper_subsets(ps: tuple, vk: tuple):
    for sz in range(1, len(ps)):
        for idxs in combns(range(len(ps)), sz):
            yield tuple(ps[i] for i in idxs), tuple(vk[i] for i in idxs)

minimal: list[tuple] = []
for (ps, vk), (mode, count) in decisive.items():
    if len(ps) < 2:
        continue
    if any((sp, sv) in decisive for sp, sv in proper_subsets(ps, vk)):
        continue
    minimal.append((ps, vk, mode, count))

minimal.sort(key=lambda x: (len(x[0]), -x[3]))

w()
w(f"  Minimal decisive multi-knob combos: {len(minimal)}")
by_k: dict[int, list] = defaultdict(list)
for ps, vk, mode, count in minimal:
    by_k[len(ps)].append((ps, vk, mode, count))
for k in sorted(by_k):
    w(f"    k={k}: {len(by_k[k])}")

# ── detailed output per k ─────────────────────────────────────────────────────

MAX_PER_MODE = 40   # cap rows shown per (k, mode) group

for k in sorted(by_k):
    grp = by_k[k]
    w()
    w(f"  {'─'*70}")
    w(f"  k = {k}   ({len(grp)} minimal combos)")
    w(f"  {'─'*70}")

    # Group by mode, then sort by count desc within mode
    by_mode: dict[str, list] = defaultdict(list)
    for ps, vk, mode, count in grp:
        by_mode[mode].append((ps, vk, count))

    for bkt in BUCKETS:
        entries = sorted(by_mode.get(bkt, []), key=lambda x: -x[2])
        if not entries:
            continue
        total_cfg = sum(c for _, _, c in entries)
        w(f"    → {bkt}   ({len(entries)} combos, {total_cfg} configs)")
        shown = entries[:MAX_PER_MODE]
        for ps, vk, count in shown:
            constraint_str = ",  ".join(f"{PARAM_LABEL[p]}={pval(p, v)}"
                                        for p, v in zip(ps, vk))
            w(f"      {count:5d} cfg   {constraint_str}")
        if len(entries) > MAX_PER_MODE:
            w(f"      … ({len(entries) - MAX_PER_MODE} more combos not shown)")

# ── write output ──────────────────────────────────────────────────────────────

text = "\n".join(out)
OUT_PATH.write_text(text)
print(text)
print()
print(f"Saved → {OUT_PATH}")
