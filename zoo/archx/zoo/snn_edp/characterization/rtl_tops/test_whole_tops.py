"""Run the independent all13-top bench with a local open-source simulator.

Example (on a host providing Verilator):
  python -B test_whole_tops.py --repo /path/to/verilog_modules --simulator verilator

No network or licensed tools are used. Exit77 means simulator unavailable;
compile/test failures are nonzero. DUT files and repo sources are read-only.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def sources(here: Path, repo: Path) -> list[Path]:
    return [
        repo / "adder/adder.v",
        repo / "register/register.v",
        repo / "and_gate/and_gate.v",
        *(here / "common" / f"{name}.v" for name in ("or_gate", "xor_gate", "not_gate", "mux2")),
        here / "helpers.v",
        here / "whole_tops.v",
        here / "test_whole_tops.sv",
    ]


def run(simulator: str, files: list[Path], build: Path) -> int:
    if simulator == "iverilog":
        executable = build / "test_whole_tops.vvp"
        command = ["iverilog", "-g2012", "-s", "test_whole_tops", "-o", str(executable), *map(str, files)]
        launch = ["vvp", str(executable)]
    else:
        command = [
            "verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
            "--top-module", "test_whole_tops", "--Mdir", str(build), "-j", "2",
            *map(str, files),
        ]
        launch = [str(build / "Vtest_whole_tops")]
    # Warnings remain visible; the runner does not suppress classes of warnings.
    print("Compile:", " ".join(command), flush=True)
    subprocess.run(command, check=True, timeout=600)
    print("Simulate:", " ".join(launch), flush=True)
    subprocess.run(launch, check=True, timeout=180)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("/u/yyu9/projects/verilog_modules"))
    parser.add_argument("--simulator", choices=("auto", "iverilog", "verilator"), default="auto")
    parser.add_argument("--build-dir", type=Path, help="Keep generated simulator files in this directory; default is temporary storage")
    parser.add_argument("--list-sources", action="store_true", help="Print absolute source paths without invoking a simulator")
    args = parser.parse_args()
    files = sources(Path(__file__).resolve().parent, args.repo.resolve())
    for path in files:
        if not path.is_file():
            parser.error(f"missing source: {path}")
    if args.list_sources:
        print("\n".join(map(str, files)))
        return 0
    available = {
        "iverilog": bool(shutil.which("iverilog") and shutil.which("vvp")),
        "verilator": bool(shutil.which("verilator")),
    }
    simulator = args.simulator
    if simulator == "auto":
        simulator = next((name for name, present in available.items() if present), "auto")
    if not available.get(simulator, False):
        print("NOT RUN: Icarus+vvp or Verilator is required; no simulation result.", file=sys.stderr)
        return 77
    try:
        if args.build_dir:
            build = args.build_dir.resolve()
            build.mkdir(parents=True, exist_ok=True)
            return run(simulator, files, build)
        with tempfile.TemporaryDirectory(prefix="snn-whole-tops-") as directory:
            return run(simulator, files, Path(directory))
    except subprocess.CalledProcessError as error:
        return error.returncode
    except subprocess.TimeoutExpired as error:
        print(f"FAILED: command timed out after {error.timeout}s", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
