#!/usr/bin/env python3
"""Shared helpers for parsing SNN CoSA sweep output (.txt) files.

Each sweep writes one .txt file per (arch, workload) pair. The format is:

  best: <mode_name>
  #1* <mode_name>    ← starred = best
    dram: KH=2 → T=4 → ...
    gb:   CIN=16 → ...
    sp:   HO=4 T=4
    util/cap: weight=4.0KB/240.0KB ...
  #2  <other_mode>
    ...

Public API
----------
extract_best_block(text, lines)  →  (best_mode, block_lines)
classify_t_in_loop(line)         →  "oooo" | "ooot" | "xxxt" | "ootk"
sp_dims(sp_line)                 →  "HO+T" | "none" | ...
kb_str_to_int(s)                 →  int bytes  (e.g. "256kb" → 262144)
parse_bytes_str(s)               →  float bytes (e.g. "4.0 KB" → 4096.0)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def extract_best_block(text: str, lines: List[str]) -> Tuple[str, List[str]]:
    """Return (best_mode, block_lines) from a sweep output file.

    block_lines are the stripped content lines inside the starred #N* block,
    up to (but not including) the next #N line. Returns ("", []) if the
    file has no 'best:' line or the starred block is not found.
    """
    bm = re.search(r"^best:\s+(\S+)", text, re.MULTILINE)
    if not bm:
        return "", []
    best = bm.group(1)

    bs = None
    for i, line in enumerate(lines):
        if re.match(r"\s*#\d+\*\s+" + re.escape(best), line):
            bs = i
            break
    if bs is None:
        return best, []

    block: List[str] = []
    for line in lines[bs + 1:]:
        s = line.strip()
        if re.match(r"#\d+", s):
            break
        block.append(s)
    return best, block


def classify_t_in_loop(line: str) -> str:
    """Classify where T appears in a 'dram:' or 'gb:' loop line.

    Returns one of:
      'oooo'  — T absent from the line
      'ooot'  — T is the only dimension in the loop
      'xxxt'  — T is the outermost (last) position with other dims present
      'ootk'  — T is present but not outermost (middle or first with others)
    """
    body = re.sub(r"^\s*\w+:\s*", "", line).strip()
    if not body or body.lower() == "none":
        return "oooo"
    parts = [p.strip() for p in body.split("→") if p.strip()]
    t_idx = [i for i, p in enumerate(parts) if re.match(r"T=", p)]
    if not t_idx:
        return "oooo"
    if len(parts) == 1:
        return "ooot"
    return "xxxt" if t_idx[-1] == len(parts) - 1 else "ootk"


def sp_dims(sp_line: str) -> str:
    """Normalize a 'sp:' line to sorted dimension names.

    Example: "sp: HO=4 T=4" → "HO+T"
    """
    body = re.sub(r"^\s*sp:\s*", "", sp_line).strip()
    if not body or body.lower() == "none":
        return "none"
    dims = sorted(re.findall(r"([A-Z][A-Z0-9]*)\s*=\s*\d+", body))
    return "+".join(dims) if dims else "none"


def kb_str_to_int(s: str) -> int:
    """Parse an arch-key KB string (e.g. '256kb') to bytes."""
    m = re.match(r"(\d+)kb", s.lower())
    return int(m.group(1)) * 1024 if m else 0


def parse_bytes_str(s: str) -> float:
    """Parse a human-readable bytes string (e.g. '4.0 KB') to float bytes."""
    m = re.match(r"([\d.]+)\s*(B|KB|MB|GB)", s.strip())
    if not m:
        return 0.0
    return float(m.group(1)) * {"B": 1, "KB": 1024, "MB": 2**20, "GB": 2**30}[m.group(2)]


def parse_traffic_per_var(block: List[str]) -> Optional[Dict[str, float]]:
    """Parse 'traffic/: weight=X  psum=Y  vmem=Z' from best-block lines.

    Returns None if the line is absent (old-format files lack it).
    """
    for line in block:
        if line.startswith("traffic/:"):
            body = re.sub(r"^traffic/:\s*", "", line).strip()
            result: Dict[str, float] = {}
            for m in re.finditer(r"(\w+)=([\d.]+)\s*(B|KB|MB|GB)", body):
                name, num, unit = m.group(1), float(m.group(2)), m.group(3)
                result[name] = num * {"B": 1, "KB": 1024, "MB": 2**20, "GB": 2**30}[unit]
            return result if result else None
    return None


__all__ = [
    "extract_best_block",
    "classify_t_in_loop",
    "sp_dims",
    "kb_str_to_int",
    "parse_bytes_str",
    "parse_traffic_per_var",
]
