"""LoAS (Low-latency inference Accelerator for dual-Sparse SNNs)
ArchComputeModel plugin -- pilot.

Reconstructs LoAS's per-row silent-neuron-compressed input line sequence
from a real trace (reconstruct.py), then derives the pipeline cycle count
(cycles.py) and the ordered weight-address stream / weight_access_count
(address.py) from it. Standalone-verified against a real captured LoAS
trace (input_trace/loas/) and against hand-built examples reproducing the
paper's own Fig. 8 compression walkthrough.

This deployment fixes: COUT node-level spatial capacity 16, matching the
paper's own 16-TPPE evaluated config, full
NodeLevel residency for KH/KW/CIN/T (see configs/arch/loas.yaml), and
DENSE weight storage (no column-wise bitmask compression on B) -- all
explicit departures from Yin, Kim, Wu & Panda, "LoAS: Fully
Temporal-Parallel Dataflow for Dual-Sparse Spiking Neural Networks"
(MICRO 2024), Sections III-IV.
"""
