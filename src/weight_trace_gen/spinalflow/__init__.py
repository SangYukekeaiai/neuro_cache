"""SpinalFlow ArchComputeModel plugin -- Phase 1 pilot.

Reconstructs SpinalFlow's per-tile spike "spine" from a real trace,
then derives MAC cycle count and the ordered weight-address stream from
it, in SpinalFlowGen.h (a port of
dump/python_reference/archmodels/spinalflow/{reconstruct,cycles,address}.py).
Standalone-verified against a
real captured LoAS trace (input_trace/loas/) used purely as sample spike
data -- LoAS's own accelerator dataflow is not modeled here.
"""
