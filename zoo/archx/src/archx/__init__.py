"""archx package init: bridge Rust-side logging into loguru.

The graph engine lives in the Rust extension `archx._core`. Rust code logs through
the `log` crate; `pyo3-log` (initialised in the `_core` module) turns those into
standard `logging` records. The handler below redirects standard `logging` (hence
the Rust records) into loguru, so Rust and Python share a single log stream.

Level filtering is left to loguru's sinks (configured by the CLI in archx/main.py
via `--log_level`), identical to the original pure-Python implementation: the
stdlib logging threshold is set to DEBUG here so every record reaches loguru, and
loguru decides what is actually emitted.
"""

import logging

from loguru import logger


class InterceptHandler(logging.Handler):
    """Redirect standard `logging` records (including Rust logs) into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        # Map the stdlib level name to loguru's; fall back to the numeric level
        # (e.g. Rust TRACE, which has no stdlib name).
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(exception=record.exc_info).log(level, record.getMessage())


def install_log_intercept(level=logging.DEBUG) -> None:
    """Route stdlib logging (incl. Rust logs via pyo3-log) into loguru.

    Idempotent. `level` is the stdlib logging threshold; DEBUG (the default) forwards
    everything and lets loguru's sinks do the real filtering (parity with the Python
    original). Lower it (see `set_log_level`) to gate Rust logs at the source.
    """
    root = logging.getLogger()
    if not any(isinstance(h, InterceptHandler) for h in root.handlers):
        root.addHandler(InterceptHandler())
    root.setLevel(level)


def set_log_level(level) -> None:
    """Set the threshold below which Rust logs are gated at the source.

    pyo3-log reads the stdlib logging level to decide whether to forward a record.
    Setting it here means disabled levels (e.g. debug! when running at INFO) are
    skipped in Rust before any string formatting or GIL crossing -- a large saving
    on hot aggregation paths -- without removing any log statement. `level` is a
    logging level name ("INFO") or value (logging.INFO). The CLI (archx/main.py)
    calls this with --log_level so verbosity is controlled exactly as in the
    pure-Python original.
    """
    logging.getLogger().setLevel(level)


install_log_intercept()
