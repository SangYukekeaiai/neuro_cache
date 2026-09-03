#!/usr/bin/env python3
"""The 31-layer L2 associativity scan: l2_assoc 16 vs 32, everything else pinned.

Plan: the set-local reuse distance is exactly 31 on all four layers measured so
far, so 16 ways cannot hold a reuse window and 32 can. This checks that on every
layer of both networks.

One layer at a time: generate its stream, run both arms, delete the stream. Peak
disk is one stream, not 31.
"""
import csv, json, pathlib, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parents[2]
GEN  = ROOT / "scripts/generate_weight_traces.py"
RUN  = ROOT / "src/wcache/native/build/release/wcache_run"
OUT  = pathlib.Path(__file__).resolve().parent / "outputs"

BASE = {"cout_block":4,"weight_bytes":1,"layout":"khkw_split",
        "l1_size_bytes":16384,"l1_assoc":8,
        "l2_size_bytes":524288,"l2_mshrs":32,
        "l1_latency":0,"l2_latency":2,"l2_miss_latency":24,
        "cin_block":16,"l2_banks":1,
        "prefetch_policy":"none","prefetch_distance":0}

DIRS = {"vgg16_T4_n5":"vgg16", "resnet19_T4_n5":"resnet19"}

def layers():
    out=[]
    for td in DIRS:
        meta=json.load(open(ROOT/f"input_trace/loas/{td}/meta.json"))
        for L in meta["layers"]: out.append((td,L))
    return out

def engine(wcts, assoc, tag, td):
    with tempfile.TemporaryDirectory() as t:
        t=pathlib.Path(t)
        (t/"c.json").write_text(json.dumps(dict(BASE, l2_assoc=assoc)))
        r=subprocess.run([str(RUN),"--config",str(t/"c.json"),"--trace",str(wcts),
                          "--run-id",f"a31-{tag}-{assoc}","--header"],
                         capture_output=True,text=True)
    if r.returncode: raise RuntimeError(f"{td}/{tag} assoc {assoc}: "
                                        f"{r.stderr.strip().splitlines()[-1][:160]}")
    rows=list(csv.reader(r.stdout.splitlines()))
    return dict(zip(rows[0],rows[1]))

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    todo=layers(); rows=[]; t0=time.time()
    print(f"31-layer scan, l2_assoc 16 vs 32, sample 0, everything else pinned.\n")
    with tempfile.TemporaryDirectory() as sd:
        sd=pathlib.Path(sd)
        for n,(td,L) in enumerate(todo,1):
            wcts=sd/"s.wcts"
            g=subprocess.run([sys.executable,str(GEN),"--stream","--arch","loas",
                "--trace-dir",td,"--layer",L,"--sample-start","0","--sample-count","1",
                "--workers","1","--schedule-cache","outputs/schedules/inst16"],
                cwd=ROOT, stdout=open(wcts,"wb"), stderr=subprocess.PIPE, text=False)
            if g.returncode:
                print(f"  {n:>2}/31 {L:<28} STREAM FAIL: "
                      f"{g.stderr.decode().strip().splitlines()[-1][:120]}"); continue
            a=engine(wcts,16,L,td); b=engine(wcts,32,L,td)
            wcts.unlink()
            r={"net":DIRS[td],"layer":L,
               "l2_accesses":a["l2_accesses"],"l2_lines":a["dram_accesses"],
               "hit16":float(a["l2_hit_rate"]),"hit32":float(b["l2_hit_rate"]),
               "cyc16":int(a["total_cycles"]),"cyc32":int(b["total_cycles"]),
               "l1hit":float(a["l1_hit_rate"]),
               "dram16":int(a["dram_accesses"]),"dram32":int(b["dram_accesses"])}
            r["speedup"]=r["cyc16"]/r["cyc32"] if r["cyc32"] else 0.0
            rows.append(r)
            print(f"  {n:>2}/31 {L:<28} l2 {100*r['hit16']:5.2f}% -> {100*r['hit32']:5.2f}%   "
                  f"cyc {r['cyc16']:>9,} -> {r['cyc32']:>9,}  {r['speedup']:.3f}x  "
                  f"({time.time()-t0:.0f}s)", flush=True)
    with (OUT/"assoc31.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f"\n{len(rows)} layers -> {OUT/'assoc31.csv'}  ({time.time()-t0:.0f}s)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
