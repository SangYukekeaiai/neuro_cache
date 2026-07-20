"""GustavSNN (Column-Parallel Tick-Batch Gustavson-product SNN
accelerator) ArchComputeModel plugin -- pilot.

Reconstructs GustavSNN's per-tile, per-tick NRV-compressed column-
partition submatrix sequence from a real trace (reconstruct.py), then
derives the pipeline cycle count (cycles.py) and the ordered weight-
address stream / weight_access_count (address.py) from it. Standalone-
verified against a real captured LoAS trace (input_trace/loas/) used
purely as sample spike data, and against hand-built examples reproducing
the paper's own NRV row-skip mechanism (Fig. 7) at multiple ticks.

This deployment fixes: column-partition width P=8, 8 tiles x 8 PEs/tile
(64 PEs total), matching the paper's own Table II/Fig. 17 evaluated
config, per Hwang, Lee, Koo & Kung, "GustavSNN: Unleashing the Power of
Gustavson's Algorithm on SNN Acceleration with Column-Parallel Tick-Batch
Dataflow" (HPCA 2026), Sections IV-V. Unlike SpinalFlow/PTB/LoAS, T is
barred from NodeLevel (one node visit = one tick) and HO/WO ARE NodeLevel
resident (spatially split) -- see reconstruct.py's module docstring and
configs/arch/gustavsnn.yaml for the full rationale.
"""
