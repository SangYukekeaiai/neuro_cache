#!/usr/bin/env python3
"""Shared progress-line printer for sweep scripts."""

from __future__ import annotations

import time


def print_progress(done: int, total: int, start: float, unit: str = "pairs") -> None:
    """Print a single overwriting progress line to stdout."""
    elapsed = time.time() - start
    rate    = done / elapsed if elapsed > 0 else 0
    eta     = (total - done) / rate if rate > 0 else float("inf")
    eta_str = f"{eta/3600:.1f}h" if eta > 3600 else f"{eta/60:.1f}m"
    print(
        f"\r  [{done}/{total}] {100*done/total:5.1f}%  "
        f"{rate:.2f} {unit}/s  ETA {eta_str}  ",
        end="", flush=True,
    )


__all__ = ["print_progress"]
