"""Fail-closed checks for the Figure 1 single-node count interface."""
import math


def require_no_gb(noc, operations=()):
    """Call before committing each count output; retain bad output for diagnosis."""
    required = ('gb_reads', 'gb_writes', 'weight_packet_hops', 'chain_packet_hops')
    for key in required:
        if key not in noc:
            raise ValueError(f'Figure 1 count output lacks {key}')
    for key, value in noc.items():
        if key in required or key.lower().startswith(('gb_', 'noclevel')):
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value != 0:
                raise ValueError(f'Figure 1 forbids GB/inter-node activity: {key}={value!r}')
    forbidden = [key for key in operations if key.startswith('shared.gb.')]
    if forbidden:
        raise ValueError(f'Figure 1 operation inventory contains GB rows: {forbidden}')
