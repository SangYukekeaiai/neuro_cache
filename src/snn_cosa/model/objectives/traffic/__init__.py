"""Traffic objective expression builders."""

from snn_cosa.model.objectives.traffic.spatial import compute_spatial_traffic
from snn_cosa.model.objectives.traffic.temporal import compute_temporal_traffic

__all__ = ["compute_spatial_traffic", "compute_temporal_traffic"]
