# Phase 5 — Synthesis

## Taxonomy

### Cluster A — Small-footprint edge chips (per-PE scratchpad dominant)
Eyeriss, ShiDianNao, DianNao, Gemmini-default, MAERI.
Feature: small PE RF (< 1KB/PE), modest global buffer (8–192KB).

### Cluster B — High-throughput data-center chips (DRAM near-memory or large SRAM)
TPU v1, DaDianNao, Ascend 910, SCNN.
Feature: very large weight stores (4–28 MB); small or no per-PE weight register.

### Cluster C — Simulation/DSE reference architectures
SCALE-Sim, Timeloop, MAESTRO, ZigZag, CoSA, Interstellar.
Feature: parameterizable; community-standard sizes often match Eyeriss.

### Cluster D — Multi-chip / chiplet architectures
Simba.
Feature: per-chiplet local scratchpad + slower cross-chip packet NoC.

## Lineage & History

```
DianNao (2014) ──► DaDianNao (2014) ──► [enterprise scale]
                         │
ShiDianNao (2015) ◄──────┘  (near-sensor, output-stationary)
        │
Eyeriss (2016) ──────────────────────────────────────────────────────────────────────►
    Row-stationary;  108KB GLB; ~192B/PE RF               ┌─ Eyeriss v2 (2019)
    168 PEs; multicast mesh NoC                            │  192KB GLB; Hier. mesh
        │                                                   │
        ├──► TETRIS (2017) — HMC replaces big GLB           │
        │                                                   │
        ├──► SCNN (2017) — sparse; 512KB per data type     │
        │                                                   │
        ├──► MAERI (2018) — reconfigurable NoC             │
        │                                                   ▼
EIE (2016) ─────────────────────────────────────  Simba (2019) — MCM chiplets
64PE sparse; 128KB/PE weight spad                  256KB/chiplet; 2MB global

TPU v1 (2017) ─────────────────────────────────── Ascend 910 (2021)
256×256 systolic; 28MB weight + 24MB UB           L0A 32KB + L0B 32KB + L0C 256KB

Simulation tools:
Timeloop (2019) ── MAESTRO (2020) ── ZigZag (2021) ── CoSA (2021)
SCALE-Sim (2019) ── Gemmini (2021, full RTL) ── Interstellar (2020)
```

## Comparative Table

| Accelerator | Year | Venue | Input Buffer | Weight Buffer | Output/Psum Buffer | Total On-chip | PEs | NoC |
|------------|------|-------|-------------|---------------|-------------------|--------------|-----|-----|
| DianNao | 2014 | ASPLOS | 2 KB (NBin) | 2 KB (SB) | 2 KB (NBout) | ~6 KB | 64 MACs | Direct wires |
| DaDianNao | 2014 | MICRO | 512 KB/tile | 4 MB eDRAM/tile | 512 KB/tile | 4.5 MB/tile | 16 NFU/tile | 3D torus |
| ShiDianNao | 2015 | ISCA | 32 KB | ~1 KB RF | 32 KB | ~64 KB | 64 (8×8) | H/V pass registers |
| Eyeriss | 2016/17 | JSSC | ~192 B/PE (108KB shared) | ~192 B/PE (shared) | ~384 B/PE (shared) | **192 KB** | 168 (14×12) | Multicast mesh |
| EIE | 2016 | ISCA | 2 KB/PE act | 128 KB/PE weight | 1 KB/PE RF | ~160 KB/PE | 64 | H-tree (quad-tree) |
| TPU v1 | 2017 | ISCA | **24 MB** (unified buffer) | **28 MB** (FIFO) | **4 MB** (accumulator) | **28 MB** | 65536 (systolic) | Systolic (cell-to-cell) |
| SCNN | 2017 | ISCA | 16 KB/PE (512KB global) | 16 KB/PE (512KB global) | 48 KB/PE | ~1 MB | 16 (4×4) | Crossbar scatter |
| TETRIS | 2017 | ASPLOS | 8–16 KB (global, reduced) | RF only (~192B/PE) | RF only | ~8–16 KB | 168 | Multicast mesh + HMC |
| MAERI | 2018 | ASPLOS | 512 B/PE + 64 KB shared | 512 B/PE + 64 KB shared | 2 KB/PE + 128 KB shared | ~256 KB | 64 | AdderTree (flex) |
| Eyeriss v2 | 2019 | JETCAS | ~192 B/PE (4.5 KB/cluster) | ~288 B/PE (7.5 KB/cluster) | ~80 B/PE (7.5 KB/cluster) | **192 KB** | 192 (8×2×12) | Hierarchical mesh |
| Timeloop ref | 2019 | ISPASS | 8 KB/PE (spad) | 4 KB/PE (spad) | 2 KB/PE (spad) | **108 KB** GLB | 168 | Eyeriss-like |
| SCALE-Sim | 2019 | arXiv | **512 KB** IFMAP SRAM | **512 KB** Filter SRAM | **512 KB** OFMAP SRAM | **1.5 MB** | 128×128=16K | 2D mesh |
| Simba | 2019 | MICRO | 256 KB/chiplet (shared) | 256 KB/chiplet (shared) | 256 KB/chiplet (shared) | **2 MB** global | 16/chiplet×36 | Packet 2D mesh |
| Buffets | 2019 | ASPLOS | flexible (scratchpad idiom) | flexible | flexible | design-specific | any | any |
| MAESTRO | 2020 | Micro | **2 KB**/PE (L1) | **2 KB**/PE (L1) | **2 KB**/PE (L1) | **1 MB** (L2) | 256 | parameterized |
| Interstellar | 2020 | ASPLOS | 8 KB/PE | 4 KB/PE | 2 KB/PE | 108 KB GLB | 168 | Eyeriss-like |
| CoSA | 2021 | ISCA | **8 KB**/PE | **32 KB**/PE | **3 KB**/PE | **128 KB** | 16 (4×4 × 64 MAC) | 2D mesh |
| Gemmini | 2021 | DAC | **256 KB** scratchpad (A) | **256 KB** scratchpad (B) | **64 KB** accumulator | **576 KB** | 256 (16×16) | Pipeline regs |
| ZigZag | 2021 | IEEE TC | 2 KB (L1, vary) | 2 KB (L1, vary) | 2 KB (L1, vary) | **64 KB** (L2, vary) | any | parameterized |
| Ascend 910 | 2021 | HPCA | **32 KB** L0A | **32 KB** L0B | **256 KB** L0C | **32 MB** (L2) | 32K (AI cores) | 3D hier. mesh |
| NVDLA | 2017 | HotChips | **256 KB** (CBUF input) | **512 KB** (CBUF weight) | integrated | ~768 KB | 1024 (512×2) | Internal bus |

## Gaps & Observations

1. **No universal naming**: "input buffer", "iact spad", "NBin", "IFMAP SRAM", "L0A", "UB" all refer to the same concept
   across different papers — care needed when comparing.

2. **Per-PE vs. global distinction is often blurred**: SCALE-Sim reports a single SRAM per data type (global),
   while Eyeriss reports per-PE scratchpads. Both models are valid but represent different abstraction levels.

3. **Weight buffer is always the largest**: Across all designs, weight/filter storage > input storage > output/psum
   storage — except EIE (sparse, 128KB/PE for CSC format) and TPU (28MB weight FIFO dominates).

4. **Community-default for simulation**: Timeloop/MAESTRO/ZigZag/Interstellar all converge on ~2–8KB per-PE
   scratchpad and 64–512KB global buffer as their reference configurations.

5. **Output/psum buffer sizing**: Most consistently sized 2–3× smaller than input buffer in edge/simulation designs.

6. **Simulators over-provision**: SCALE-Sim's default 512KB per buffer is unrealistically large for small PE arrays
   but is intended to avoid bandwidth bottlenecks in simulation sweeps.
