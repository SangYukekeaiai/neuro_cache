"""Shared manifest, generation, and coverage helpers for the wt500 Slurm harness."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
from collections import Counter
import pathlib
import shlex
import subprocess
import sys
from typing import Any, Iterable, Iterator, Mapping, Sequence


SLURM_ROOT = pathlib.Path(__file__).resolve().parent
CAMPAIGN_ROOT = SLURM_ROOT.parent
REPO_ROOT = CAMPAIGN_ROOT.parents[1]
DEFAULT_CASE_DIR = CAMPAIGN_ROOT / "outputs/slurm/cases"
DEFAULT_CAMPAIGN_MANIFEST = CAMPAIGN_ROOT / "outputs/manifest.json"
MAX_ARRAY_SHARDS = 250
DEFAULT_TIME_LIMIT = "90:00"

ARCH_ORDER = ("loas", "ptb", "spinalflow", "prosperity", "gustavsnn")
SAMPLE_START = 0
SAMPLE_COUNT = 500
SAMPLES = tuple(range(SAMPLE_START, SAMPLE_START + SAMPLE_COUNT))
RESULT_FIELDS = ("arch", "trace_dir", "layer", "sample", "step_cycles", "wcts")


def _as_name(value: Any) -> str | None:
    """Return a trace directory name from a manifest scalar or record."""
    if isinstance(value, Mapping):
        for key in ("trace_dir", "trace", "path", "directory", "name", "id"):
            if key in value:
                return _as_name(value[key])
        return None
    if value is None:
        return None
    text = str(value).rstrip("/")
    return pathlib.Path(text).name if text else None


def _entry_is_included(entry: Mapping[str, Any]) -> bool:
    for key in ("has_solution", "feasible", "included", "runnable"):
        if key in entry and not bool(entry[key]):
            return False
    if bool(entry.get("excluded", False)) or bool(entry.get("infeasible", False)):
        return False
    status = str(entry.get("status", "")).strip().lower().replace(" ", "_")
    if status in {
        "infeasible", "excluded", "no_solution", "no_output", "failed", "error",
        "bridge_incompatible", "not_run", "exec_failed", "invalid_json", "artifact_failed",
    }:
        return False
    return not any(word in status for word in (
        "infeasible", "excluded", "no_solution", "bridge_incompatible", "not_run",
    ))


def _as_layers(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        result = []
        for name, record in value.items():
            if isinstance(record, Mapping) and not _entry_is_included(record):
                continue
            if isinstance(record, bool) and not record:
                continue
            result.append(str(name))
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value]
    return []


def _entry_arch(entry: Mapping[str, Any], inherited: str | None = None) -> str | None:
    value = entry.get("arch", entry.get("architecture", inherited))
    if isinstance(value, Mapping):
        value = value.get("name")
    return str(value) if value is not None else None


def _entry_trace(entry: Mapping[str, Any], inherited: str | None = None) -> str | None:
    for key in ("trace_dir", "trace", "capture", "benchmark", "input"):
        if key in entry:
            return _as_name(entry[key])
    return inherited


def _entry_layer(entry: Mapping[str, Any], inherited: str | None = None) -> str | None:
    for key in ("layer", "layer_name"):
        if key in entry:
            return str(entry[key])
    return inherited


def _iter_explicit_records(value: Any, arch: str | None = None,
                           trace_dir: str | None = None,
                           layer: str | None = None) -> Iterator[Mapping[str, Any]]:
    """Walk list records or an arch -> trace -> layer schedule map."""
    if isinstance(value, Mapping):
        record_arch = _entry_arch(value, arch)
        record_trace = _entry_trace(value, trace_dir)
        record_layer = _entry_layer(value, layer)
        if record_arch and record_trace and record_layer:
            yield {**value, "arch": record_arch, "trace_dir": record_trace, "layer": record_layer}
            return
        for key, child in value.items():
            next_arch, next_trace, next_layer = arch, trace_dir, layer
            if key in ARCH_ORDER and arch is None:
                next_arch = key
            elif next_arch is not None and next_trace is None:
                next_trace = _as_name(key)
            elif next_arch is not None and next_trace is not None and next_layer is None:
                next_layer = str(key)
            yield from _iter_explicit_records(child, next_arch, next_trace, next_layer)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from _iter_explicit_records(child, arch, trace_dir, layer)
    elif arch and trace_dir and layer:
        # A nested map may use a schedule path as its leaf value.
        yield {"arch": arch, "trace_dir": trace_dir, "layer": layer}


def _capture_records(payload: Mapping[str, Any]) -> list[tuple[str, list[str], Mapping[str, Any]]]:
    captures = None
    for key in ("captures", "benchmarks", "traces", "trace_dirs", "workloads"):
        if key in payload:
            captures = payload[key]
            break
    if captures is None:
        return []
    if isinstance(captures, Mapping):
        iterable = [(key, value) for key, value in captures.items()]
    elif isinstance(captures, Sequence) and not isinstance(captures, (str, bytes)):
        iterable = [(None, value) for value in captures]
    else:
        return []
    records = []
    for key, value in iterable:
        record = value if isinstance(value, Mapping) else {}
        trace_dir = _as_name(record) or _as_name(value) or _as_name(key)
        if not trace_dir:
            continue
        layers = []
        for field in ("valid_layers", "included_layers", "layers", "workloads"):
            if field in record:
                layers = _as_layers(record[field])
                if layers:
                    break
        if not layers and isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            layers = [str(item) for item in value]
        records.append((trace_dir, layers, record))
    return records


def _entry_relative_trace(entry: Mapping[str, Any]) -> str | None:
    for key in ("trace_relative_dir", "trace_relative_path", "relative_dir"):
        value = entry.get(key)
        if value is not None:
            return str(value)
    return None


def campaign_combo_records(path: pathlib.Path,
                           arches: Sequence[str] | None = None) -> list[dict[str, str]]:
    """Read feasible combo records, retaining nested input-trace locations."""
    payload = json.loads(pathlib.Path(path).read_text())
    if isinstance(payload, list):
        payload = {"combos": payload}
    if not isinstance(payload, Mapping):
        raise ValueError(f"campaign manifest must be a JSON object: {path}")
    selected_arches = set(arches or ARCH_ORDER)
    unknown = selected_arches - set(ARCH_ORDER)
    if unknown:
        raise ValueError(f"unknown architecture(s): {', '.join(sorted(unknown))}")

    records: list[Mapping[str, Any]] = []
    for key in ("combos", "schedules", "schedule_records", "solved_schedules"):
        if key in payload:
            records.extend(_iter_explicit_records(payload[key]))
            if records:
                break
    combos: list[dict[str, str]] = []
    if records:
        for record in records:
            if not _entry_is_included(record):
                continue
            arch, trace_dir, layer = _entry_arch(record), _entry_trace(record), _entry_layer(record)
            if arch in selected_arches and trace_dir and layer:
                combo = {"arch": arch, "trace_dir": trace_dir, "layer": layer}
                relative = _entry_relative_trace(record)
                if relative:
                    combo["trace_relative_dir"] = relative
                combos.append(combo)
    else:
        for trace_dir, layers, capture in _capture_records(payload):
            excluded = capture.get("excluded_layers", {})
            layers = [layer for layer in layers if layer not in excluded]
            global_arches = payload.get("architectures", payload.get("arches", ARCH_ORDER))
            if isinstance(global_arches, Mapping):
                global_arches = list(global_arches)
            for arch in global_arches:
                if str(arch) in selected_arches:
                    for layer in layers:
                        combo = {"arch": str(arch), "trace_dir": trace_dir, "layer": layer}
                        relative = _entry_relative_trace(capture)
                        if relative:
                            combo["trace_relative_dir"] = relative
                        combos.append(combo)
    if not combos and isinstance(payload.get("valid_layers"), Mapping):
        for trace_value, layers_value in payload["valid_layers"].items():
            trace_dir = _as_name(trace_value)
            for arch in ARCH_ORDER:
                if arch in selected_arches:
                    combos.extend({"arch": arch, "trace_dir": trace_dir, "layer": layer}
                                  for layer in _as_layers(layers_value))

    unique = []
    seen = set()
    for combo in combos:
        key = (combo["arch"], combo["trace_dir"], combo["layer"])
        if key not in seen:
            seen.add(key)
            unique.append(combo)
    # Stable sorting by architecture preserves manifest order inside each arch.
    unique.sort(key=lambda combo: ARCH_ORDER.index(combo["arch"])
                if combo["arch"] in ARCH_ORDER else len(ARCH_ORDER))
    return unique


def campaign_combos(path: pathlib.Path, arches: Sequence[str] | None = None) -> list[tuple[str, str, str]]:
    """Read feasible ``(arch, trace_dir, layer)`` groups from a campaign manifest."""
    return [(record["arch"], record["trace_dir"], record["layer"])
            for record in campaign_combo_records(path, arches)]


def case_tuple(case: Any) -> tuple[str, str, str, int]:
    if isinstance(case, Mapping):
        arch = case.get("arch")
        trace_dir = case.get("trace_dir", case.get("trace"))
        layer = case.get("layer", case.get("layer_name"))
        sample = case.get("sample", case.get("sample_idx"))
    else:
        arch, trace_dir, layer, sample = case
    if arch is None or trace_dir is None or layer is None or sample is None:
        raise ValueError(f"invalid case: {case!r}")
    return str(arch), _as_name(trace_dir) or str(trace_dir), str(layer), int(sample)


def case_dict(case: Any) -> dict[str, Any]:
    arch, trace_dir, layer, sample = case_tuple(case)
    result = {"arch": arch, "trace_dir": trace_dir, "layer": layer, "sample": sample}
    if isinstance(case, Mapping):
        for key in ("trace_relative_dir", "trace_relative_path", "relative_dir"):
            if case.get(key) is not None:
                result["trace_relative_dir"] = str(case[key])
                break
    return result


def case_key(case: Any) -> tuple[str, str, str, int]:
    return case_tuple(case)


def combo_key(case: Any) -> tuple[str, str, str]:
    return case_tuple(case)[:3]


def load_case_file(path: pathlib.Path) -> list[Any]:
    payload = json.loads(pathlib.Path(path).read_text())
    raw_cases = payload["cases"] if isinstance(payload, Mapping) else payload
    return [case_dict(case) if isinstance(case, Mapping) else case_tuple(case) for case in raw_cases]


def split_cases(cases: Iterable[Any], num_shards: int | None = None,
                cases_per_shard: int | None = None,
                preserve_groups: bool = True) -> tuple[list[list[Any]], int, int]:
    """Split deterministically, keeping every combo's sample group together."""
    normalized = [case_dict(case) if isinstance(case, Mapping) else case_tuple(case) for case in cases]
    if not normalized:
        raise ValueError("cannot split an empty case set")
    if num_shards is None and cases_per_shard is None:
        raise ValueError("provide --num-shards or --cases-per-shard")
    if num_shards is not None and num_shards < 1:
        raise ValueError("num-shards must be positive")
    if preserve_groups:
        groups: list[list[tuple]] = []
        for case in normalized:
            if not groups or combo_key(groups[-1][0]) != combo_key(case):
                groups.append([case])
            else:
                groups[-1].append(case)
        largest = max(len(group) for group in groups)
        if cases_per_shard is None:
            groups_per_shard = max(1, (len(groups) + num_shards - 1) // num_shards)
            cases_per_shard = largest * groups_per_shard
        if cases_per_shard < 1:
            raise ValueError("cases-per-shard must be positive")
        if largest > cases_per_shard:
            raise ValueError(
                f"cases-per-shard={cases_per_shard} is smaller than a combo group ({largest} samples)"
            )
        shards: list[list[tuple]] = []
        current: list[tuple] = []
        for group in groups:
            if current and len(current) + len(group) > cases_per_shard:
                shards.append(current)
                current = []
            current.extend(group)
        if current:
            shards.append(current)
    else:
        if cases_per_shard is None:
            cases_per_shard = max(1, (len(normalized) + num_shards - 1) // num_shards)
        if cases_per_shard < 1:
            raise ValueError("cases-per-shard must be positive")
        shards = [normalized[i:i + cases_per_shard] for i in range(0, len(normalized), cases_per_shard)]
    required_shards = len(shards)
    if num_shards is not None and num_shards < required_shards:
        raise ValueError(
            f"{len(normalized)} cases need at least {required_shards} shards at "
            f"{cases_per_shard} cases/shard, got {num_shards}"
        )
    if required_shards > MAX_ARRAY_SHARDS:
        raise ValueError(f"num-shards={required_shards} exceeds Slurm maxsubmit limit {MAX_ARRAY_SHARDS}")
    return shards, required_shards, cases_per_shard


def shard_tag(index: int) -> str:
    return f"{index:04d}"


def write_manifest(output_dir: pathlib.Path, cases: Sequence[Any], shards: Sequence[Sequence[Any]],
                   cases_per_shard: int, source: str = "campaign manifest",
                   combos: Sequence[Sequence[str]] | None = None) -> pathlib.Path:
    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized = [case_tuple(case) for case in cases]
    shard_files = []
    for index, shard in enumerate(shards):
        shard_cases = [case_dict(case) for case in shard]
        filename = f"cases_{shard_tag(index)}.json"
        (output_dir / filename).write_text(json.dumps({"cases": shard_cases}, indent=2) + "\n")
        shard_files.append({"index": index, "case_file": filename, "cases": len(shard_cases)})
    payload = {
        "format": 1,
        "source": source,
        "sample_start": SAMPLE_START,
        "sample_count": SAMPLE_COUNT,
        "samples": list(SAMPLES),
        "total_cases": len(normalized),
        "num_shards": len(shards),
        "cases_per_shard": cases_per_shard,
        "combos": [list(combo) for combo in combos] if combos is not None else [],
        "cases": [case_dict(case) for case in normalized],
        "shards": shard_files,
    }
    path = output_dir / "manifest.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def load_manifest(path: pathlib.Path) -> tuple[dict[str, Any], list[Any]]:
    path = pathlib.Path(path)
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"manifest must be an object: {path}")
    cases = [case_dict(case) if isinstance(case, Mapping) else case_tuple(case)
             for case in payload.get("cases", [])]
    if payload.get("sample_start", SAMPLE_START) != SAMPLE_START:
        raise ValueError(f"{path}: sample_start must be {SAMPLE_START}")
    if payload.get("sample_count", SAMPLE_COUNT) != SAMPLE_COUNT:
        raise ValueError(f"{path}: sample_count must be {SAMPLE_COUNT}")
    if payload.get("total_cases") != len(cases):
        raise ValueError(f"manifest total_cases does not match cases: {path}")
    if payload.get("num_shards") != len(payload.get("shards", [])):
        raise ValueError(f"manifest shard metadata is incomplete: {path}")
    counts = Counter(case_key(case) for case in cases)
    if any(count != 1 for count in counts.values()):
        raise ValueError(f"manifest contains duplicate cases: {path}")
    return payload, cases


def result_path(shard_root: pathlib.Path, index: int) -> pathlib.Path:
    tag = shard_tag(index)
    return pathlib.Path(shard_root) / f"shard_{tag}" / f"results_{tag}.csv"


def case_stem(case: Any) -> str:
    arch, trace_dir, layer, sample = case_tuple(case)
    return f"{arch}_{trace_dir}_{layer}_s{sample:05d}"


def output_relpaths(case: Any) -> tuple[pathlib.Path, pathlib.Path]:
    arch, trace_dir, layer, sample = case_tuple(case)
    stem = f"sample_{sample:05d}"
    base = pathlib.Path(arch) / trace_dir / layer
    return (pathlib.Path("step_cycles") / base / f"{stem}.json.gz",
            pathlib.Path("wcts") / base / f"{stem}.wcts.gz")


def _safe_relative(path: str | pathlib.Path) -> pathlib.Path:
    value = pathlib.Path(path)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError(f"output path must be relative and contained in its shard: {path}")
    return value


def validate_result_row(row: Mapping[str, Any], shard_dir: pathlib.Path,
                        expected_case: Any) -> None:
    key = case_key(expected_case)
    if case_key(row) != key:
        raise ValueError(f"result row case mismatch: expected {key}, got {case_key(row)}")
    expected_cycles, expected_wcts = output_relpaths(expected_case)
    if pathlib.PurePosixPath(row["step_cycles"]) != pathlib.PurePosixPath(expected_cycles.as_posix()):
        raise ValueError(f"{shard_dir}: unexpected step-cycles path for {key}: {row['step_cycles']}")
    if pathlib.PurePosixPath(row["wcts"]) != pathlib.PurePosixPath(expected_wcts.as_posix()):
        raise ValueError(f"{shard_dir}: unexpected WCTS path for {key}: {row['wcts']}")
    for field in ("step_cycles", "wcts"):
        path = shard_dir / _safe_relative(row[field])
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"{shard_dir}: missing output for {key}: {path}")


def _base_env(repo: pathlib.Path) -> dict[str, str]:
    env = os.environ.copy()
    source_root = str(pathlib.Path(repo).resolve() / "src")
    old = env.get("PYTHONPATH")
    env["PYTHONPATH"] = source_root if not old else source_root + os.pathsep + old
    return env


def _generator_command(python: str, arch: str, trace_root: pathlib.Path, trace_dir: str,
                       layer: str, schedule_cache: pathlib.Path, *, stream: bool = False,
                       sample_start: int = SAMPLE_START, sample_count: int = SAMPLE_COUNT,
                       out_dir: pathlib.Path | None = None, workers: int = 1) -> list[str]:
    command = [str(python), "-m", "lays.weight_trace_gen", "gen", "--arch", arch,
               "--trace-root", str(trace_root), "--trace-dir", trace_dir, "--layer", layer,
               "--schedule-cache", str(schedule_cache), "--sample-start", str(sample_start),
               "--sample-count", str(sample_count)]
    if stream:
        command.append("--stream")
    else:
        command.extend(("--out-dir", str(out_dir)))
        if workers > 1:
            command.extend(("--workers", str(workers)))
    return command


def _trace_root_and_dir(case: Any, trace_root: pathlib.Path) -> tuple[pathlib.Path, str]:
    """Resolve nested capture metadata without changing schedule-cache keys."""
    trace_dir = case_tuple(case)[1]
    relative = case.get("trace_relative_dir") if isinstance(case, Mapping) else None
    if not relative:
        return trace_root, trace_dir
    relative_path = pathlib.Path(str(relative))
    if relative_path.is_absolute() or ".." in relative_path.parts or relative_path.name != trace_dir:
        raise ValueError(f"invalid trace_relative_dir for {case_tuple(case)}: {relative}")
    return trace_root / relative_path.parent, trace_dir


def _write_log(path: pathlib.Path, command: Sequence[str], stdout: str, stderr: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(shlex.join([str(item) for item in command]) + "\n" + stdout + stderr)


def _run_cycles(command: Sequence[str], repo: pathlib.Path, log_path: pathlib.Path) -> None:
    result = subprocess.run(command, cwd=repo, env=_base_env(repo), text=True, capture_output=True)
    _write_log(log_path, command, result.stdout, result.stderr)
    if result.returncode:
        raise RuntimeError(
            f"cycle generation failed ({result.returncode}): {shlex.join([str(x) for x in command])}; "
            f"see {log_path}"
        )


def _run_stream(command: Sequence[str], repo: pathlib.Path, output_path: pathlib.Path,
                log_path: pathlib.Path) -> None:
    """Run one stream producer and gzip stdout without buffering WCTS in RAM."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".part")
    process = subprocess.Popen(command, cwd=repo, env=_base_env(repo),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None and process.stderr is not None
    with temporary.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            while True:
                chunk = process.stdout.read(1024 * 1024)
                if not chunk:
                    break
                compressed.write(chunk)
    process.stdout.close()
    stderr = process.stderr.read().decode(errors="replace")
    process.stderr.close()
    returncode = process.wait()
    _write_log(log_path, command, "", stderr)
    if returncode:
        raise RuntimeError(
            f"WCTS generation failed ({returncode}): {shlex.join([str(x) for x in command])}; "
            f"see {log_path}"
        )
    os.replace(temporary, output_path)


def _ordered_combos(cases: Sequence[tuple[str, str, str, int]]) -> list[tuple[str, str, str]]:
    groups = []
    seen = set()
    for case in cases:
        combo = combo_key(case)
        if combo not in seen:
            seen.add(combo)
            groups.append(combo)
    return sorted(groups, key=lambda combo: ARCH_ORDER.index(combo[0])
                  if combo[0] in ARCH_ORDER else len(ARCH_ORDER))


def run_shard(*, case_file: pathlib.Path, shard_dir: pathlib.Path, repo: pathlib.Path,
              python: str, trace_root: pathlib.Path, schedule_cache: pathlib.Path,
              workers: int = 1) -> int:
    """Generate one shard: one 500-sample cycle call plus one stream per sample."""
    cases = load_case_file(case_file)
    if not cases:
        raise ValueError(f"empty shard case file: {case_file}")
    if workers < 1:
        raise ValueError("workers must be positive")
    counts = Counter(case_key(case) for case in cases)
    if any(count != 1 for count in counts.values()):
        raise ValueError(f"duplicate cases in {case_file}")
    shard_dir = pathlib.Path(shard_dir)
    shard_dir.mkdir(parents=True, exist_ok=True)
    cycles_root = shard_dir / "step_cycles"
    logs = shard_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    tag = case_file.stem.split("_")[-1]
    results_path = shard_dir / f"results_{tag}.csv"
    grouped: dict[tuple[str, str, str], list[Any]] = {}
    for case in cases:
        grouped.setdefault(combo_key(case), []).append(case)

    with results_path.open("w", newline="") as results_file, \
            (logs / f"commands_{tag}.txt").open("w") as command_file:
        writer = csv.DictWriter(results_file, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        for arch, trace_dir, layer in _ordered_combos(cases):
            combo_cases = grouped[(arch, trace_dir, layer)]
            locations = {_trace_root_and_dir(case, trace_root) for case in combo_cases}
            if len(locations) != 1:
                raise ValueError(f"combo has inconsistent trace locations: {(arch, trace_dir, layer)}")
            combo_trace_root, combo_trace_dir = locations.pop()
            for_sample = sorted(case_tuple(case)[3] for case in combo_cases)
            cycle_command = _generator_command(
                python, arch, combo_trace_root, combo_trace_dir, layer, schedule_cache,
                sample_start=SAMPLE_START, sample_count=SAMPLE_COUNT,
                out_dir=cycles_root, workers=workers,
            )
            command_file.write(shlex.join(cycle_command) + "\n")
            command_file.flush()
            _run_cycles(cycle_command, repo, logs / f"{arch}_{trace_dir}_{layer}_cycles.log")
            for sample in for_sample:
                case = (arch, trace_dir, layer, sample)
                cycles_rel, wcts_rel = output_relpaths(case)
                cycles_path = shard_dir / cycles_rel
                if not cycles_path.is_file() or cycles_path.stat().st_size == 0:
                    raise RuntimeError(f"generator omitted step-cycles output: {cycles_path}")
                wcts_path = shard_dir / wcts_rel
                if not wcts_path.is_file() or wcts_path.stat().st_size == 0:
                    stream_command = _generator_command(
                        python, arch, combo_trace_root, combo_trace_dir, layer, schedule_cache,
                        stream=True, sample_start=sample, sample_count=1,
                    )
                    command_file.write(shlex.join(stream_command) + " | gzip\n")
                    command_file.flush()
                    _run_stream(stream_command, repo, wcts_path,
                                logs / f"{case_stem(case)}_stream.log")
                if not wcts_path.is_file() or wcts_path.stat().st_size == 0:
                    raise RuntimeError(f"stream generator omitted WCTS output: {wcts_path}")
                writer.writerow({"arch": arch, "trace_dir": trace_dir, "layer": layer,
                                 "sample": sample, "step_cycles": cycles_rel.as_posix(),
                                 "wcts": wcts_rel.as_posix()})
                results_file.flush()
    return 0


def sbatch_command(manifest_dir: pathlib.Path, shard_root: pathlib.Path, num_shards: int,
                   cpus: int = 4, trace_root: pathlib.Path | None = None,
                   schedule_cache: pathlib.Path | None = None, repo: pathlib.Path | None = None,
                   python: str | None = None, time_limit: str = DEFAULT_TIME_LIMIT) -> str:
    """Render a portable sbatch line; unset roots are shell variables."""
    script = SLURM_ROOT / "run_array.sbatch"
    array = f"0-{num_shards - 1}%{min(num_shards, MAX_ARRAY_SHARDS)}"
    fixed = ["sbatch", "--partition=normal", f"--time={time_limit}",
             f"--cpus-per-task={cpus}", f"--array={array}",
             "--output", f"{pathlib.Path(shard_root)}/slurm-%A_%a.out",
             "--error", f"{pathlib.Path(shard_root)}/slurm-%A_%a.err",
             str(script), "--case-dir", str(pathlib.Path(manifest_dir)),
             "--shard-root", str(pathlib.Path(shard_root))]
    command = shlex.join(fixed)
    command += " --trace-root " + (shlex.quote(str(trace_root)) if trace_root else '"$TRACE_ROOT"')
    command += " --schedule-cache " + (shlex.quote(str(schedule_cache))
                                      if schedule_cache else '"$SCHEDULE_CACHE"')
    command += " --repo " + (shlex.quote(str(repo)) if repo else '"$REPO"')
    command += " --python " + (shlex.quote(str(python)) if python else '"$PYTHON"')
    return command


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run-shard", help="run one manifest shard")
    run.add_argument("--case-file", type=pathlib.Path, required=True)
    run.add_argument("--shard-dir", type=pathlib.Path, required=True)
    run.add_argument("--repo", type=pathlib.Path, required=True)
    run.add_argument("--python", required=True)
    run.add_argument("--trace-root", type=pathlib.Path, required=True)
    run.add_argument("--schedule-cache", type=pathlib.Path, required=True)
    run.add_argument("--workers", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "run-shard":
        return run_shard(case_file=args.case_file, shard_dir=args.shard_dir,
                         repo=args.repo, python=args.python, trace_root=args.trace_root,
                         schedule_cache=args.schedule_cache, workers=args.workers)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
