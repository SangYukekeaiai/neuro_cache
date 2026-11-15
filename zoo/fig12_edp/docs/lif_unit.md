# Shared LIF unit: digital decomposition (Fig 12, 7 nm)

Status: RESOLVED 2026-11-12 by benchmark scan (user directive: use the most
common setting across all 8 benchmarks). Scan result, unanimous 8/8, from
the model sources AND the LoAS checkpoint pickles: **LIF** (never IF),
**multiplicative decay** v[t] = lambda*v[t-1] + x[t]/tau with lambda =
1 - 1/tau, **hard reset to 0** (v_reset=0.0 everywhere; never soft).
tau = 2.0 (lambda = 0.5 = 2^-1) for spikformer/sdt/spikinglm/sma_azo x2;
tau = 4/3 (lambda = 0.25 = 2^-2) for the three LoAS benchmarks.
Thresholds 1.0 (attention neurons 0.5 in the transformers): constants, no
hardware difference. Used by loas_energy.md (row 5), ptb_energy.md (LIF
sweep term), gustavsnn_energy.md (row 4; the paper's own soft-reset eval is
OVERRIDDEN by the benchmark majority), prosperity_energy.md (row 10), and
spinalflow_energy.md (leak term, now required).

## Per-step logic, V[t] = lambda*V[t-1] + I[t]; spike if V >= theta; reset

| Stage | Logic | Width | Energy entry |
|---|---|---|---|
| 1 Leak | RESOLVED: both campaign lambdas are exact powers of two (0.5, 0.25), so lambda*V is a pure arithmetic right shift: wiring plus a 2-way config mux, no subtractor, no multiplier. The input scale x/tau is folded into the weights offline (standard practice, footnote) | 32b (BW_VMEM) | e_leak ~ 0 (captured by the synthesized block) |
| 2 Integrate | adder, psum lane (16b) into V (32b) | 16->32b | e_add32 |
| 3 Threshold | comparator V >= theta (fixed theta: subtract-and-sign) | 32b | e_cmp32 |
| 4 Reset | RESOLVED hard: mux V<-0 (no subtractor) | 32b | e_reset (mux) |
| 5 State | V register RMW + 1-bit spike flop | 32b + 1b | e_reg32_rmw + e_bit |

e_lif_step = e_leak? + e_add32 + e_cmp32 + e_reset + e_reg32_rmw + e_bit

## Energy source

Preferred: synthesize the WHOLE unit as one RTL block (lif_unit) via
https://github.com/UnaryLab/auto_syn_pnr at ASAP7 (captures mux/control/glue
that a primitive sum misses). Until then: sum of ASAP7 primitive entries,
marked placeholder in energy_table.json, listed in auto_syn_pnr_worklist.

## Where it lands per arch

- LoAS: L = HO*WO*COUT*T steps (sequential scan over the T psum lanes per
  TPPE); plus the separate psum-lane read per step (e_reg16_rd).
- PTB: same L steps at the post-accumulation LIF sweep.
- SpinalFlow: per-spike op stays accumulate + compare (event-driven); the
  neuron model IS LIF, so a leak op per (neuron, timestep boundary) =
  L = HO*WO*COUT*T is ADDED to spinalflow_energy.md: the shift itself is
  wiring, so the cost is one extra register RMW per step, L * e_reg32_rmw.

## Decisions (RESOLVED 2026-11-12, benchmark-scan majority: 8/8 unanimous)

1. LIF, all benchmarks. 2. lambda in {0.5, 0.25}: power-of-two shift, no
multiplier. 3. Hard reset to 0. The single shared lif_unit RTL (one block,
auto_syn_pnr, ASAP7) uses: shift-leak (configurable k in {1,2}), 16->32b
integrate, 32b fixed-threshold compare, hard-reset mux, 32b V register +
spike flop. This unblocks all five arch dispatches.
