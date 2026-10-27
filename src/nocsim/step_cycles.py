"""The step-cycles file: one sample's per-(dram_i, noc_i) cycle counts.

Written by the weight-trace generator (save_step_cycles); read only by
nocsim (load_step_cycles, nocsim/sim.py).
"""

from __future__ import annotations

import gzip
import json
import os
import pathlib
import tempfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from weight_trace_gen import ComputeCycles

if TYPE_CHECKING:
    from snn_scheduler.artifact import ScheduleArtifact
    from weight_trace_gen.weight_trace import LayerWeightTrace


STEP_CYCLES_FORMAT = "step_cycles_v1"


def save_step_cycles(trace: LayerWeightTrace, path: pathlib.Path) -> None:
    """Writes the part of `trace` nocsim reads (load_step_cycles): the
    identity fields, the step counts, and each tile's dram_i, noc_i,
    mac_cycles and lif_cycles, as gzip-compressed JSON tagged
    `format: "step_cycles_v1"`. The weight addresses (each tile's `ticks`)
    are left out; they reach the cache simulator through the WCTS stream
    (stream_weight_trace) instead. `path` should end in .json.gz.

    Writes to a sibling temp file and os.replace()s it into place, so a
    process killed mid-write (OOM, SLURM time limit, etc.) can never leave
    a truncated file sitting at `path` -- skip-existing checks (this
    module's callers, generate_weight_traces.py) only ever see either the
    complete prior file or nothing, never a corrupted partial one."""
    doc = {
        "format": STEP_CYCLES_FORMAT,
        "arch": trace.arch,
        "trace_dir": trace.trace_dir,
        "layer_name": trace.layer_name,
        "sample_idx": trace.sample_idx,
        "workload_dims": trace.workload_dims,
        "dram_num_steps": trace.dram_num_steps,
        "noc_num_steps": trace.noc_num_steps,
        "tiles": [
            {"dram_i": t.dram_i, "noc_i": t.noc_i,
             "mac_cycles": t.mac_cycles, "lif_cycles": t.lif_cycles}
            for t in trace.tiles
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    os.close(fd)
    try:
        with gzip.open(tmp_name, "wt") as fh:
            json.dump(doc, fh)
        os.replace(tmp_name, path)
    except BaseException:
        os.unlink(tmp_name)
        raise


@dataclass(frozen=True)
class StepCycles:
    """One sample's per-(dram_i, noc_i) cycle counts, read back out of a
    saved step-cycles file, plus the identity fields needed to prove they
    belong to a given schedule.

    This is the read-side counterpart of save_step_cycles. nocsim charges
    each schedule step its own MAC time, and per ruling U31
    (src/cachesim/PROGRESS.md) it READS that number here rather than
    recomputing it from a live archmodel.

    by_step's values are already the max over that tile's cores -- the
    reduction assemble_layer_traces applies before writing (see its
    `mac_cycles = max(...)`), and the same one combine.py's "mac_count
    (all PEs, parallel)" step calls for. Nothing recomputes it here, and
    nothing could: the per-core values are not in the file.
    """

    by_step: Dict[Tuple[int, int], ComputeCycles]
    arch: str
    trace_dir: str
    layer_name: str
    sample_idx: int
    workload_dims: Dict[str, Any]
    dram_num_steps: int
    noc_num_steps: int

    def check_against(self, artifact: ScheduleArtifact, schedule) -> None:
        """Raise unless this trace was reconstructed from this schedule.

        Six fields, reported together rather than one at a time, so a
        mismatched pair names everything that disagrees in one message.
        Without this a wrong-but-well-formed pairing (right arch, right
        step counts, wrong layer) produces a plausible tc.csv with
        silently wrong cycle counts, which is the same failure shape as
        PROGRESS.md B173 and B179.

        `schedule` is a decoded Schedule (from schedule_from_strategy);
        it supplies the step counts, which the artifact only carries for
        the DRAM half.
        """
        bad: List[str] = []
        if self.arch != artifact.arch:
            bad.append(f"arch: trace={self.arch} schedule={artifact.arch}")
        if self.layer_name != artifact.layer_name:
            bad.append(
                f"layer_name: trace={self.layer_name} schedule={artifact.layer_name}"
            )
        if self.trace_dir != artifact.trace_dir:
            bad.append(
                f"trace_dir: trace={self.trace_dir} schedule={artifact.trace_dir}"
            )
        # The artifact nests the dims one level deeper than the trace does:
        # artifact.workload is {"problem": {...}} (what SNNProb parses),
        # while workload_dims IS that inner dict. Comparing the outer dicts
        # would fail on every correctly-matched pair.
        artifact_dims = artifact.workload.get("problem", artifact.workload)
        if self.workload_dims != artifact_dims:
            bad.append(f"workload dims: trace={self.workload_dims} schedule={artifact_dims}")
        if self.dram_num_steps != schedule.dram_num_steps:
            bad.append(
                f"dram_num_steps: trace={self.dram_num_steps} "
                f"schedule={schedule.dram_num_steps}"
            )
        if self.noc_num_steps != schedule.noc_num_steps:
            bad.append(
                f"noc_num_steps: trace={self.noc_num_steps} "
                f"schedule={schedule.noc_num_steps}"
            )
        if bad:
            raise ValueError(
                "weight trace does not match schedule:\n  " + "\n  ".join(bad)
            )


def load_step_cycles(path: pathlib.Path) -> StepCycles:
    """Read the per-tile cycle counts out of one sample_NNNNN.json.gz.

    Accepts both forms of that file: the step-cycles form save_step_cycles
    writes (`format: "step_cycles_v1"`), and the older full weight-trace
    form (no `format` key, each tile also carrying `ticks`, which is
    ignored). Both give the same StepCycles. Accepts a plain .json as well
    as .json.gz, so a hand-written fixture needs no compression step.

    Raises ValueError on an unknown `format`, on a duplicate (dram_i,
    noc_i), or on a tile count that disagrees with the file's own
    dram_num_steps * noc_num_steps. All three mean the producer and this
    reader disagree about the format, which is worth failing on at load
    time rather than surfacing later as a KeyError from deep inside
    combine()'s NoC loop.
    """
    path = pathlib.Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as fh:
        doc = json.load(fh)
    if doc.get("format", STEP_CYCLES_FORMAT) != STEP_CYCLES_FORMAT:
        raise ValueError(
            f"{path}: unknown format {doc['format']!r} (expected {STEP_CYCLES_FORMAT!r} or none)"
        )

    by_step: Dict[Tuple[int, int], ComputeCycles] = {}
    for tile in doc["tiles"]:
        key = (tile["dram_i"], tile["noc_i"])
        if key in by_step:
            raise ValueError(f"{path}: duplicate tile (dram_i, noc_i)={key}")
        by_step[key] = ComputeCycles(
            mac_cycles=tile["mac_cycles"], lif_cycles=tile["lif_cycles"]
        )

    expected = doc["dram_num_steps"] * doc["noc_num_steps"]
    if len(by_step) != expected:
        raise ValueError(
            f"{path}: {len(by_step)} tiles for a "
            f"{doc['dram_num_steps']}x{doc['noc_num_steps']} schedule "
            f"(expected {expected})"
        )

    return StepCycles(
        by_step=by_step,
        arch=doc["arch"],
        trace_dir=doc["trace_dir"],
        layer_name=doc["layer_name"],
        sample_idx=doc["sample_idx"],
        workload_dims=doc["workload_dims"],
        dram_num_steps=doc["dram_num_steps"],
        noc_num_steps=doc["noc_num_steps"],
    )
