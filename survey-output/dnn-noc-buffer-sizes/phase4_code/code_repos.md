# Phase 4 — Code & Artifacts

Open-source simulators and RTL with configurable local buffer sizes.

| Tool | URL | Language | Stars (approx) | What it models |
|------|-----|----------|----------------|----------------|
| SCALE-Sim | https://github.com/scalesim-project/scale-sim-v2 | Python | ~400 | Systolic array; IFMAP/Filter/OFMAP SRAM |
| Timeloop + Accelergy | https://github.com/NVlabs/timeloop | C++ | ~600 | Full memory hierarchy; per-level buffer |
| MAESTRO | https://github.com/maestro-project/maestro | C++ | ~250 | Cost model; L1/L2 scratchpad |
| ZigZag | https://github.com/ZigZag-Project/zigzag | Python | ~300 | DSE over any memory hierarchy |
| Gemmini | https://github.com/ucb-bar/gemmini | Chisel/Scala | ~800 | Full RTL; sp_capacity/acc_capacity params |
| CoSA | https://github.com/ucb-bar/cosa | Python | ~100 | ILP mapper for spatial arrays |
| NVDLA | https://github.com/nvdla/hw | SystemVerilog | ~1200 | Full RTL accelerator |

## Key Config Parameters

### SCALE-Sim v2 (scale.cfg)
```
ArrayHeight    = 128
ArrayWidth     = 128
IfmapSramSzkB  = 512     # input buffer
FilterSramSzkB = 512     # weight buffer
OfmapSramSzkB  = 512     # output buffer
```

### Timeloop Eyeriss-like (arch YAML)
```yaml
- name: DRAM
- name: shared_glb   # 108 KB, unified
- name: ifmaps_spad  # per-PE ~224 words (8 KB)
- name: weights_spad # per-PE ~224 words (4 KB)
- name: psum_spad    # per-PE ~16 words  (2 KB)
- name: MAC
```

### Gemmini (config.scala)
```scala
val sp_capacity = CapacityInKilobytes(256)  // scratchpad (A+B)
val acc_capacity = CapacityInKilobytes(64)  // accumulator (C)
val meshRows  = 16
val meshColumns = 16
```
