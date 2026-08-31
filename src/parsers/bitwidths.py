#!/usr/bin/env python3
"""Step 2 – Parse variable-specific bit widths from an arch YAML.

Expected arch YAML format::

    arch:
      bitwidths:
        BW_WEIGHT: 8    # bits per weight element
        BW_PSUM:   32   # bits per partial-sum element
        BW_VMEM:   16   # bits per membrane-potential element
        DRAM_LATENCY: 17  # per-packet DRAM access latency multiplier
      ...               # remaining arch fields (memory hierarchy, etc.)

Missing keys fall back to the defaults defined below, so a minimal arch file
that omits ``bitwidths`` entirely is still valid.

Traffic multipliers (used in later steps):
  WeightTraffic = 1 * weight_factor * BW_WEIGHT   (load only)
  PsumTraffic   = 2 * psum_factor   * BW_PSUM     (load + store)
  VmemTraffic   = 2 * vmem_factor   * BW_VMEM     (load + store)
"""

import logging
import pathlib
from typing import Dict

import yaml

logger = logging.getLogger(__name__)

# Defaults used when a key is absent from the YAML
_DEFAULT_BW_WEIGHT: int = 8
_DEFAULT_BW_PSUM:   int = 32
_DEFAULT_BW_VMEM:   int = 32
_DEFAULT_DRAM_LATENCY: float = 0.25


def parse_snn_bitwidths(arch_path: pathlib.Path) -> "SNNBitwidths":
    """Parse per-variable bit widths from *arch_path*.

    Args:
        arch_path: Path to an arch YAML containing an ``arch.bitwidths`` block.

    Returns:
        SNNBitwidths populated with validated bit-width integers.

    Raises:
        FileNotFoundError: If *arch_path* does not exist.
        ValueError: If the YAML lacks a top-level ``arch`` key, or if any
                    bit width is not a positive integer.
    """
    return SNNBitwidths(arch_path)


class SNNBitwidths:
    """Per-variable bit widths for the SNN memory-traffic model.

    Attributes:
        bw_weight (int): Bits per weight element.   Default 8.
        bw_psum   (int): Bits per partial-sum element. Default 32.
        bw_vmem   (int): Bits per membrane-potential element. Default 16.
        dram_latency (float): Cycles the DRAM port is OCCUPIED per 256-bit
            (32-byte) packet, used by the NoC simulator.

            Set it from a clock and a bandwidth:  32 B x f / BW.
            Invert it to read one back:           BW = 32 B x f / dram_latency.

            Default 0.25: 64 GB/s at 500 MHz. Fractional values are the
            normal case, since any port moving more than one packet per
            cycle lands below 1. The value is NOT rounded -- rounding 0.25
            to an int would be a 4x error in the modelled bandwidth. The
            PRODUCT size * dram_latency is ceiled instead, once per
            transaction, so the rate stays exact and the error is at most
            one cycle per transaction.

            This is an occupancy, not an access latency. A real controller
            overlaps outstanding requests, so access latency belongs at the
            ramp, not on every packet. The old default of 17 was a CoSA
            analytic-metric coefficient, never a cycle count: it implied
            1.88 GB/s at 1 GHz and made every layer DRAM-bound.
        path (pathlib.Path): Resolved path to the source arch YAML.
    """

    # Canonical key names expected in arch.bitwidths
    _KEYS: Dict[str, int] = {
        "BW_WEIGHT": _DEFAULT_BW_WEIGHT,
        "BW_PSUM":   _DEFAULT_BW_PSUM,
        "BW_VMEM":   _DEFAULT_BW_VMEM,
        "DRAM_LATENCY": _DEFAULT_DRAM_LATENCY,
    }

    def __init__(self, arch_path: pathlib.Path) -> None:
        self.path = pathlib.Path(arch_path).resolve()
        if not self.path.exists():
            raise FileNotFoundError(
                f"SNNBitwidths: arch config not found: {self.path}"
            )

        with open(self.path, "r") as f:
            raw = yaml.safe_load(f)

        if "arch" not in raw:
            raise ValueError(
                f"SNNBitwidths: YAML at {self.path} must have a top-level 'arch' key"
            )

        bw_block = raw["arch"].get("bitwidths", {})

        self.bw_weight: int = int(bw_block.get("BW_WEIGHT", _DEFAULT_BW_WEIGHT))
        self.bw_psum:   int = int(bw_block.get("BW_PSUM",   _DEFAULT_BW_PSUM))
        self.bw_vmem:   int = int(bw_block.get("BW_VMEM",   _DEFAULT_BW_VMEM))
        # Fractional on purpose: at any clock where the port moves more than
        # one packet per cycle this is below 1, and rounding it to an int
        # would be a 4x error at 0.25. The product is what gets rounded,
        # once per transaction, in EventSim.h and generator.py.
        self.dram_latency: float = float(bw_block.get("DRAM_LATENCY", _DEFAULT_DRAM_LATENCY))

        for name, val in [
            ("BW_WEIGHT", self.bw_weight),
            ("BW_PSUM",   self.bw_psum),
            ("BW_VMEM",   self.bw_vmem),
            ("DRAM_LATENCY", self.dram_latency),
        ]:
            if val <= 0:
                raise ValueError(
                    f"SNNBitwidths: {name}={val} in {self.path} "
                    f"must be positive"
                )

        logger.debug(
            "SNNBitwidths: BW_WEIGHT=%d  BW_PSUM=%d  BW_VMEM=%d  DRAM_LATENCY=%g",
            self.bw_weight, self.bw_psum, self.bw_vmem, self.dram_latency,
        )

    def print(self) -> None:
        print(
            f"SNNBitwidths(bw_weight={self.bw_weight}, "
            f"bw_psum={self.bw_psum}, bw_vmem={self.bw_vmem}, "
            f"dram_latency={self.dram_latency})"
        )
