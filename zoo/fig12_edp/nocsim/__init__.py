"""Fig12 NoC latency and physical movement counts."""

from .driver import run_case
from .energycounts import parse_tc_csv

__all__ = ["run_case", "parse_tc_csv"]
