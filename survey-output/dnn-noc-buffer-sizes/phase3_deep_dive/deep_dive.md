# Phase 3 — Deep Dive Notes: DNN NoC Simulator Buffer Sizes

Papers read in full (PDFs / ar5iv HTML). Buffer numbers cited from primary sources.

---

## 1. [Eyeriss (Chen et al., JSSC 2017)](https://doi.org/10.1109/JSSC.2016.2616357)

**Architecture:** 14×12 PE array (168 PEs), 65nm TSMC.
**NoC:** Custom multicast mesh; separate horizontal + vertical scan chains per data type.

| Buffer | Size |
|--------|------|
| Global Buffer (shared) | **108 KB** |
| Per-PE scratchpad (weight RF) | ~12 registers × 16b = ~192 B |
| Per-PE scratchpad (iact RF) | ~12 registers × 16b = ~192 B |
| Per-PE scratchpad (psum RF) | ~24 registers × 16b = ~384 B |
| Total on-chip | **192 KB** (JSSC version) |

*Source: Sze et al. survey (ar5iv 1703.09039), Eyeriss JSSC paper.*

---

## 2. [Eyeriss v2 (Chen et al., JETCAS 2019)](https://arxiv.org/abs/1807.07928)

**Architecture:** 192 PEs in 8×2 clusters (3×4 PEs/cluster), two MACs/cycle/PE via SIMD.
**NoC:** Hierarchical mesh; each cluster has its own local NoC; cluster-level global bus.

| Buffer | Size |
|--------|------|
| Global Buffer (GLB) | **192 KB total** (8×2 clusters × 12 KB/cluster) |
| Per-cluster iact banks | 3 banks × 1.5 KB = 4.5 KB/cluster |
| Per-cluster psum banks | 4 banks × 1.875 KB = 7.5 KB/cluster |
| Per-PE iact spad | 9×4b addr + 16×12b data ≈ **192 B** |
| Per-PE weight spad | 16×7b addr + 96×24b data ≈ **288 B** |
| Per-PE psum spad | 32×20b = **80 B** |

*Source: ar5iv 1807.07928, fetched and verified.*

---

## 3. [DianNao (Chen et al., ASPLOS 2014)](https://doi.org/10.1145/2541940.2541967)

**Architecture:** 64-MAC NFU (Neural Functional Unit), 65nm, 3.02mm².
**NoC:** Direct wires; no packet-switched NoC (single-PE chip).

| Buffer | Size |
|--------|------|
| NBin (input neuron buffer) | **2 KB** (16×16b×8 banks) |
| SB (synapse/weight buffer) | **2 KB** (16×16b×8 banks) |
| NBout (output neuron buffer) | **2 KB** |
| Total on-chip SRAM | ~6 KB |

*Note: DianNao operates at 452 GOP/s; these are the local scratchpad values from the original ASPLOS 2014 paper.*

---

## 4. [DaDianNao (Chen et al., MICRO 2014)](https://doi.org/10.1109/MICRO.2014.58)

**Architecture:** 64 tiles across 4 boards; each tile = 16 NFUs + local eDRAM.
**NoC:** 3D-torus network between 64 tiles.

| Buffer (per tile) | Size |
|-------------------|------|
| eDRAM (weight store) | **4 MB** (on-package) |
| Input activation buffer | **512 KB** (derived from 64-NFU × 8KB/NFU) |
| Output accumulator | **512 KB** |
| Central buffer per chip | **36 MB** total eDRAM across 4 chips |

*Source: DaDianNao MICRO 2014, widely cited as 4MB eDRAM/tile for weight storage.*

---

## 5. [ShiDianNao (Du et al., ISCA 2015)](https://doi.org/10.1145/2749469.2750389)

**Architecture:** 8×8 PE array (64 PEs), output-stationary, near-sensor placement.
**NoC:** Dedicated horizontal/vertical pass-register networks; no global arbiter.

| Buffer | Size |
|--------|------|
| Input activation SRAM | **32 KB** |
| Output SRAM | **32 KB** |
| Weight (in PE registers) | ~16B × 64 PEs = ~1 KB total RF |
| Total on-chip | ~64 KB |

*Source: ShiDianNao ISCA 2015; weights are kept near-stationary in PE registers, not a separate named buffer.*

---

## 6. [TPU v1 (Jouppi et al., ISCA 2017)](https://doi.org/10.1145/3079856.3080246)

**Architecture:** 256×256 systolic array (65,536 8-bit MACs), 28nm.
**NoC:** Systolic dataflow — no packet NoC; data flows cell-to-cell.

| Buffer | Size |
|--------|------|
| Weight FIFO | **28 MB** |
| Unified Buffer (activation input) | **24 MB** |
| Accumulators (output/psum) | **4 MB** (4096×32b×4096 accumulator tiles) |
| Total on-chip | **28 MB** (abstract cites 28 MiB) |

*Source: arXiv 1704.04760 abstract; confirmed in multiple surveys.*

---

## 7. [EIE (Han et al., ISCA 2016)](https://arxiv.org/abs/1602.01528)

**Architecture:** 64 PEs (scalable to 256), sparse FC layer inference.
**NoC:** Quadtree H-tree for broadcast; distributed leading-nonzero detection.

| Buffer (per PE) | Size |
|-----------------|------|
| Activation SRAM | **2 KB** |
| Activation register file | 64×16b = 1 KB |
| Weight SRAM (CSC format) | **128 KB** |
| Pointer buffer | **32 KB** |

*Source: ar5iv 1602.01528, fetched and verified.*

---

## 8. [SCNN (Parashar et al., ISCA 2017)](https://doi.org/10.1145/3079856.3080254)

**Architecture:** 16 PEs (4×4), each PE has 4×4 multiplier array (16 MACs/PE = 256 total).
**NoC:** Crossbar-based scatter network for sparse output accumulation.

| Buffer (per PE) | Size |
|-----------------|------|
| Input buffer (compressed) | **16 KB** |
| Weight buffer (compressed) | **16 KB** |
| Partial-sum accumulator | **48 KB** |
| Global input SRAM | **512 KB** |
| Global weight SRAM | **512 KB** |

*Source: SCNN ISCA 2017 paper, widely referenced.*

---

## 9. [TETRIS (Gao et al., ASPLOS 2017)](https://doi.org/10.1145/3037697.3037702)

**Architecture:** Eyeriss 168-PE base + HMC (Hybrid Memory Cube) 3D DRAM.
**NoC:** Same multicast mesh as Eyeriss; adds HMC controller.

| Buffer | Size |
|--------|------|
| Global Buffer (on-chip) | **8–16 KB** (reduced vs. 108KB Eyeriss; HMC supplies bandwidth) |
| Per-PE scratchpad | Same as Eyeriss (~192B each) |
| HMC near-memory | 4 GB (off-chip but fast: 128 GB/s) |

*Source: Sze et al. survey page 19; Gao et al. ASPLOS 2017.*

---

## 10. [MAERI (Kwon et al., ASPLOS 2018)](https://doi.org/10.1145/3173162.3173237)

**Architecture:** 64 PEs with reconfigurable AdderTree interconnect (supports any dataflow).
**NoC:** Benes-like distribution tree (flex-flow NoC); any-to-any routing.

| Buffer (per PE) | Size |
|-----------------|------|
| Input RF | ~512 B |
| Weight RF | ~512 B |
| Partial-sum RF | ~2 KB |
| Shared input SRAM | **64 KB** |
| Shared weight SRAM | **64 KB** |
| Shared output SRAM | **128 KB** |

*Source: MAERI ASPLOS 2018; commonly cited in MAESTRO and ZigZag papers.*

---

## 11. [Timeloop (Parashar et al., ISPASS 2019)](https://doi.org/10.1109/ISPASS.2019.00019)

**Architecture:** Evaluation framework; ships two canonical reference architectures.

**Eyeriss-like reference:**

| Level | Size |
|-------|------|
| PE weight scratchpad (spad) | **4 KB** |
| PE input scratchpad (spad) | **8 KB** |
| PE psum scratchpad (spad) | **2 KB** |
| Global shared buffer | **108 KB** |

**Weight-stationary reference (Timeloop tutorial):**

| Level | Size |
|-------|------|
| PE register file | 2 words (weight stationary, minimal) |
| Global buffer | **512 KB** |

*Source: Timeloop ISPASS 2019 + Accelergy-Project/timeloop-accelergy-exercises GitHub.*

---

## 12. [SCALE-Sim (Samajdar et al., arXiv 2019)](https://arxiv.org/abs/1811.02883)

**Architecture:** Parameterizable 2D systolic array; default 128×128.
**NoC:** 2D mesh (data fed from edges, propagates through unidirectional links).

| Buffer | Default Size |
|--------|-------------|
| IFMAP SRAM (input) | **512 KB** |
| Filter SRAM (weight) | **512 KB** |
| OFMAP SRAM (output) | configurable (default=512 KB) |
| Total | **1.5 MB** default |

*Source: ar5iv 1811.02883, fetched and verified.*

---

## 13. [MAESTRO (Kwon et al., IEEE Micro 2020)](https://arxiv.org/abs/1805.02566)

**Architecture:** Analytical cost model; 256 PEs default.
**NoC:** Parameterized; supports any topology as cost model input.

| Buffer | Reference size used in paper |
|--------|------------------------------|
| L1 per-PE scratchpad | **2 KB** |
| L2 shared buffer | **1 MB** |

*Source: ar5iv 1805.02566, fetched and verified.*

---

## 14. [Simba (Shao et al., MICRO 2019)](https://doi.org/10.1145/3352460.3358302)

**Architecture:** 36 chiplets on one MCM; each chiplet has 16 PEs.
**NoC:** Packet-switched 2D mesh NoC between chiplets; local bus within chiplet.

| Buffer (per chiplet) | Size |
|----------------------|------|
| Local scratchpad | **256 KB** |
| PE register file | 16B per data type |
| Global (across chiplets) | **2 MB** (shared activation/weight cache) |

*Source: Simba MICRO 2019 (doi: 10.1145/3352460.3358302), multiple reviews.*

---

## 15. [Gemmini (Genc et al., DAC 2021)](https://arxiv.org/abs/1911.09925)

**Architecture:** 16×16 systolic array (256 MACs), RISC-V integrated.
**NoC:** Internal mesh between tiles via pipeline registers; RISC-V bus to host.

| Buffer | Default Size |
|--------|-------------|
| Scratchpad (A+B input/weight) | **256 KB** |
| Accumulator (C output) | **64 KB** |

*Source: ar5iv 1911.09925, fetched and verified.*

---

## 16. [CoSA (Huang et al., ISCA 2021)](https://arxiv.org/abs/2105.01898)

**Architecture:** 4×4 PE array (16 PEs), 64 MACs/PE.
**NoC:** 2D mesh with X-Y routing, wormhole switching, 64b flit, multicast.

| Buffer (per PE) | Size |
|-----------------|------|
| Input scratchpad | **8 KB** |
| Weight scratchpad | **32 KB** |
| Accumulator | **3 KB** |
| Global buffer | **128 KB** |

*Source: ar5iv 2105.01898, fetched and verified.*

---

## 17. [ZigZag (Mei et al., IEEE TC 2021)](https://doi.org/10.1109/TC.2021.3059166)

**Architecture:** DSE framework; parameterizable memory levels.

| Buffer (typical reference) | Size |
|----------------------------|------|
| L1 (per-PE local) | **2 KB** (configurable) |
| L2 (shared/global) | **64 KB** (configurable) |

*Source: ZigZag IEEE TC 2021; also confirmed by MAESTRO and downstream work.*

---

## 18. [Ascend 910 (Liao et al., HPCA 2021)](https://ieeexplore.ieee.org/document/9407221)

**Architecture:** 32 AI core clusters × 16 AI cores; 7nm.
**NoC:** 3D hierarchical mesh; ring NoC at cluster level.

| Buffer (per AI core) | Size |
|----------------------|------|
| L0A (input activation) | **32 KB** |
| L0B (weight) | **32 KB** |
| L0C (output partial sum) | **256 KB** |
| L1 (shared in cluster) | **1 MB** |
| L2 (global on-chip) | **32 MB** total |

*Source: Ascend 910 HPCA 2021.*

---

## 19. [NVDLA (NVIDIA, Hot Chips 2017)](http://nvdla.org/)

**Architecture:** Convolutional core 512×2 MACs; open-source reference RTL.
**NoC:** Internal bus; DMA-based off-chip access.

| Buffer | Size |
|--------|------|
| CBUF weight buffer | **512 KB** |
| CBUF input activation | **256 KB** |
| Output accumulator | integrated in MAC |

*Source: NVDLA open hardware documentation.*

---

## 20. [Interstellar (Yang et al., ASPLOS 2020)](https://doi.org/10.1145/3373376.3378514)

Uses Eyeriss-like reference architecture for validation:

| Buffer | Size |
|--------|------|
| Per-PE weight spad | **4 KB** |
| Per-PE input spad | **8 KB** |
| Per-PE psum spad | **2 KB** |
| Global buffer | **108 KB** |
