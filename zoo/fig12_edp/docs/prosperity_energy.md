# Prosperity node energy plan (Fig 12, 7 nm)

Status: for user review. Parent plan: `docs/plans/2026-11-11-fig12-edp-plan.md`.
Sources: Prosperity paper (Wei et al., HPCA 2025, arXiv:2503.03379, read in
full: Secs IV-VII, Table III/IV); lays model
`src/lays/weight_trace_gen/prosperity/ProsperityGen.h` + `native_bridge.py`;
`zoo/wt500_fig3cfg/walkthroughs/prosperity.md`; `prosperity_infeasibility.md`;
`zoo/fig12_edp/docs/prosperity_base.md` (BASE needs no special energy
term; never read temporal_traffic as a count); CAVEATS P1-P3/R1-R5;
count helper `zoo/wt500_fig3cfg/stokes/prosperity_count.cpp` + S3 digest.
Scope: scratchpad/node side only (cache design deferred).

## 1. Model facts that shape the energy accounting

1. **ProSparsity is always on** in the generator (no BASE/ProSparsity
   switch; "BASE" is a scheduler traffic mode only). Dedup: rows (one per
   (ho, wo, t) position, a k = kh*kw-bit mask over kernel taps, per
   resident CIN) are stable-sorted by popcount; each row takes the most
   recent subset row as its prefix and fetches only `row XOR prefix` bits.
   mac_cycles = records = total pattern popcount (access == compute).
2. **Per-CIN walks**: the bridge expands each scheduler tile into one
   native walk per resident CIN (<= 16), so prefix histories never cross
   CIN. Tile geometry: M = ho_n*wo_n*t_n rows (8*1*T = 32..256), k = 9
   bits used on 3x3 layers, 1 bit on 1x1.
3. **Where compression acts**: only the 47 3x3 (S2) layers (~2x measured).
   On the 98 1x1/GEMM layers it is inert: records = one fetch per firing
   CIN per tile per COUT slab, closed-form (CAVEATS R1: never average the
   two classes together).
4. **Counts source**: the S3 digest retains only aggregates
   (mean/min/max/sum + a few anchor samples), not per-sample vectors.
   The exact per-sample R_p comes from the pipeline: R_p = the record
   count of the case's generated weight trace (records = native
   mac_cycles sum), emitted at gen time in every demo/full run;
   prosperity_counts.py consumes that per-case CSV and labels the
   provenance. Digest aggregates and the 1x1 closed form are
   cross-checks; sample-0 3x3 rows exist from a one-time
   prosperity_count.cpp recompute for standalone validation. Raw
   (pre-dedup) firing bits are analytic from the captures, so
   ProSparsity saving = raw_bits - R_p per layer.
5. **Infeasible cases**: prosperity has 145 pairs, not 151: A08
   (vgg16_cifar10_loas_T32) L1-L6 fail the NodeLevel psum capacity
   equality (64*T <= 1024 needs T <= 16). Figure handling is decision 5.
6. **Mode-blind accounting** per prosperity_base.md: node tiles are
   mode-invariant; compute + node-local counts from tile & capture; shared
   side from tc.csv (which carries weight movement + every-step
   k_chain/t_chain psum/vmem links) and cachesim; guard: never derive any
   count from `result.metrics.temporal_traffic`.

## 2. Counts (per capture, layer, sample)

```
N_rows = HO x WO x T x CIN            # one row per position per channel
                                      #   (front-end events; geometry only)
R_p    = records from S3 digest       # dedup'd fetches, incl. cout-slab
         (1x1: closed form)           #   factor; = native mac_cycles sum
A_p    = R_p x cout_n                 # accumulates (ProSparsity-reduced!)
raw    = S_win-style firing bits      # analytic; savings = raw - R_p
SORT   = sum over (tile,CIN) of 2*M*log2(M)   # bitonic comparisons
L      = HO x WO x COUT x T           # LIF steps (T node-resident ->
                                      #   potentials register-resident)
```

Note the contrast with the other four archs: accumulates are NOT the
universal `S_win x COUT`; ProSparsity cuts fetches AND accumulates to A_p.

## 3. Node components and per-event energies (7 nm): the full PPU

Paper PPU (Fig. 5, Table III) shrunk to the campaign node (4 PEs =
COUT spatial 4; detector geometry kept at 256x16 since M <= 256 rows and
k <= 16 bits fit our tiles exactly):

| # | Component | Geometry | Energy source | Count |
|---|-----------|----------|---------------|-------|
| 1 | Detector TCAM (ternary, double-buffered) | 256 x 16, 1 KB; ALL cells activate per search (paper: largest on-chip power) | auto_syn_pnr `tcam_256x16` (no archx entry; synthesized match-array is conservative vs custom CAM) - OR 28nm paper power scaled to 7 nm (decision 3) | N_rows searches + N_rows row-writes |
| 2 | Popcount units (8 in paper) | 16-bit popcount per row (sort key) | auto_syn_pnr `popcount16` | N_rows |
| 3 | Pruner: 256-ch proper-subset filter + argmax (prefix select) + 16-bit XOR (pattern) | one composite block | auto_syn_pnr `pruner` | N_rows each stage |
| 4 | Dispatcher: ProSparsity table + bitonic stable sorter | PS table 1.5 KB SRAM (cacti_fn); sorter compare-exchange 16-bit+idx | cacti_fn (table) + auto_syn_pnr `bitonic_cmp` | table: N_rows writes + N_rows reads; sorter: SORT comparisons |
| 5 | Processor PEs (4): 8-bit add into 16-bit psum register + bit-scan-forward decoder | per record: BSF finds next set bit; add weight into psum reg | ASAP7 add16/reg16 (existing) + auto_syn_pnr `bsf16` | A_p adds + A_p reg RMW; R_p BSF ops |
| 6 | Psum seed load (prefix output row -> psum registers) | read cout_n x 2 B from output/psum buffer per row with a prefix, repeated once per cout slab (the PE walk repeats per slab, so seeds do too) | cacti_fn psum L1 (1 KB) | <= N_rows x COUT reads (bound; decision 4) |
| 7 | Output/psum buffer writeback | campaign psum L1 1 KB (paper: 96 KB); each row's psums written once per cout slab | cacti_fn sram, tech 7 | N_rows x COUT x 2 B writes |
| 8 | L1 weight scratchpad read (spad design) | 32 KB, burst cout_n x 1 B | cacti_fn sram, tech 7 | R_p bursts |
| 9 | Spike row buffer | row bitmasks (double-buffered 8 KB in paper; campaign-sized small SRAM) | cacti_fn sram | N_rows reads (+ loads) |
| 10 | LIF array | shared lif_unit (docs/lif_unit.md), potentials register-resident (T full at node) | ASAP7 lif_unit | L x (e_lif_step_core + e_reg_rmw) |
| 11 | SFU (128 AND/OR, 32 MUL, 8 EXP, 1 DIV; transformer softmax/LayerNorm) | NOT exercised: campaign captures are the spiking GEMM/conv layers only | excluded from energy AND area, footnote (decision 2) | 0 |
| 12 | psum/vmem boundary movement | zero GB/DRAM boundary transactions (all 749 schedules); intra-step k_chain/t_chain links counted from tc.csv | tc.csv | per tc.csv |

## 3.1 Front-end blocks decomposed into primitives (user request 2026-11-12)

The big blocks stay the auto_syn_pnr synthesis targets; each decomposes
into primitives for (a) marked placeholder energies composable today from
archx's catalog (xor_bitwise, and_gate, comparator, adder_*, register) and
(b) a cross-check on the synthesis results.

| Block | Primitive inventory | Per-event composition |
|---|---|---|
| TCAM 256x16 search | ternary cell = 2 storage bits + XNOR + mask-AND; 256x16 cells (x2 double-buffered, one active); 256x 16-in AND-reduce match lines; 16 query-mask muxes | e_search = 256*16*(e_xnor+e_and) + 256*e_and16_tree + 16*e_mux (all cells active per search: the paper's top on-chip power) |
| TCAM row write | 32 storage-bit writes | e_write = 32*e_bit_wr |
| popcount16 | 15 full adders, 4-level tree (16b -> 5b) | e_popcnt16 ~= 15*e_FA |
| Pruner / subset filter | per channel: 16*(AND+NOT) + 16-in NOR-reduce + 8-bit index comparator; 256 channels | per row: 256*(16*e_and + e_nor16 + e_cmp8) |
| Pruner / argmax | binary tree over 256: 255*(5-bit cmp + 13-bit mux) | one tree pass per row |
| Pruner / XOR | 16 XOR gates | 16*e_xor per row |
| Dispatcher / PS table | stays a MEMORY: 1.5 KB SRAM via cacti_fn (not decomposed) | per access from cacti_fn |
| Dispatcher / bitonic sorter | compare-exchange = 13-bit comparator (5b popcount || 8b index key) + 2x 13-bit swap mux | e_bitonic_cmp per CE op; SORT ops per tile |
| PE / bit-scan-forward | 16-bit priority encoder + clear mask (AND) | e_bsf16 per record |

## 4. Inner-node compute energy formula

```
E_compute(layer, sample) =
    N_rows * (e_tcam_search + e_tcam_write + e_popcnt16
              + e_pruner + e_pstab_w + e_pstab_r + e_spikebuf_rd)
  + SORT   * e_bitonic_cmp
  + A_p    * (e_add16 + e_reg16_rmw)       # ProSparsity-reduced accumulate
  + R_p    * (e_bsf16 + e_l1w_rd(burst))   # L1 read: spad design only
  + N_rows * COUT * (e_psum_wr + e_psum_rd_seed_bound)
                                           # per-slab walks write/seed
                                           #   psums per slab: COUT total
                                           #   channels, not one slab
  + L      * (e_lif_step_core + e_reg_rmw)
E_leak = P_leak(node: PPU front-end + 4 PEs + LIF + buffers, SFU excluded)
         * 16 nodes * T_layer / f
```

The front-end (rows 1-4) is charged once per (tile, CIN) walk (decision
1); the PE-side psum terms (rows 6-7) repeat per cout slab because the
walk does.

## 5. archx workflow (Prosperity slice)

1. `/u/yyu9/projects/neuro_cache_wcache/zoo/archx/zoo/snn_edp/characterization/prosperity.architecture.yaml` at technology 7:
   cacti_fn for PS table/psum/spike/weight SRAMs; add16/reg16 from the
   ASAP7-synthesized verilog_modules adder/register (BITWIDTH 16);
   new auto_syn_pnr blocks: `tcam_256x16`, `popcount16`, `pruner`,
   `bitonic_cmp`, `bsf16` (worklist: see the parent plan's RTL section;
   adder/register/fifo/and_gate/multiplier now come ready-made from
   https://github.com/UnaryLab/verilog_modules).
2. Harvest -> energy_table.json keys prosperity.*.
3. `prosperity_counts.py`: N_rows/SORT/L/raw analytic from geometry +
   captures; R_p consumed from the S3 digest outputs (1x1 closed form as
   cross-check); A_p = R_p x cout_n.
4. **Validation anchor (the "well estimated" check)**: reassemble the
   paper's own config (128 PEs, 96 KB output buffer, 28 nm equivalents)
   from our per-event energies scaled 7nm->28nm and compare against
   Table IV (0.529 mm^2, 299.8 GOP/J @ 500 MHz) and the Fig. 10 power
   ordering (TCAM largest on-chip, then buffers/processor). Agreement
   within ~2x validates every shared entry; disagreement localizes the bad
   entry. Also: record-count equality vs the S3 digest cross-checks.

## 6. Resolved decisions (user)

1. **Front-end charged once per (tile, CIN) walk**: the TCAM detector,
   pruner and sorter run once and the PS table is reused across COUT
   slabs (spike patterns do not depend on the output channel). Only the
   PE walk, and therefore the psum write/seed terms (rows 6-7), repeat
   per slab.
2. **SFU excluded** from energy and area (the campaign exercises only
   the spiking GEMM path); footnote.
3. **TCAM energy synthesized** via auto_syn_pnr, validated against the
   paper's published numbers per §5.4.
4. **Seed loads charged at the upper bound** N_rows x COUT reads (every
   row of every slab loads a seed; exact prefix-hit counts are not
   recorded anywhere).
5. **A08 shows a hatched partial bar + footnote**: layers 1-6 of
   vgg16_cifar10_loas_T32 are structurally infeasible for prosperity at
   T=32 (psum capacity 64*T <= 1024 needs T <= 16), so the bar
   aggregates layers 7+ only, a different layer set than the other
   archs' A08 bars.
6. **Neuron model**: LIF, power-of-two shift leak, hard reset to 0
   (lif_unit.md); the LIF row charges the core-only lif_unit variant
   plus an external register RMW.
