"""Numerical-equivalence / regression test for the Rust graph engine.

The `rust` branch reimplements the A-Graph aggregation engine (previously pure
Python on `graph-tool`) in the `archx._core` Rust extension. The aggregation
formulas are a 1-to-1 port, so for fixed inputs the engine must produce the same
numbers the Python implementation produced.

This test pins those numbers. It builds a small but representative A-Graph
(mirroring the `mac_1_cycle` example: a workload -> events -> sub-events ->
modules, with a shared multi-operation memory module) directly through the
public API, then checks every aggregation mode against values derived by hand
from the documented aggregation spec:

  - module      : sum of leaf value * instance, shared modules counted once
  - summation   : count * value * factor accumulated bottom-up; path-count
                  scaling under a workload; multi-operation resolution
  - specified   : parallel-max + sequential-accumulate over child events, with
                  the connect-leaf-only fallback to the performance-model value
  - tag         : sum over all modules carrying a tag
  - event_count : product of edge counts over all workload -> event paths

It also asserts that the design-error guards ported from the Python `assert`
statements still fire (reachability, multi-op misuse, specified case1/case2).

It deliberately does NOT use any hardware interface (CACTI7 / csv_cmos), so it
runs anywhere the Rust extension is built, independent of external binaries.
"""

from collections import OrderedDict

import pytest

from archx._core import ArchxGraph
from archx.metric import (
    aggregate_event_metric,
    aggregate_tag_metric,
    aggregate_event_count,
    query_module_metric,
)

# --- fixed inputs -----------------------------------------------------------

METRIC_DICT = OrderedDict({
    "area":           {"unit": "mm^2",   "aggregation": "module"},
    "dynamic_energy": {"unit": "nJ",     "aggregation": "summation"},
    "cycle_count":    {"unit": "cycles", "aggregation": "specified"},
    "runtime":        {"unit": "ms",     "aggregation": "specified"},
})

# leaf-module hardware metrics (what an interface query would return)
MULT = {"area": 2.0, "dynamic_energy": 0.5, "instance": 16}
ADD  = {"area": 1.0, "dynamic_energy": 0.3, "instance": 16}
SRAM_AREA = 10.0
SRAM_RD_E = 0.4   # dynamic_energy, read
SRAM_WR_E = 0.6   # dynamic_energy, write

# edge call counts
C_MA, C_RD, C_WR = 4.0, 8.0, 4.0      # gemm16 -> {mac_array, sram_rd, sram_wr}
C_MULT = C_ADD = 16.0                  # mac_array -> {multiplier, adder}

# performance-model "specified" values injected on intermediate events
MA_CYC, MA_RT = 1.0, 0.01
RD_CYC, RD_RT = 1.0, 0.02
WR_CYC, WR_RT = 1.0, 0.02

REL = 1e-9   # f64: equivalence is exact up to rounding


def _single(value, unit):
    return {"value": float(value), "unit": unit}


def build_graph():
    """Construct the mac_1_cycle-shaped A-Graph with known metrics."""
    g = ArchxGraph()

    # nodes: events + module leaves
    for n in ["gemm16", "mac_array", "sram_rd", "sram_wr",
              "multiplier", "adder", "sram"]:
        g.add_node(n, None)

    # edges (event -> sub-event)
    g.add_edge("gemm16", "mac_array")
    g.add_edge("gemm16", "sram_rd")
    g.add_edge("gemm16", "sram_wr")
    g.add_edge("mac_array", "multiplier")
    g.add_edge("mac_array", "adder")
    g.add_edge("sram_rd", "sram")
    g.add_edge("sram_wr", "sram")

    # initialise all node metrics to 0 for every metric
    g.init_metrics({m: METRIC_DICT[m]["unit"] for m in METRIC_DICT})

    # populate leaf modules
    g.set_module_data(
        "multiplier",
        {"area": _single(MULT["area"], "mm^2"),
         "dynamic_energy": _single(MULT["dynamic_energy"], "nJ")},
        float(MULT["instance"]), ["compute"])
    g.set_module_data(
        "adder",
        {"area": _single(ADD["area"], "mm^2"),
         "dynamic_energy": _single(ADD["dynamic_energy"], "nJ")},
        float(ADD["instance"]), ["compute"])
    g.set_module_data(
        "sram",
        {"area": _single(SRAM_AREA, "mm^2"),
         "dynamic_energy": {"read": _single(SRAM_RD_E, "nJ"),
                            "write": _single(SRAM_WR_E, "nJ")}},
        1.0, ["memory", "onchip"])

    # edge properties (what the performance models would set)
    g.set_edge_count("gemm16", "mac_array", C_MA)
    g.set_edge_count("gemm16", "sram_rd", C_RD)
    g.set_edge_count("gemm16", "sram_wr", C_WR)
    g.set_edge_count("mac_array", "multiplier", C_MULT)
    g.set_edge_count("mac_array", "adder", C_ADD)
    g.set_edge_count("sram_rd", "sram", 1.0)
    g.set_edge_count("sram_wr", "sram", 1.0)

    # aggregation modes for 'specified' (only matters between events)
    g.set_edge_aggregation("gemm16", "mac_array", "sequential")
    g.set_edge_aggregation("gemm16", "sram_rd", "parallel")
    g.set_edge_aggregation("gemm16", "sram_wr", "parallel")

    # operation tags for the multi-op memory module
    g.set_edge_operation("sram_rd", "sram", {"dynamic_energy": "read"})
    g.set_edge_operation("sram_wr", "sram", {"dynamic_energy": "write"})

    # performance-model 'specified' metrics on intermediate events
    g.set_node_specified_metric("mac_array", "cycle_count", MA_CYC, "cycles")
    g.set_node_specified_metric("mac_array", "runtime", MA_RT, "ms")
    g.set_node_specified_metric("sram_rd", "cycle_count", RD_CYC, "cycles")
    g.set_node_specified_metric("sram_rd", "runtime", RD_RT, "ms")
    g.set_node_specified_metric("sram_wr", "cycle_count", WR_CYC, "cycles")
    g.set_node_specified_metric("sram_wr", "runtime", WR_RT, "ms")
    return g


@pytest.fixture
def graph():
    return build_graph()


def agg(graph, metric, event, workload=None):
    return aggregate_event_metric(
        event_graph=graph, metric_dict=METRIC_DICT,
        metric=metric, workload=workload, event=event)["value"]


# --- module mode ------------------------------------------------------------

def test_module_area_full(graph):
    # sum of leaf area * instance; sram is shared by sram_rd/sram_wr -> counted once
    expected = MULT["area"] * MULT["instance"] + ADD["area"] * ADD["instance"] + SRAM_AREA
    assert agg(graph, "area", "gemm16") == pytest.approx(expected, rel=REL)  # 58.0


def test_module_area_subevent(graph):
    expected = MULT["area"] * MULT["instance"] + ADD["area"] * ADD["instance"]
    assert agg(graph, "area", "mac_array") == pytest.approx(expected, rel=REL)  # 48.0


def test_module_shared_leaf_counted_once(graph):
    # area of a single shared module queried directly
    assert agg(graph, "area", "sram") == pytest.approx(SRAM_AREA, rel=REL)


# --- summation mode ---------------------------------------------------------

def test_summation_energy_top(graph):
    mac = C_MULT * MULT["dynamic_energy"] + C_ADD * ADD["dynamic_energy"]   # 12.8
    expected = C_MA * mac + C_RD * SRAM_RD_E + C_WR * SRAM_WR_E             # 56.8
    assert agg(graph, "dynamic_energy", "gemm16") == pytest.approx(expected, rel=REL)


def test_summation_energy_no_workload_matches_self_workload(graph):
    a = agg(graph, "dynamic_energy", "gemm16", workload=None)
    b = agg(graph, "dynamic_energy", "gemm16", workload="gemm16")
    assert a == pytest.approx(b, rel=REL)


def test_summation_subevent_path_scaled(graph):
    mac = C_MULT * MULT["dynamic_energy"] + C_ADD * ADD["dynamic_energy"]   # 12.8
    expected = mac * C_MA                                                   # 51.2
    assert agg(graph, "dynamic_energy", "mac_array", workload="gemm16") == pytest.approx(expected, rel=REL)


def test_summation_multiop_leaf_under_workload(graph):
    # two paths gemm16->sram_rd->sram (read) and gemm16->sram_wr->sram (write)
    expected = SRAM_RD_E * C_RD + SRAM_WR_E * C_WR                          # 5.6
    assert agg(graph, "dynamic_energy", "sram", workload="gemm16") == pytest.approx(expected, rel=REL)


# --- specified mode ---------------------------------------------------------

def test_specified_cycle_count_top(graph):
    seq = MA_CYC * C_MA                                  # sequential edge
    par = max(RD_CYC * C_RD, WR_CYC * C_WR)              # parallel edges -> max
    assert agg(graph, "cycle_count", "gemm16") == pytest.approx(seq + par, rel=REL)  # 12.0


def test_specified_runtime_top(graph):
    seq = MA_RT * C_MA
    par = max(RD_RT * C_RD, WR_RT * C_WR)
    assert agg(graph, "runtime", "gemm16") == pytest.approx(seq + par, rel=REL)      # 0.20


def test_specified_connect_leaf_only_uses_injected(graph):
    # mac_array connects only to modules -> value comes from the performance model
    assert agg(graph, "cycle_count", "mac_array") == pytest.approx(MA_CYC, rel=REL)


def test_specified_subevent_path_scaled(graph):
    assert agg(graph, "cycle_count", "mac_array", workload="gemm16") == pytest.approx(MA_CYC * C_MA, rel=REL)


# --- tag mode ---------------------------------------------------------------

def test_tag_area_onchip(graph):
    r = aggregate_tag_metric(event_graph=graph, metric_dict=METRIC_DICT,
                             metric="area", tag="onchip")
    assert r["value"] == pytest.approx(SRAM_AREA, rel=REL)


# --- event count ------------------------------------------------------------

def test_event_count_single_path(graph):
    assert aggregate_event_count(graph, workload="gemm16", event="multiplier") == pytest.approx(C_MA * C_MULT, rel=REL)  # 64


def test_event_count_two_paths(graph):
    assert aggregate_event_count(graph, workload="gemm16", event="sram") == pytest.approx(C_RD + C_WR, rel=REL)  # 12


def test_event_count_self(graph):
    assert aggregate_event_count(graph, workload="gemm16", event="gemm16") == pytest.approx(1.0, rel=REL)


# --- module query -----------------------------------------------------------

def test_query_multiop_module(graph):
    r = query_module_metric(event_graph=graph, metric_dict=METRIC_DICT,
                            metric="dynamic_energy", module="sram", operation="read")
    assert r["value"] == pytest.approx(SRAM_RD_E, rel=REL)


# --- Rust logs integrated into loguru ---------------------------------------

def test_rust_logs_reach_loguru(graph):
    # Rust trace logs (via pyo3-log + the InterceptHandler in archx/__init__) must
    # appear in loguru. Capture them through a temporary loguru sink at DEBUG.
    from loguru import logger
    records = []
    sink = logger.add(lambda m: records.append(m.record), level="DEBUG")
    try:
        agg(graph, "dynamic_energy", "gemm16", workload="gemm16")
    finally:
        logger.remove(sink)
    msgs = [r["message"] for r in records]
    # per-edge summation trace emitted from Rust (aggregate.rs)
    assert any("single value" in m and "count" in m for m in msgs)
    assert any(m.startswith("  Total value") for m in msgs)


def test_rust_logs_respect_loguru_level(graph):
    # Level is controlled by loguru (as in the Python original): an INFO sink must
    # receive Rust INFO records but none of the DEBUG traces.
    from loguru import logger
    records = []
    sink = logger.add(lambda m: records.append(m.record), level="INFO")
    try:
        agg(graph, "area", "gemm16")
    finally:
        logger.remove(sink)
    levels = {r["level"].name for r in records}
    assert "DEBUG" not in levels
    assert "INFO" in levels   # e.g. "Aggregate metric <area> for module ..."


def test_set_log_level_gates_rust_logs(graph):
    # set_log_level gates Rust logs at the source (pyo3-log skips disabled levels):
    # with it at ERROR, no Rust DEBUG/INFO trace reaches loguru even via a DEBUG sink.
    # The logs are not removed -- they are level-gated -- so we restore DEBUG after.
    from loguru import logger
    from archx import set_log_level
    records = []
    set_log_level("ERROR")
    sink = logger.add(lambda m: records.append(m.record), level="DEBUG")
    try:
        agg(graph, "dynamic_energy", "gemm16", workload="gemm16")
    finally:
        logger.remove(sink)
        set_log_level("DEBUG")
    levels = {r["level"].name for r in records}
    assert "DEBUG" not in levels   # Rust debug! traces gated at source
    assert "INFO" not in levels    # Rust info! traces gated at source


# --- duplicate-edge merge (task 2) ------------------------------------------

def test_duplicate_edge_merged_and_signaled():
    g = ArchxGraph()
    g.add_node("a", None)
    g.add_node("b", None)
    assert g.add_edge("a", "b") is False        # first insertion
    assert g.add_edge("a", "b") is True         # duplicate -> merged, signaled
    assert len(g.get_out_neighbors("a")) == 1   # single edge, no parallel edge


# --- restored design-error guards (ported Python assertions) ----------------

def test_guard_summation_multiop_leaf_without_workload(graph):
    # main metric.py L280: summation without a workload needs a single-op module
    with pytest.raises((ValueError, AssertionError)):
        graph.aggregate_event_metric("dynamic_energy", "summation", "nJ", None, "sram")


def test_guard_module_mode_on_multiop_leaf(graph):
    # main metric.py L389: 'module' aggregation requires single-op leaves
    with pytest.raises((ValueError, AssertionError)):
        graph.aggregate_event_metric("dynamic_energy", "module", "nJ", None, "gemm16")


def test_guard_unreachable_event(graph):
    # main metric.py L239: event must be reachable from the workload
    graph.add_node("orphan", None)
    with pytest.raises((ValueError, AssertionError)):
        agg(graph, "area", "orphan", workload="gemm16")


def test_guard_bad_operation_summation(graph):
    # main metric.py L535: operation on the edge must be a legal op of the module
    graph.set_edge_operation("sram_rd", "sram", {"dynamic_energy": "bogus"})
    with pytest.raises((ValueError, AssertionError)):
        agg(graph, "dynamic_energy", "gemm16")


def test_guard_specified_case1_missing_injected_metric():
    # main metric.py L488: a node connected only to modules must inject the metric
    g = ArchxGraph()
    g.add_node("e", None)
    g.add_node("m", None)
    g.add_edge("e", "m")
    g.init_metrics({"cycle_count": "cycles"})
    g.set_module_data("m", {"cycle_count": _single(1.0, "cycles")}, 1.0, [])
    # NOTE: no set_node_specified_metric on 'e'
    with pytest.raises((ValueError, AssertionError)):
        g.aggregate_event_metric("cycle_count", "specified", "cycles", None, "e")


def test_guard_specified_case2_spurious_injected_metric():
    # main metric.py L493: a node connected to no modules must NOT inject the metric
    g = ArchxGraph()
    g.add_node("top", None)
    g.add_node("mid", None)
    g.add_node("leaf", None)
    g.add_edge("top", "mid")
    g.add_edge("mid", "leaf")
    g.init_metrics({"cycle_count": "cycles"})
    g.set_module_data("leaf", {"cycle_count": _single(1.0, "cycles")}, 1.0, [])
    g.set_node_specified_metric("mid", "cycle_count", 1.0, "cycles")   # mid: leaf-only, valid
    g.set_node_specified_metric("top", "cycle_count", 1.0, "cycles")   # top: no modules -> spurious
    with pytest.raises((ValueError, AssertionError)):
        g.aggregate_event_metric("cycle_count", "specified", "cycles", None, "top")
