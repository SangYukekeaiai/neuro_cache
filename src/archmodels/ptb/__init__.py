"""PTB (Parallel Time Batching) ArchComputeModel plugin -- pilot.

Reconstructs PTB's per-tile stSAP-compressed line sequence from a real
trace (reconstruct.py), then derives the pipeline cycle count (cycles.py)
and the ordered weight-address stream / weight_access_count (address.py)
from it. Standalone-verified against a real captured LoAS trace
(input_trace/loas/) used purely as sample spike data, and against hand-
built examples for the stSAP compression and pipeline-latency formulas
that the (currently T=4) real trace is too short to exercise fully.

This deployment fixes: time window size 8, 16x8 PE array (16 COUT rows x
8 time-window columns), per Lee, Zhang & Li, "Parallel Time Batching:
Systolic-Array Acceleration of Sparse Spiking Neural Computation" (HPCA
2022), Sections 4.3-4.4 and 6.1.2.
"""
