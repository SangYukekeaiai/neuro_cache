#!/usr/bin/env python3
"""Per-layer L1/L2 hit rates, L2 global reuse distance, and L2 reuse-count
distribution, for all 31 layers.  Config identical to run_assoc31.py at 16-way.

Set-local reuse distance is also computed, but only for layers that turn out to
have reuse: it needs a second run for the line-to-set map and is meaningless
where every line is touched once.
"""
import collections, csv, io, json, pathlib, struct, subprocess, sys, tempfile, time
ROOT = pathlib.Path(__file__).resolve().parents[2]
GEN  = ROOT/"scripts/generate_weight_traces.py"
RUN  = ROOT/"src/wcache/native/build/release/wcache_run"
OUT  = pathlib.Path(__file__).resolve().parent/"outputs"
BASE = {"cout_block":4,"weight_bytes":1,"layout":"khkw_split","l1_size_bytes":16384,
        "l1_assoc":8,"l2_size_bytes":524288,"l2_assoc":16,"l2_mshrs":32,"l1_latency":0,
        "l2_latency":2,"l2_miss_latency":24,"cin_block":16,"l2_banks":1,
        "prefetch_policy":"none","prefetch_distance":0}
DIRS={"vgg16_T4_n5":"vgg16","resnet19_T4_n5":"resnet19"}

def l2_seq(path):
    out=[]
    with open(path,"rb") as f:
        f.read(8)
        while (b:=f.read(1<<16)):
            for i in range(0,len(b)-7,8):
                if b[i]==1 and b[i+2]==1: out.append(struct.unpack_from("<I",b,i+4)[0])
    return out

def stack_hist(seq, sets=None):
    """Stack distance in distinct lines. `sets` restricts to the same set."""
    h=collections.Counter(); cold=0; last={}
    for i,L in enumerate(seq):
        if L not in last: cold+=1
        else:
            w=seq[last[L]+1:i]
            h[len({x for x in w} if sets is None
                  else {x for x in w if sets[x]==sets[L]})]+=1
        last[L]=i
    return cold,h

def main():
    rows=[]; t0=time.time(); n=0
    with tempfile.TemporaryDirectory() as sd:
        sd=pathlib.Path(sd)
        for td,net in DIRS.items():
            meta=json.load(open(ROOT/f"input_trace/loas/{td}/meta.json"))
            for L in meta["layers"]:
                n+=1; w=sd/"s.wcts"; alog=sd/"a.log"; cst=sd/"c.csv"
                g=subprocess.run([sys.executable,str(GEN),"--stream","--arch","loas",
                    "--trace-dir",td,"--layer",L,"--sample-start","0","--sample-count","1",
                    "--workers","1","--schedule-cache","outputs/schedules/inst16"],
                    cwd=ROOT,stdout=open(w,"wb"),stderr=subprocess.DEVNULL)
                if g.returncode: print(f"  {n:>2}/31 {L} STREAM FAIL"); continue
                (sd/"c.json").write_text(json.dumps(BASE))
                r=subprocess.run([str(RUN),"--config",str(sd/"c.json"),"--trace",str(w),
                    "--run-id","an","--header","--access-log",str(alog)],
                    capture_output=True,text=True,check=True)
                cr=list(csv.reader(r.stdout.splitlines())); row=dict(zip(cr[0],cr[1]))
                seq=l2_seq(alog); alog.unlink()
                cold,gh=stack_hist(seq)
                cnt=collections.Counter(collections.Counter(seq).values())
                # set-local, only where reuse exists
                sl=""
                if len(gh):
                    subprocess.run([str(RUN),"--config",str(sd/"c.json"),"--trace",str(w),
                        "--run-id","an","--header","--access-log","/dev/null",
                        "--cache-state",str(cst),"--cache-state-core","0"],
                        capture_output=True,text=True,check=True)
                    txt=[x for x in cst.read_text().splitlines() if not x.startswith("#")]
                    m={int(q["line"]):int(q["set"]) for q in csv.DictReader(io.StringIO("\n".join(txt)))
                       if q["level"]=="l2"}
                    _,lh=stack_hist(seq,m)
                    sl=";".join(f"{k}:{v}" for k,v in sorted(lh.items()))
                    cst.unlink()
                w.unlink()
                rows.append({"net":net,"layer":L,
                  "l1_hit_rate":row["l1_hit_rate"],"l1_accesses":row["l1_accesses"],
                  "l2_hit_rate":row["l2_hit_rate"],"l2_accesses":row["l2_accesses"],
                  "l2_lines":str(len(set(seq))),"reuse":f"{len(seq)/max(1,len(set(seq))):.4f}",
                  "cold":str(cold),
                  "global_rd":";".join(f"{k}:{v}" for k,v in sorted(gh.items())),
                  "setlocal_rd":sl,
                  "reuse_count":";".join(f"{k}:{v}" for k,v in sorted(cnt.items()))})
                print(f"  {n:>2}/31 {L:<28} l1 {100*float(row['l1_hit_rate']):5.2f}%  "
                      f"l2 {100*float(row['l2_hit_rate']):5.2f}%  reuse {rows[-1]['reuse']}  "
                      f"rd[{len(gh)}] cnt[{len(cnt)}]  ({time.time()-t0:.0f}s)",flush=True)
    with (OUT/"perlayer31.csv").open("w",newline="") as f:
        wr=csv.DictWriter(f,fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
    print(f"\n{len(rows)} layers -> {OUT/'perlayer31.csv'}  ({time.time()-t0:.0f}s)")
    return 0
if __name__=="__main__": sys.exit(main())
