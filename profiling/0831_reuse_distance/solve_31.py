#!/usr/bin/env python3
"""Solve inst16 schedules for all 31 loas layers of the two surviving n5 trace
dirs.  A variant of scripts/solve_inst16_subset.py, whose LAYERS list is the
four the 0823 stage-4 study used; the same call, over every layer instead.
"""
import json, pathlib, sys, time
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import tracegen

ARCH = "loas"
TRACE_ROOT = ROOT / "input_trace/loas"
CACHE = ROOT / "outputs/schedules/inst16"
DIRS = ["vgg16_T4_n5", "resnet19_T4_n5"]

def main():
    arch_yaml = str(ROOT / f"configs/arch/{ARCH}_inst16.yaml")
    df_yaml   = str(ROOT / f"configs/dataflow/{ARCH}.yaml")
    ok = fail = skip = 0
    t00 = time.time()
    for td in DIRS:
        meta = json.load(open(TRACE_ROOT / td / "meta.json"))
        names = list(meta["layers"])
        for i, layer in enumerate(names):
            out = CACHE / ARCH / td / f"{layer}.json"
            if out.exists():
                print(f"  skip  {td}/{layer}"); skip += 1; continue
            next_cin = meta["layers"][names[i+1]][2] if i+1 < len(names) else None
            t0 = time.time()
            try:
                art = tracegen.solve_and_cache_schedule(
                    ARCH, arch_yaml, df_yaml, td, layer, meta, next_cin, CACHE)
            except Exception as e:
                print(f"  FAIL  {td}/{layer}: {type(e).__name__}: {e}"); fail += 1; continue
            has = art.result.get("has_solution")
            print(f"  {'ok  ' if has else 'INFEASIBLE'} {td}/{layer}  mode={art.mode} "
                  f"dram_steps={art.dram_num_steps} {time.time()-t0:.1f}s", flush=True)
            ok += 1 if has else 0; fail += 0 if has else 1
    print(f"\nsolved {ok}, failed {fail}, skipped {skip}  ({time.time()-t00:.0f}s)")
    return 1 if fail else 0

if __name__ == "__main__":
    sys.exit(main())
