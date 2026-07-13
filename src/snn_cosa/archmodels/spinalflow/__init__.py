"""SpinalFlow ArchComputeModel plugin -- Phase 1 pilot.

Reconstructs SpinalFlow's per-tile spike "spine" from a real trace
(reconstruct.py), then derives MAC cycle count (cycles.py) and the ordered
weight-address stream (address.py) from it. Standalone-verified against a
real captured LoAS trace (input_trace/loas/) used purely as sample spike
data -- LoAS's own accelerator dataflow is not modeled here.
"""
