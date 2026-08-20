"""Measure the whole generated corpus, one sample per layer.

Written for the "Phase C -> A3" obligation in PROGRESS.md, which says plan unit
A3 owes two numbers against the REAL corpus that `FakeTrace` cannot supply: the
count of `gap == 0` pairs (Q11 says it must be zero) and the `tile_tail`
histogram (Q10 closed with numbers this script does not reproduce). Kept beside
the examples rather than run once from a scratchpad, per decision B147: a number
with no artifact in the tree is a claim.

Reads the FIRST sample of every layer directory, preferring the `.gz` where both
a `.gz` and a stale uncompressed `.json` exist -- see decision B154, since
loas/vgg16 layer 01 holds a v1 leftover that describes a different tiling of the
same layer. Reports per layer:

    fmt                on-disk shape, "v2" (tiles -> ticks -> cores) or the
                       legacy flat "v1"
    gap0/gapmin/gapmax spacing between one core's consecutive bursts in a tile
    multi              (core, tick) pairs carrying more than one burst
    cores_union/core_max   distinct core ids seen, and the largest
    tile_core_counts   how many cores participate per tile
    tail_min/max/mode  mac_cycles - max_tick, the Q10 tail

Writes the per-layer rows as JSON to the path given by $OUT, and streams one row
per line to stdout as it goes, since a full pass parses tens of GB and takes
minutes.

Run from the repo root:
    OUT=/tmp/survey.json conda run -n base python src/wcache/examples/survey_corpus.py
"""

import json, gzip, glob, os, sys
from collections import Counter

ROOT = "outputs/weight_traces"
rows = []
for arch in ["loas","prosperity","ptb","spinalflow","gustavsnn"]:
    for wl in ["vgg16_T4_all","resnet19_T4_all"]:
        for layer in sorted(glob.glob(os.path.join(ROOT,arch,wl,"layer_*"))):
            fs = sorted(glob.glob(os.path.join(layer,"*.json.gz")))
            if not fs:
                fs = sorted(glob.glob(os.path.join(layer,"sample_*.json")))
            if not fs:
                rows.append(dict(arch=arch,wl=wl,layer=os.path.basename(layer),fmt="EMPTY")); continue
            p = fs[0]
            d = json.load(gzip.open(p,'rt') if p.endswith('.gz') else open(p))
            t0 = d["tiles"][0] if d["tiles"] else {}
            if "ticks" not in t0:
                rows.append(dict(arch=arch,wl=wl,layer=os.path.basename(layer),fmt="v1",
                                 n_tiles=len(d["tiles"]))); continue
            gap0=0; gapmin=None; gapmax=None; bursts=0; multi=0
            tails=Counter(); cores=set(); percore_tile=Counter(); spans=set()
            for t in d["tiles"]:
                mx=-1; per={}
                for te in t["ticks"]:
                    mx=max(mx,te["tick"])
                    for ce in te["cores"]:
                        c=ce["core_id"]; cores.add(c)
                        wa=ce["weight_addresses"]; bursts+=len(wa)
                        if len(wa)>1: multi+=1
                        for a in wa: spans.add(a[4]-a[3])
                        per.setdefault(c,[]).extend([te["tick"]]*len(wa))
                percore_tile[len(per)]+=1
                for c,fl in per.items():
                    fl.sort()
                    for i in range(1,len(fl)):
                        g=fl[i]-fl[i-1]
                        if g==0: gap0+=1
                        gapmin=g if gapmin is None else min(gapmin,g)
                        gapmax=g if gapmax is None else max(gapmax,g)
                tails[t["mac_cycles"]-mx]+=1
            rows.append(dict(arch=arch,wl=wl,layer=os.path.basename(layer),fmt="v2",
                n_tiles=len(d["tiles"]), bursts=bursts, gap0=gap0, gapmin=gapmin, gapmax=gapmax,
                multi=multi, cores_union=len(cores), core_max=max(cores) if cores else None,
                tile_core_counts=sorted(percore_tile.items())[:4],
                tail_min=min(tails), tail_max=max(tails),
                tail_mode=tails.most_common(1)[0], spans=sorted(spans)))
            print(json.dumps(rows[-1]), flush=True)
json.dump(rows, open(os.environ["OUT"],"w"), indent=1)
print("DONE", len(rows))
