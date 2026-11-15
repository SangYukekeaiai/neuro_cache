# Vendored archx 0.1.1

Upstream: https://github.com/UnaryLab/archx at
49449c4fc1a023dd8b9c81a41720e53c1b61ba76. `VENDOR.json` records the source
inventory, working-tree additions and design archive. The backend sources and
characterization assets live here; the campaign does not fetch archx from pip.

From the campaign repository root, prepare the target Python environment with:

```bash
CARGO_BUILD_JOBS=1 python -m pip install -e ./zoo/archx
```

This editable installation builds the Rust extension from local archx source
and places it in `src/archx`. Rust/Cargo and the build requirements in
`pyproject.toml` are needed; third-party dependencies and Cargo crates may need
downloading. Rebuild on the target platform instead of assuming the bundled
Linux ABI3 binary is compatible. No archx source is fetched. Both model entries
prioritize this tree's `src`; a site-packages backend is never used.

Standalone: `cd zoo/snn_edp && ./script.sh --arch spinalflow`.
The fig12 caller uses the same API with external counters and an explicit table.
All model thread pools are capped at one and performance caching is disabled.

`examples/` and zoo designs other than `snn_edp/` are present on disk but ignored
by Git. Backend sources, characterization CSV/report assets and `zoo/snn_edp/`
are eligible for tracking; generated caches/runs stay ignored. The ABI3 Linux
extension is included for this platform, with the local-source build above for
other targets. The original checkout is not a runtime dependency.
