"""Shared case-manifest and shard helpers for the fig2 Slurm harness."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


SLURM_ROOT = Path(__file__).resolve().parent
CAMPAIGN_ROOT = SLURM_ROOT.parent
REPO_ROOT = CAMPAIGN_ROOT.parents[1]
DEFAULT_CASE_DIR = CAMPAIGN_ROOT / "outputs/slurm/cases"
MAX_ARRAY_SHARDS = 250
DEFAULT_TIME_LIMIT = "90:00"


def _import_campaign_modules():
    """Import the active gen_inputs.py and run.py from this campaign."""
    for import_path in (str(REPO_ROOT / "src"), str(CAMPAIGN_ROOT)):
        if import_path not in sys.path:
            sys.path.insert(0, import_path)
    import gen_inputs  # pylint: disable=import-outside-toplevel
    import run  # pylint: disable=import-outside-toplevel
    return gen_inputs, run


def campaign_modules():
    return _import_campaign_modules()


def case_tuple(case):
    if isinstance(case, dict):
        return (case["network"], case["layer"], int(case["N"]), int(case["sample"]))
    return (case[0], case[1], int(case[2]), int(case[3]))


def case_dict(case):
    network, layer, n, sample = case_tuple(case)
    return {"network": network, "layer": layer, "N": n, "sample": sample}


def case_key(case):
    return case_tuple(case)


def config_cases(networks=None):
    """Build the deterministic full case list from gen_inputs.py."""
    config, _ = campaign_modules()
    layer_workloads = config.workloads(networks=networks)
    return [
        (network, layer, n, sample)
        for network, layers in layer_workloads.items()
        for n in config.HARDWARE_SIZES
        for layer in layers
        for sample in config.SAMPLES
    ]


def load_case_file(path):
    payload = json.loads(Path(path).read_text())
    raw_cases = payload["cases"] if isinstance(payload, dict) else payload
    return [case_tuple(case) for case in raw_cases]


def split_cases(cases, num_shards=None, cases_per_shard=None, preserve_groups=False):
    """Split cases into deterministic shards, optionally keeping batch groups whole."""
    cases = [case_tuple(case) for case in cases]
    if num_shards is None and cases_per_shard is None:
        raise ValueError("provide --num-shards or --cases-per-shard")
    if num_shards is not None and num_shards < 1:
        raise ValueError("num-shards must be positive")
    if cases_per_shard is None:
        cases_per_shard = max(1, math.ceil(len(cases) / num_shards))
    if cases_per_shard < 1:
        raise ValueError("cases-per-shard must be positive")
    if preserve_groups:
        groups = []
        for case in cases:
            key = case[:3]
            if not groups or groups[-1][0][:3] != key:
                groups.append([case])
            else:
                groups[-1].append(case)
        oversized = [len(group) for group in groups if len(group) > cases_per_shard]
        if oversized:
            raise ValueError(
                f"cases-per-shard={cases_per_shard} is smaller than a batch group ({max(oversized)} cases)"
            )
        shards = []
        current = []
        for group in groups:
            if current and len(current) + len(group) > cases_per_shard:
                shards.append(current)
                current = []
            current.extend(group)
        if current or not shards:
            shards.append(current)
        required_shards = len(shards)
    else:
        required_shards = max(1, math.ceil(len(cases) / cases_per_shard))
        shards = [cases[i * cases_per_shard:(i + 1) * cases_per_shard]
                  for i in range(required_shards)]
    if num_shards is not None and num_shards < required_shards:
        raise ValueError(
            f"{len(cases)} cases need at least {required_shards} shards at "
            f"{cases_per_shard} cases/shard, got {num_shards}"
        )
    # Never materialize empty trailing array tasks when K is larger than needed.
    num_shards = required_shards
    if num_shards > MAX_ARRAY_SHARDS:
        raise ValueError(f"num-shards={num_shards} exceeds Slurm maxsubmit limit {MAX_ARRAY_SHARDS}")
    return shards, num_shards, cases_per_shard


def shard_tag(index):
    return f"{index:04d}"


def write_manifest(output_dir, cases, shards, cases_per_shard, source="gen_inputs.py", batch_samples=False):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    shard_files = []
    for index, shard in enumerate(shards):
        filename = f"cases_{shard_tag(index)}.json"
        (output_dir / filename).write_text(json.dumps({"cases": [case_dict(c) for c in shard]}, indent=2) + "\n")
        shard_files.append({"index": index, "case_file": filename, "cases": len(shard)})
    manifest = {
        "format": 1,
        "source": source,
        "total_cases": len(cases),
        "num_shards": len(shards),
        "cases_per_shard": cases_per_shard,
        "batch_samples": batch_samples,
        "cases": [case_dict(case) for case in cases],
        "shards": shard_files,
    }
    path = output_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def load_manifest(path):
    path = Path(path)
    payload = json.loads(path.read_text())
    cases = [case_tuple(case) for case in payload["cases"]]
    if payload.get("total_cases") != len(cases):
        raise ValueError(f"manifest total_cases does not match cases: {path}")
    if payload.get("num_shards") != len(payload.get("shards", [])):
        raise ValueError(f"manifest shard metadata is incomplete: {path}")
    return payload, cases


def result_path(shard_root, index):
    tag = shard_tag(index)
    return Path(shard_root) / f"shard_{tag}" / f"results_{tag}.csv"


def case_stem(case):
    network, layer, n, sample = case_tuple(case)
    return f"{network}_n{n}_{layer}_s{sample:05d}"


def sbatch_command(manifest_dir, shard_root, num_shards, cpus=4, batch_samples=False,
                   time_limit=DEFAULT_TIME_LIMIT):
    script = SLURM_ROOT / "run_array.sbatch"
    shard_root = Path(shard_root)
    array = f"0-{num_shards - 1}%{min(num_shards, MAX_ARRAY_SHARDS)}"
    command = (
        f"sbatch --partition=normal --time={time_limit} --cpus-per-task={cpus} --array={array} "
        f"--output={shard_root}/slurm-%A_%a.out --error={shard_root}/slurm-%A_%a.err "
        f"{script} --case-dir {Path(manifest_dir)} --shard-root {shard_root}"
    )
    if batch_samples:
        command += " --batch-samples"
    return command
