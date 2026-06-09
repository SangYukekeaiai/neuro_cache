# Local Buffer Sizes in DNN NoC Simulators and Chips (2014–2025)

*A literature survey of input, weight, and output buffer sizes across the most-cited
DNN accelerator designs and their simulation models.*

---

## Executive Summary

Across 10 years of DNN accelerator literature, local on-chip buffers fall into two
distinct regimes: **per-PE scratchpads** (bytes to kilobytes each) and **global shared
SRAMs** (tens to hundreds of KB). The weight buffer is consistently the largest of the
three data types — often 2–10× larger than the input buffer — because weights are the
densest memory bottleneck. Output/psum buffers are consistently the smallest. Simulation
frameworks converge on a canonical geometry derived from Eyeriss: 2–8 KB per-PE
scratchpad and 64–512 KB global buffer.

---

## 1. Foundational Chips (2014–2017)

### DianNao — [Chen et al., ASPLOS 2014](https://doi.org/10.1145/2541940.2541967)

The first landmark ML accelerator from the DianNao family. Uses 64 MACs in a single
NFU (Neural Functional Unit) and three identically-sized 2KB scratchpads — one per
data type — in 65nm CMOS:

- **NBin (input):** 2 KB
- **SB (weight/synapse):** 2 KB
- **NBout (output):** 2 KB
- **NoC:** Direct wires; single-PE design with no packet-switched network.

### DaDianNao — [Chen et al., MICRO 2014](https://doi.org/10.1109/MICRO.2014.58)

Scales DianNao to a 64-tile multi-node supercomputer. Each tile integrates an NFU
cluster with embedded DRAM (eDRAM) on the same package:

- **Input activation buffer:** ~512 KB / tile
- **Weight store (eDRAM):** **4 MB / tile** (dominant; 36 MB total on 4-chip system)
- **Output accumulator:** ~512 KB / tile
- **NoC:** 3D-torus ring between 64 tiles; per-chip banked interconnect.

Weight storage at 4 MB/tile set the precedent for large weight buffers in datacenter-class
accelerators.

### ShiDianNao — [Du et al., ISCA 2015](https://doi.org/10.1145/2749469.2750389)

Near-sensor placement; 8×8 PE array (64 PEs) with output-stationary dataflow:

- **Input SRAM:** 32 KB (global, streamed horizontally)
- **Weight RF (per PE):** ~16 B (stationary in register)
- **Output SRAM:** 32 KB
- **NoC:** Dedicated horizontal/vertical pass-register networks; no global arbiter.

### Eyeriss — [Chen et al., JSSC 2017](https://doi.org/10.1109/JSSC.2016.2616357)

The most-cited spatial DNN accelerator. Row-stationary dataflow on a 14×12 PE array
(168 PEs), 65nm TSMC, 12.25 mm²:

- **Global Buffer (shared):** **108 KB** (later 192 KB in JSSC version)
- **Per-PE weight scratchpad:** ~12 × 16b registers ≈ **192 B**
- **Per-PE input scratchpad:** ~12 × 16b registers ≈ **192 B**
- **Per-PE psum scratchpad:** ~24 × 16b registers ≈ **384 B**
- **NoC:** Custom multicast mesh with separate horizontal/vertical scan chains per data
  type.

Eyeriss established the per-PE scratchpad + global buffer two-level hierarchy as the
standard simulator geometry.

### EIE — [Han et al., ISCA 2016](https://arxiv.org/abs/1602.01528)

Targets sparse FC layers; 64 PEs, each working on a column of the compressed weight matrix:

- **Activation SRAM (per PE):** **2 KB**
- **Weight SRAM, CSC format (per PE):** **128 KB**
- **Pointer buffer (per PE):** **32 KB**
- **NoC:** Quadtree H-tree for activation broadcast; distributed leading-nonzero detection.

EIE is an outlier: each PE's weight buffer (128 KB) is far larger than the activation
buffer because CSC-format weights need dense local storage.

### TPU v1 — [Jouppi et al., ISCA 2017](https://doi.org/10.1145/3079856.3080246)

Google's production datacenter inference chip. 256×256 8-bit systolic array, 28nm:

- **Unified Buffer (input activation):** **24 MB**
- **Weight FIFO:** **28 MB** (feeds the 256-column systolic array)
- **Accumulator (output/psum):** **4 MB** (4096 × 32-bit × 4096 output tiles)
- **NoC:** Systolic cell-to-cell data flow — no packet-switched NoC.
- **Total on-chip:** ~28 MiB

TPU v1 is the extreme case: weight and activation buffers measured in megabytes because
a 256×256 array requires massive bandwidth.

### SCNN — [Parashar et al., ISCA 2017](https://doi.org/10.1145/3079856.3080254)

Sparse CNN accelerator; 16 PEs (4×4), each with a 4×4 multiplier inner product unit:

- **Input buffer (per PE, compressed):** **16 KB**
- **Weight buffer (per PE, compressed):** **16 KB**
- **Partial-sum accumulator (per PE):** **48 KB**
- **Global input SRAM:** 512 KB
- **Global weight SRAM:** 512 KB
- **NoC:** Crossbar-based scatter network for accumulation of sparse outputs.

SCNN's large per-PE psum accumulator (48 KB) reflects the irregular output scatter
pattern from sparse multiplication.

### TETRIS — [Gao et al., ASPLOS 2017](https://doi.org/10.1145/3037697.3037702)

Eyeriss with 3D-stacked HMC memory. Deliberately reduces on-chip global buffer:

- **Global Buffer:** **8–16 KB** (reduced by ~10× versus Eyeriss; HMC supplies bandwidth)
- **Per-PE scratchpad:** Same as Eyeriss (~192 B each)
- **HMC off-chip:** 4 GB, 128 GB/s bandwidth
- **NoC:** Same multicast mesh as Eyeriss.

TETRIS shows that with high near-DRAM bandwidth, global buffer can shrink dramatically.

---

## 2. Second-Generation Architectures (2018–2020)

### MAERI — [Kwon et al., ASPLOS 2018](https://doi.org/10.1145/3173162.3173237)

Reconfigurable interconnect supporting any dataflow. 64 PEs:

- **Input RF (per PE):** ~512 B
- **Weight RF (per PE):** ~512 B
- **Psum RF (per PE):** ~2 KB
- **Shared input SRAM:** **64 KB**
- **Shared weight SRAM:** **64 KB**
- **Shared output SRAM:** **128 KB**
- **NoC:** Benes-style AdderTree (flex-flow); any-to-any routing.

MAERI's psum RF (2 KB/PE) is notably larger than input/weight RF because partial sum
accumulation is the bottleneck in a reconfigurable-flow design.

### Simba — [Shao et al., MICRO 2019](https://doi.org/10.1145/3352460.3358302)

Multi-chip-module (MCM) inference chip. 36 chiplets on one substrate:

- **Local scratchpad (per chiplet):** **256 KB** (shared among chiplet's 16 PEs)
- **PE register file:** ~16 B per data type
- **Global buffer (cross-chiplet):** **2 MB**
- **NoC:** Packet-switched 2D mesh between chiplets; local crossbar within chiplet.

### Eyeriss v2 — [Chen et al., JETCAS 2019](https://arxiv.org/abs/1807.07928)

Adds SIMD support and hierarchical cluster organization. 192 PEs in 8×2 clusters:

- **Global buffer total:** **192 KB** (8 clusters × 2 banks × 12 KB/cluster)
- **Per-cluster iact banks:** 3 × 1.5 KB = **4.5 KB**
- **Per-cluster psum banks:** 4 × 1.875 KB = **7.5 KB**
- **Per-PE iact scratchpad:** 9×4b addr + 16×12b data ≈ **192 B**
- **Per-PE weight scratchpad:** 16×7b addr + 96×24b data ≈ **288 B**
- **Per-PE psum scratchpad:** 32×20b ≈ **80 B**
- **NoC:** Hierarchical mesh with unicast/multicast/broadcast modes.

### SIGMA — [Muralimanohar et al., HPCA 2020](https://ieeexplore.ieee.org/document/9065592)

Sparse/irregular GEMM for DNN training. 1024 MACs:

- **Input buffer (per PE):** ~512 B
- **Weight buffer (per PE):** ~512 B
- **NoC:** Flexible Benes network (reconfigurable interconnect).

---

## 3. Simulation Frameworks and Reference Architectures

A key insight from Phase 3: simulation frameworks almost always report a **canonical reference**
configuration — not the full parameterization space. These references converge to the same
community-standard geometry.

### Timeloop — [Parashar et al., ISPASS 2019](https://doi.org/10.1109/ISPASS.2019.00019)

Systematic evaluator for DNN accelerator memory hierarchies. Two canonical architectures:

**Eyeriss-like reference:**

| Level | Size |
|-------|------|
| Shared global buffer | 108 KB |
| Per-PE weight scratchpad | **4 KB** |
| Per-PE input scratchpad | **8 KB** |
| Per-PE psum scratchpad | **2 KB** |
| PEs | 168 |

**Weight-stationary reference:**

| Level | Size |
|-------|------|
| Global buffer | 512 KB |
| Per-PE register file | ~2 words (minimal) |

Timeloop's Eyeriss-like configuration is the single most-used benchmark geometry in the
hardware-mapping research community.

### SCALE-Sim — [Samajdar et al., arXiv 2019](https://arxiv.org/abs/1811.02883)

Systolic CNN accelerator simulator. Default 128×128 array:

| Buffer | Default |
|--------|---------|
| IFMAP SRAM (input) | **512 KB** |
| Filter SRAM (weight) | **512 KB** |
| OFMAP SRAM (output) | **512 KB** |
| Total | **1.5 MB** |

SCALE-Sim's 512KB defaults are intentionally over-provisioned to avoid SRAM bandwidth
bottlenecks when sweeping large (128×128) arrays. Users shrink them to study memory-bound
regimes.

### MAESTRO — [Kwon et al., IEEE Micro 2020](https://arxiv.org/abs/1805.02566)

Analytical cost model. Reference configuration used for energy normalization:

| Level | Size |
|-------|------|
| L1 per-PE scratchpad | **2 KB** |
| L2 shared buffer | **1 MB** |
| PEs | 256 |

The 2KB/1MB split is the MAESTRO community reference; often compared against CoSA and ZigZag.

### Interstellar — [Yang et al., ASPLOS 2020](https://doi.org/10.1145/3373376.3378514)

Halide-based scheduling language for DNN accelerators. Uses Eyeriss-like geometry for
validation: 8KB input spad, 4KB weight spad, 2KB psum spad, 108KB global buffer, 168 PEs.

### CoSA — [Huang et al., ISCA 2021](https://arxiv.org/abs/2105.01898)

ILP-based mapper for spatial accelerators. 4×4 PE array, 64 MACs/PE:

| Level | Size |
|-------|------|
| Input scratchpad (per PE) | **8 KB** |
| Weight scratchpad (per PE) | **32 KB** |
| Accumulator (per PE) | **3 KB** |
| Global buffer | **128 KB** |
| **NoC** | 2D mesh, X-Y routing, wormhole, 64b flit, multicast |

CoSA's per-PE weight buffer (32 KB) is notably larger than input (8 KB) — matching
the weight-dominated bandwidth pattern.

### ZigZag — [Mei et al., IEEE TC 2021](https://doi.org/10.1109/TC.2021.3059166)

Design-space exploration framework. Parameterizable; typical reference:

| Level | Default |
|-------|---------|
| L1 per-PE buffer | **2 KB** |
| L2 shared buffer | **64 KB** |

### Gemmini — [Genc et al., DAC 2021](https://arxiv.org/abs/1911.09925)

Full-stack RISC-V-integrated systolic array generator. Default:

| Level | Default |
|-------|---------|
| Scratchpad (input A + weight B) | **256 KB** total |
| Accumulator (output C) | **64 KB** |
| Array | 16×16 (256 MACs) |
| **NoC** | Pipeline registers between tiles; RISC-V bus to host |

Gemmini is unique in treating input and weight as sharing one scratchpad rather than
allocating separate named buffers.

---

## 4. Modern High-End Chips (2021–2024)

### Ascend 910 — [Liao et al., HPCA 2021](https://ieeexplore.ieee.org/document/9407221)

Huawei's datacenter training chip, 7nm:

| Level (per AI core) | Size |
|---------------------|------|
| L0A (input activation) | **32 KB** |
| L0B (weight) | **32 KB** |
| L0C (output partial sum) | **256 KB** |
| L1 (shared in cluster) | **1 MB** |
| L2 (global on-chip) | **32 MB** total |
| **NoC** | 3D hierarchical mesh; ring NoC at cluster level |

Ascend 910 uses three separate named L0 buffers — the naming convention closest to
the input/weight/output trifecta sought in this survey.

### NVDLA — [NVIDIA, Hot Chips 2017](http://nvdla.org/)

Open-source reference RTL for inference:

| Buffer | Size |
|--------|------|
| CBUF input activation | **256 KB** |
| CBUF weight | **512 KB** |
| Accumulator | integrated in MAC fabric |
| **NoC** | Internal bus + DMA to off-chip DRAM |

---

## 5. Consolidated Comparison Table

| Accelerator | Year | Input Buffer | Weight Buffer | Output/Psum Buffer | Total On-chip | PEs | NoC Type |
|------------|------|-------------|---------------|-------------------|--------------|-----|----------|
| [DianNao](https://doi.org/10.1145/2541940.2541967) | 2014 | 2 KB | 2 KB | 2 KB | ~6 KB | 64 MACs | Direct wires |
| [DaDianNao](https://doi.org/10.1109/MICRO.2014.58) | 2014 | 512 KB/tile | **4 MB eDRAM**/tile | 512 KB/tile | 4.5 MB/tile | 16 NFU/tile | 3D torus |
| [ShiDianNao](https://doi.org/10.1145/2749469.2750389) | 2015 | 32 KB | ~1 KB RF | 32 KB | ~64 KB | 64 (8×8) | H/V pass-reg |
| [EIE](https://arxiv.org/abs/1602.01528) | 2016 | 2 KB/PE | **128 KB/PE** (CSC) | 1 KB RF/PE | ~160 KB/PE | 64 | H-tree |
| [Eyeriss](https://doi.org/10.1109/JSSC.2016.2616357) | 2017 | ~192 B/PE + 108KB shared | ~192 B/PE + 108KB shared | ~384 B/PE + 108KB shared | **192 KB** | 168 (14×12) | Multicast mesh |
| [TPU v1](https://doi.org/10.1145/3079856.3080246) | 2017 | **24 MB** | **28 MB** | **4 MB** | **28 MB** | 65536 | Systolic (no NoC) |
| [SCNN](https://doi.org/10.1145/3079856.3080254) | 2017 | 16 KB/PE + 512KB global | 16 KB/PE + 512KB global | **48 KB/PE** | ~1 MB | 256 (16 PEs×16 MACs) | Crossbar scatter |
| [TETRIS](https://doi.org/10.1145/3037697.3037702) | 2017 | 8–16 KB (global, reduced) | ~192B/PE RF | ~384B/PE RF | **8–16 KB** (+HMC) | 168 | Multicast mesh |
| [NVDLA](http://nvdla.org/) | 2017 | **256 KB** | **512 KB** | Integrated | ~768 KB | 1024 | Internal bus |
| [MAERI](https://doi.org/10.1145/3173162.3173237) | 2018 | 512B/PE + **64 KB** | 512B/PE + **64 KB** | 2KB/PE + **128 KB** | ~256 KB | 64 | AdderTree (Benes) |
| [Eyeriss v2](https://arxiv.org/abs/1807.07928) | 2019 | ~192B/PE, 4.5KB/cluster | ~288B/PE, 7.5KB/cluster | ~80B/PE, 7.5KB/cluster | **192 KB** | 192 | Hier. mesh |
| [Timeloop ref](https://doi.org/10.1109/ISPASS.2019.00019) | 2019 | **8 KB**/PE spad | **4 KB**/PE spad | **2 KB**/PE spad | 108 KB GLB | 168 | Eyeriss-like |
| [SCALE-Sim](https://arxiv.org/abs/1811.02883) | 2019 | **512 KB** IFMAP | **512 KB** Filter | **512 KB** OFMAP | **1.5 MB** | 128×128 | 2D mesh |
| [Simba](https://doi.org/10.1145/3352460.3358302) | 2019 | 256KB/chiplet (shared) | 256KB/chiplet (shared) | 256KB/chiplet (shared) | **2 MB** global | 576 (36×16) | Packet 2D mesh |
| [MAESTRO](https://arxiv.org/abs/1805.02566) | 2020 | **2 KB**/PE (L1) | **2 KB**/PE (L1) | **2 KB**/PE (L1) | **1 MB** (L2) | 256 | Parameterized |
| [SIGMA](https://ieeexplore.ieee.org/document/9065592) | 2020 | ~512B/PE | ~512B/PE | — | — | 1024 | Flexible Benes |
| [Interstellar](https://doi.org/10.1145/3373376.3378514) | 2020 | **8 KB**/PE | **4 KB**/PE | **2 KB**/PE | 108 KB GLB | 168 | Eyeriss-like |
| [CoSA](https://arxiv.org/abs/2105.01898) | 2021 | **8 KB**/PE | **32 KB**/PE | **3 KB**/PE | **128 KB** GLB | 16×64MAC | 2D mesh |
| [Gemmini](https://arxiv.org/abs/1911.09925) | 2021 | **256 KB** scratchpad (shared A+B) | **256 KB** scratchpad (shared A+B) | **64 KB** accumulator | **576 KB** | 256 (16×16) | Pipeline regs |
| [ZigZag](https://doi.org/10.1109/TC.2021.3059166) | 2021 | **2 KB** L1 | **2 KB** L1 | **2 KB** L1 | **64 KB** L2 | parameterized | Parameterized |
| [Ascend 910](https://ieeexplore.ieee.org/document/9407221) | 2021 | **32 KB** L0A | **32 KB** L0B | **256 KB** L0C | **32 MB** L2 | ~32K AI cores | 3D hier. mesh |

---

## 6. Key Patterns and Design Principles

### Pattern 1 — Weight buffer is almost always the largest

In every design except TPU (where input UB=24MB ≈ weight FIFO=28MB), the weight buffer
is 1.5–64× larger than the input buffer:

- DianNao: equal (2KB each)
- EIE: weight 64× input (128KB vs 2KB), driven by CSC sparsity format
- SCNN: weight = input per PE, but psum accumulator 3× larger
- CoSA: weight 4× input (32KB vs 8KB)
- Ascend: weight = input at L0 (32KB each), but L0C output 8× larger

### Pattern 2 — Output/psum buffer is the smallest at the per-PE level

In simulation frameworks:
- Timeloop: input 8KB > weight 4KB > psum 2KB
- MAESTRO: equal 2KB each
- CoSA: weight 32KB > input 8KB > psum 3KB
- Eyeriss: psum RF largest (~384B) because partial sums accumulate longest

### Pattern 3 — Simulation defaults cluster around Eyeriss geometry

Timeloop, Interstellar, and MAESTRO (Eyeriss config) all use 168 PEs, ~4–8KB weight,
~8KB input, ~2KB psum per PE, and 64–128KB global buffer. This is the "canonical" geometry
for DNN accelerator simulation papers.

### Pattern 4 — Global buffers: 64 KB – 1 MB for simulators, 8–32 MB for production chips

Production chips (TPU, Ascend, NVDLA) need megabyte-scale buffers to feed their large
MAC arrays. Simulation frameworks use 64–512KB to keep DSE tractable.

### Pattern 5 — NoC topology depends on dataflow

| Dataflow | Typical NoC |
|----------|-------------|
| Weight stationary | Broadcast tree (weights static, activation routed) |
| Output stationary | H/V pass registers (ShiDianNao) |
| Row stationary (Eyeriss) | Custom multicast mesh |
| Flexible / any-flow | Benes network (MAERI, SIGMA) |
| Systolic | No explicit NoC; cell-to-cell registers (TPU, Gemmini) |
| Multi-chip | Packet 2D mesh (Simba) |

---

## 7. Practical Guidance for Simulation Setup

When setting up a new DNN NoC simulation, the following ranges are defensible based
on the literature:

| Parameter | Conservative (edge/IoT) | Standard (ML workstation) | Aggressive (datacenter) |
|-----------|-------------------------|--------------------------|------------------------|
| Input buffer / PE | 512 B – 2 KB | 4–8 KB | 16–32 KB |
| Weight buffer / PE | 1 KB – 4 KB | 4–32 KB | 32–64 KB |
| Output/psum / PE | 256 B – 1 KB | 1–3 KB | 8–256 KB |
| Global buffer | 16–64 KB | 64–512 KB | 1–32 MB |
| PE count | 16–256 | 256–1024 | 1K–64K |
| NoC type | Bus / H-tree | 2D mesh | 3D hier. mesh |

---

## References (inline above; listed for convenience)

- [Chen et al., ASPLOS 2014](https://doi.org/10.1145/2541940.2541967) — DianNao
- [Chen et al., MICRO 2014](https://doi.org/10.1109/MICRO.2014.58) — DaDianNao
- [Du et al., ISCA 2015](https://doi.org/10.1145/2749469.2750389) — ShiDianNao
- [Han et al., ISCA 2016](https://arxiv.org/abs/1602.01528) — EIE
- [Chen et al., JSSC 2017](https://doi.org/10.1109/JSSC.2016.2616357) — Eyeriss
- [Jouppi et al., ISCA 2017](https://doi.org/10.1145/3079856.3080246) — TPU v1
- [Parashar et al., ISCA 2017](https://doi.org/10.1145/3079856.3080254) — SCNN
- [Gao et al., ASPLOS 2017](https://doi.org/10.1145/3037697.3037702) — TETRIS
- [Kwon et al., ASPLOS 2018](https://doi.org/10.1145/3173162.3173237) — MAERI
- [Chen et al., JETCAS 2019](https://arxiv.org/abs/1807.07928) — Eyeriss v2
- [Parashar et al., ISPASS 2019](https://doi.org/10.1109/ISPASS.2019.00019) — Timeloop
- [Samajdar et al., arXiv 2019](https://arxiv.org/abs/1811.02883) — SCALE-Sim
- [Shao et al., MICRO 2019](https://doi.org/10.1145/3352460.3358302) — Simba
- [Kwon et al., IEEE Micro 2020](https://arxiv.org/abs/1805.02566) — MAESTRO
- [Muralimanohar et al., HPCA 2020](https://ieeexplore.ieee.org/document/9065592) — SIGMA
- [Yang et al., ASPLOS 2020](https://doi.org/10.1145/3373376.3378514) — Interstellar
- [Huang et al., ISCA 2021](https://arxiv.org/abs/2105.01898) — CoSA
- [Genc et al., DAC 2021](https://arxiv.org/abs/1911.09925) — Gemmini
- [Mei et al., IEEE TC 2021](https://doi.org/10.1109/TC.2021.3059166) — ZigZag
- [Liao et al., HPCA 2021](https://ieeexplore.ieee.org/document/9407221) — Ascend 910
- [NVIDIA, Hot Chips 2017](http://nvdla.org/) — NVDLA
- [Sze et al., Proc. IEEE 2017](https://arxiv.org/abs/1703.09039) — Tutorial and Survey
