"""Prosperity (Product-Sparsity SNN accelerator) ArchComputeModel plugin
-- pilot.

Reconstructs Prosperity's per-tile ProSparsity-compressed row sequence
from a real trace (reconstruct.py), then derives the pipeline cycle count
(cycles.py) and the ordered weight-address stream / weight_access_count
(address.py) from it. Standalone-verified against the pilot's own
hand-built worked example (reproducing Wei et al.'s own Fig. 1(d)/Fig. 2
canonical 6-row/4-column illustration exactly) and against a real
captured LoAS trace (input_trace/loas/) used purely as sample spike data.

This deployment fixes: tile size m=256 (HO=16, WO=16), k=16 (KH=4, KW=4,
CIN barred -- one input channel per node visit), n=128 (COUT), per Wei,
Guo, Cheng, Li, Yang, Li & Chen, "Prosperity: Accelerating Spiking Neural
Networks via Product Sparsity" (HPCA 2025), Table III's own evaluated
config -- this pilot's node size was given to match that table exactly,
not chosen independently. Unlike SpinalFlow/PTB/LoAS (HO/WO barred
entirely) and like GustavSNN, HO/WO ARE node-level resident here -- but
unlike GustavSNN's HO, neither HO nor WO is a spatial (parallel-PE) axis:
Prosperity's row-wise dataflow (Section V-E) processes the tile's rows
strictly SEQUENTIALLY through one shared 128-wide PE array (parallel only
across COUT/N), so HO and WO are both plain capped, non-spatial
node_dim_capacity entries -- see reconstruct.py's module docstring and
configs/arch/prosperity.yaml for the full rationale.
"""
