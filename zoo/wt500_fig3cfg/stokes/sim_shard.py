#!/usr/bin/env python3
"""Run the four cachesim arms for one generated WT500 shard."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from collections import Counter, deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import subprocess
from typing import Iterator, Mapping, Sequence


ARMS = ("cache", "spad_oracle", "spad_wcache", "spad_nocsim")
PREFIX_FIELDS = ("arch", "trace_dir", "layer", "sample")
REQUIRED_CONFIG_FIELDS = (
    "l1_size_bytes", "l1_assoc", "l2_size_bytes", "l2_assoc",
    "cin_block", "cout_block", "weight_bytes", "layout",
)
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BINARY = REPO_ROOT / "src/lays/cachesim/native/build/release/cachesim_run"


def _read_results(shard_dir: Path) -> list[dict[str, str]]:
    files = sorted(shard_dir.glob("results_*.csv"))
    if not files:
        raise RuntimeError(f"no results_*.csv under {shard_dir}")
    rows: list[dict[str, str]] = []
    for path in files:
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise RuntimeError(f"results file has no header: {path}")
            required = ("arch", "trace_dir", "layer", "sample", "wcts")
            missing = set(required) - set(reader.fieldnames)
            if missing:
                raise RuntimeError(f"{path} is missing columns: {', '.join(sorted(missing))}")
            for row in reader:
                if any(row.get(field, "") in (None, "") for field in PREFIX_FIELDS + ("wcts",)):
                    raise RuntimeError(f"incomplete results row in {path}: {row}")
                rows.append(row)
    if not rows:
        raise RuntimeError(f"results files contain no rows under {shard_dir}")
    return rows


def _validate_config(config: Path) -> None:
    try:
        payload = json.loads(config.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot parse simulator config: {config}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"simulator config must be a JSON object: {config}")
    missing = [field for field in REQUIRED_CONFIG_FIELDS if field not in payload]
    if missing:
        raise RuntimeError(
            f"simulator config is missing required geometry fields: {', '.join(missing)}"
        )


def _wcts_path(shard_dir: Path, wcts_dir: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = shard_dir / path
    resolved = path.resolve()
    try:
        resolved.relative_to(wcts_dir.resolve())
    except ValueError as error:
        raise RuntimeError(f"WCTS path is outside shard wcts tree: {value}") from error
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise RuntimeError(f"missing or empty WCTS: {resolved}")
    return resolved


def _referenced_wcts(shard_dir: Path, wcts_dir: Path,
                     rows: Sequence[Mapping[str, str]]) -> list[tuple[Mapping[str, str], Path]]:
    row_paths = [(row, _wcts_path(shard_dir, wcts_dir, row["wcts"])) for row in rows]
    paths = [path for _, path in row_paths]
    if len(set(paths)) != len(paths):
        raise RuntimeError("multiple results rows reference the same WCTS")
    present = set()
    for path in wcts_dir.rglob("*.wcts.gz"):
        if path.is_symlink():
            raise RuntimeError(f"WCTS symlink is not supported: {path}")
        present.add(path.resolve())
    extra = sorted(present - set(paths))
    if extra:
        listed = ", ".join(str(path) for path in extra[:5])
        suffix = " ..." if len(extra) > 5 else ""
        raise RuntimeError(f"unreferenced WCTS files under {wcts_dir}: {listed}{suffix}")
    return row_paths


def _parse_native_output(stdout: str, expect_header: bool) -> tuple[list[str] | None, list[str]]:
    rows = list(csv.reader(io.StringIO(stdout)))
    if expect_header:
        if len(rows) != 2:
            raise RuntimeError(f"cachesim_run returned {len(rows)} CSV rows, expected header + row")
        header, data = rows
    else:
        if len(rows) != 1:
            raise RuntimeError(f"cachesim_run returned {len(rows)} CSV rows, expected one row")
        header, data = None, rows[0]
    if not data or (header is not None and len(header) != len(data)):
        raise RuntimeError("cachesim_run returned an incomplete CSV row")
    return header, data


def _run_one(binary: Path, config: Path, row: Mapping[str, str], arm: str,
             wcts: Path, expect_header: bool) -> tuple[list[str] | None, list[str]]:
    command = [str(binary), "--config", str(config), "--trace", str(wcts),
               "--arm", arm, "--header" if expect_header else "--no-header"]
    if arm == "spad_oracle":
        command.append("--oracle-only")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip()
        if len(detail) > 4000:
            detail = detail[-4000:]
        raise RuntimeError(
            f"cachesim_run failed for {row['arch']}/{row['trace_dir']}/{row['layer']}"
            f" sample {row['sample']} arm {arm} (rc={result.returncode}): {detail}"
        )
    return _parse_native_output(result.stdout, expect_header)


def _jobs(
    row_paths: Sequence[tuple[Mapping[str, str], Path]],
) -> Iterator[tuple[Mapping[str, str], str, Path, bool]]:
    first = True
    for row, wcts in row_paths:
        for arm in ARMS:
            yield row, arm, wcts, first
            first = False


def _simulations(
    binary: Path, config: Path, row_paths: Sequence[tuple[Mapping[str, str], Path]], workers: int,
) -> Iterator[tuple[Mapping[str, str], str, Path, list[str], list[str]]]:
    pool = ThreadPoolExecutor(max_workers=workers)
    pending: deque[
        tuple[Future[tuple[list[str] | None, list[str]]], Mapping[str, str], str, Path]
    ] = deque()
    source = iter(_jobs(row_paths))

    def submit_next() -> bool:
        try:
            row, arm, wcts, expect_header = next(source)
        except StopIteration:
            return False
        pending.append((pool.submit(_run_one, binary, config, row, arm, wcts, expect_header),
                        row, arm, wcts))
        return True

    try:
        for _ in range(workers):
            if not submit_next():
                break
        native_header: list[str] | None = None
        while pending:
            future, row, arm, wcts = pending.popleft()
            header, data = future.result()
            if header is not None:
                native_header = header
            elif native_header is None:
                raise RuntimeError("first cachesim_run result did not include a header")
            elif len(native_header) != len(data):
                raise RuntimeError("cachesim_run CSV row length changed within the shard")
            yield row, arm, wcts, native_header, data
            submit_next()
    except BaseException:
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)


def _durable_replace(part_path: Path, final_path: Path) -> None:
    os.replace(part_path, final_path)
    directory_fd = os.open(final_path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _delete_consumed(wcts_dir: Path, consumed: set[Path]) -> None:
    for path in sorted(consumed):
        path.unlink()
    directories = set()
    for path in consumed:
        directory = path.parent
        while directory != wcts_dir.parent:
            directories.add(directory)
            directory = directory.parent
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass


def run_shard(*, shard_dir: Path, config: Path, binary: Path = DEFAULT_BINARY,
              workers: int = 1) -> int:
    shard_dir = Path(shard_dir)
    output_path = shard_dir / "cachesim_results.csv"
    wcts_dir = shard_dir / "wcts"
    if output_path.is_file() and not wcts_dir.exists() and not wcts_dir.is_symlink():
        return 0
    config = Path(config)
    binary = Path(binary)
    if not shard_dir.is_dir():
        raise RuntimeError(f"missing shard directory: {shard_dir}")
    if not config.is_file():
        raise RuntimeError(f"missing simulator config: {config}")
    _validate_config(config)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(f"missing executable cachesim_run: {binary}")
    if workers < 1:
        raise ValueError("workers must be positive")

    rows = _read_results(shard_dir)
    if not wcts_dir.is_dir() or wcts_dir.is_symlink():
        raise RuntimeError(f"missing WCTS tree: {wcts_dir}")
    row_paths = _referenced_wcts(shard_dir, wcts_dir, rows)
    config_sha256 = hashlib.sha256(config.read_bytes()).hexdigest()

    part_path = shard_dir / "cachesim_results.csv.part"
    native_header: list[str] | None = None
    recorded_paths: Counter[Path] = Counter()
    with part_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        for row, _arm, wcts, header, data in _simulations(binary, config, row_paths, workers):
            if native_header is None:
                native_header = header
                writer.writerow([*PREFIX_FIELDS, "config_sha256", *native_header])
            writer.writerow([row[field] for field in PREFIX_FIELDS] + [config_sha256] + data)
            recorded_paths[wcts] += 1
        expected = len(rows) * len(ARMS)
        written = sum(recorded_paths.values())
        if written != expected or set(recorded_paths) != {path for _, path in row_paths}:
            raise RuntimeError(f"incomplete simulation results: wrote {written} rows, expected {expected}")
        if any(count != len(ARMS) for count in recorded_paths.values()):
            raise RuntimeError("a WCTS path did not produce one result per simulator arm")
        if native_header is None:
            raise RuntimeError("simulator produced no CSV header")
        _referenced_wcts(shard_dir, wcts_dir, rows)
        handle.flush()
        os.fsync(handle.fileno())
    _durable_replace(part_path, output_path)
    _delete_consumed(wcts_dir, set(recorded_paths))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True,
                        help="the deployment-supplied cachesim_run JSON config")
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    return run_shard(shard_dir=args.shard_dir, config=args.config,
                     binary=args.binary, workers=args.workers)


if __name__ == "__main__":
    raise SystemExit(main())
