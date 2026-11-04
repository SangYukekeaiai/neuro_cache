# lays src-layout Restructure Plan

**Goal:** Move every current `src/` package under a single importable package `src/lays/`, rename `snn_scheduler` to `scheduler`, and rename the distribution to `lays`, so the repo matches the UnaryLab src-layout pattern. Import paths become `lays.cachesim`, `lays.nocsim`, `lays.parsers`, `lays.scheduler`, `lays.weight_trace_gen`, `lays.util`. No behavior changes: the same binaries build, the same tests pass, and the demo emits a byte-identical CSV.

**User order (2026-11-03):** follow the src-layout of https://github.com/UnaryLab/archx and https://github.com/UnaryLab/syndrilla; the project is named `lays`; all current `src/` content moves under `src/lays/`; `snn_scheduler` is renamed `scheduler`.

All line numbers below are as of the dispatch snapshot `git stash create c7830eaa10bf20440a1faec5eb3bf0a44a1481fa` (branch `wcache-rebuild-phase-a`), taken before any file moved.

## Motivation

The two reference repos expose exactly one importable package under `src/<package>/` and keep everything that is not library code at the top level: `tests/`, `examples/`, `zoo/`, `docs/`. This repo instead publishes five sibling top-level packages (`cachesim`, `nocsim`, `parsers`, `snn_scheduler`, `weight_trace_gen`) plus one loose top-level module (`util`, declared at `pyproject.toml:12` as `py-modules = ["util"]`). Five names and a bare `util` are installed into the environment's global import namespace, so `import util` can collide with any other package's module of that name, and nothing in an importer's source says which project a given import came from. One `lays` package fixes both: a single installed name, and every import self-identifying as this project's.

`snn_scheduler` becomes `scheduler` because the `snn_` prefix was namespacing the module against those same global siblings; inside `lays` the package path `lays.scheduler` already carries the project name, so the prefix is redundant.

## Target tree

```
src/lays/__init__.py          (new; src/ has no __init__.py today)
src/lays/util.py              (from src/util.py; no longer a py-module)
src/lays/cachesim/            (incl. native/, examples/)
src/lays/nocsim/              (incl. eventsim/, core/, schedule/, transactions/)
src/lays/parsers/
src/lays/scheduler/           (from src/snn_scheduler/)
src/lays/weight_trace_gen/    (incl. gustavsnn/, loas/, prosperity/, ptb/, spinalflow/)
```

Top level unchanged, playing the references' `tests/`/`examples/`/`zoo/` roles: `tests/`, `scripts/`, `configs/`, `input_trace/`, `data/`, `docs/`, `conftest.py`, `Makefile`, `pyproject.toml`, `requirements.txt`, `README.md`.

One test file is renamed with its module: `tests/test_snn_scheduler_cli.py` -> `tests/test_scheduler_cli.py`. No other test file changes name.

Console-entry surface: the four `__main__.py` modules (`cachesim`, `nocsim`, `snn_scheduler`, `weight_trace_gen`) move with their packages, so every invocation gains the prefix -- `python -m cachesim` becomes `python -m lays.cachesim`, `python -m snn_scheduler` becomes `python -m lays.scheduler`.

## Wiring surfaces

Packaging
- `pyproject.toml:6` `name = "neuro-cache"` -> `lays`; `pyproject.toml:12` `py-modules = ["util"]` dropped (util is now `lays.util`). `package-dir = {"" = "src"}` (`:11`) and `packages.find where = ["src"]` (`:15`) are already correct for the new layout and stay as they are.
- `src/neuro_cache.egg-info/` is stale metadata for the old name; the editable install must be re-run, in BOTH venvs that exist in the tree: `.baseline/venv` (the interpreter `Makefile:2` prefers) and `.venv`.

Import rewrites
- 32 `.py` files reference `snn_scheduler` by name; all five package names plus `util` are rewritten to `lays.*`. The `from util import ...` sites are `src/snn_scheduler/solve.py:39` (`build_strategy`), `scripts/pipeline.py:35` and `scripts/compare_l2pf.py:19` (both `data_root`).
- Tests import the packages directly (`from cachesim.stream import ...`, `from nocsim.sim import main`, `from snn_scheduler.artifact import ...`, `from weight_trace_gen import ...`, `from nocsim.core.transaction import FLITS_PER_PACKET`); each gains the `lays.` prefix. `conftest.py:5`, which only puts `scripts/` on the path, needs no change.

Root-anchor arithmetic (the class of edit most likely to be missed: each path is one directory deeper now)
- `src/cachesim/grid.py:7` `ROOT = pathlib.Path(__file__).resolve().parents[2]` -> `parents[3]`. This is the real anchor behind the `cachesim/cli.py` surface: `cli.py:15` builds `NATIVE = grid.ROOT / "src/cachesim/native"`, which must also become `src/lays/cachesim/native`, and `grid.py:8-9` resolve `configs/cache/base.json` and `khkw_sweep.json` off the same ROOT. (The original dispatch named `cachesim/cli.py` NATIVE; `grid.py:7` is where the depth actually lives, and the manager's 2026-11-03 addendum put it in T53's scope explicitly.)
- `src/cachesim/examples/to_stream.py:20` `parents[2]` -> `parents[3]`, with the `:19` comment's level count updated; it must keep pointing at `src/` so `import lays.weight_trace_gen.trace` resolves.
- `src/cachesim/native/tests/cout_golden.sh:10` and `run_cli.sh:8` both compute `root=$(cd "$(dirname "$0")/../../../.." && pwd)` -- four levels, which is the repo root today. After the move the scripts sit at `src/lays/cachesim/native/tests/`, so those same four levels resolve tests -> native -> cachesim -> lays and land on `src/`, one short of the root; both become five levels. Their hardcoded paths move too: `cout_golden.sh:11,16,17` and `run_cli.sh:9,14,15,133,134` (`$root/src/cachesim/native`, `$root/src/cachesim/examples/...`).

Build paths
- `Makefile:6-8`: `src/cachesim/native`, `src/nocsim/eventsim`, `src/weight_trace_gen/loas`.
- `scripts/pipeline.py:333-334` (`src/cachesim/native`, `src/nocsim/eventsim`), `:335-336` and `:181` (`src/weight_trace_gen/<bench>/Makefile`), `:54` (`str(ROOT / "src")` on `PYTHONPATH`), `:34` (`from snn_scheduler.artifact import ...`), `:280` (`sys.executable -m snn_scheduler solve-trace`), `:6` (module docstring naming `python -m snn_scheduler`).
- `scripts/compare_l2pf.py:14` (`SRC = ROOT / "src"`), `:150-151`, `:153-154`.

Ignore rules
- `.gitignore`: the built-binary paths `:56-61` (`src/nocsim/eventsim/eventsim`, `src/weight_trace_gen/{gustavsnn/gustavgen,loas/loasgen,prosperity/prosperitygen,ptb/ptbgen,spinalflow/spinalflowgen}`), the committed-fixture exception `:38` `!src/cachesim/examples/*.json` with its `:34` comment, and the `:83` comment naming `src/util.py` as where the default `NEURO_CACHE_DATA` data root is read.
- Constraint from the board: `.gitignore` carries another team's uncommitted line, so it is edited but NOT staged.

Paths cited inside the native sources (the dispatch named these)
- Genuine comments, so they affect no build: `src/cachesim/native/include/cachesim/trace/stream_format.h:11` and `src/cachesim/native/src/trace/stream_trace.cpp:252`, both naming the Python producer as `src/cachesim/stream.py` -> `src/lays/cachesim/stream.py`.
- NOT a comment: `stream_format.h:227` is the tail of a string literal in the `throw std::invalid_argument(...)` at `:222-227` ("... so regenerate the stream with the current src/cachesim/stream.py"). It is a user-visible runtime error message that tells the operator which file to re-run, so it belongs to the same class as the CLI strings below, not to the harmless comments: left stale, it sends a reader to a path that no longer exists. It is in T53's scope under the same addendum that assigned the CLI strings.

CLI strings (T53's scope by the manager's addendum of 2026-11-03, dispatched to impl)
- Eleven `prog=` values and in-message instructions still spell the old module paths: `src/cachesim/cli.py:1,8,34`; `src/snn_scheduler/cli.py:46`; `src/snn_scheduler/artifact.py:135`; `src/nocsim/sim.py:9,260,295`; `src/weight_trace_gen/cli.py:132,313,354`. Each prints a `python -m <old>` that no longer runs as printed. These are code edits, not docs edits, so they belong to T53 and not to T55's re-point pass; `grep -rn "python -m "` over the moved tree is the check that none is left.

## Gates

Captured on the pre-move tree FIRST, then re-run after, and compared:

1. `make build` exits 0 (all three native Makefiles).
2. `make test` passes with the SAME collected/passed counts as the pre-move baseline -- a count that drops silently is the signature of a package that stopped being importable, which an exit code alone does not catch.
3. `make demo` output CSV is BYTE-IDENTICAL to the pre-move baseline CSV (`cmp`, not an eyeballed diff).

The baseline numbers are not recorded in this plan: capturing them means running the gates against the build tree, which is T53's claim. T53 records the three baselines before its first move.

## Constraints

- Behavior-preserving. No logic, no defaults, no CSV schema, no config keys change. Every edit is a path, a name, or a depth count.
- Moves use `git mv` so history follows the files.
- `.gitignore` is edited but never staged (it holds another team's uncommitted line). The task board is never staged.
- `docs/plans/` stays historical: this file is the only plan file added or touched by the restructure.
- Commits happen only on the user's order, and only from the manager pane.

## Tasks

### T53 - the restructure itself (impl)
Files: `src/**`, `tests/*.py`, `scripts/*.py`, `pyproject.toml`, `Makefile`, `.gitignore`.
Order that keeps the tree importable at each step: capture the three baselines; `git mv` the packages under `src/lays/` and `snn_scheduler` -> `scheduler`; add `src/lays/__init__.py`; rewrite imports and the root-anchor arithmetic; fix the packaging metadata and re-run both editable installs; rename `tests/test_snn_scheduler_cli.py`; re-point the stale path strings that print to a user (the eleven `python -m` sites and the `stream_format.h:227` throw message, both added by the manager's 2026-11-03 addendum) and the three native-source path citations; then the three gates.
Gates: as above, all three, compared against the baselines captured first.

### T55 - docs re-point and atlas stamp bump (scribe, RESERVED, not dispatched)
Files: `README.md`, `docs/REPRODUCE.md`, `input_trace/README.md`, `docs/atlas/*`, `docs/demo_l2pf_artifact_prompt.md`.
Dispatched only after T53 reads `reviewed pass` AND the user-ordered code commit lands, because the atlas stamps cite commit SHAs and the re-pin must name the restructure commit. Runs under the board's atlas lessons 12, 13, and 16: re-point every path and line citation, re-run `wc -l` for every length the atlas states, and state which citation FORM and backtick state each coverage claim covers. `README.md:17-21` and `:54-57` carry the old `src/<pkg>/` tree table (the `:21` row covers `src/parsers/` and `src/util.py`) and the `python -m <pkg>` command lines and are the most exposed surface.
