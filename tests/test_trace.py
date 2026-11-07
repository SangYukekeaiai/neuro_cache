"""src/lays/weight_trace_gen/trace.py: the workload dict a layer's meta.json entry gives,
and which layers the arch models can replay."""
import json
import pathlib

import pytest

from lays.weight_trace_gen.trace import (build_workload_from_trace, exclusion_reason,
                                    layer_params, valid_layer_names)

INPUT_TRACE = pathlib.Path(__file__).resolve().parents[1] / "examples/input_trace/loas"


def test_pre_gemm_3x3_workloads_match_frozen_reference():
    golden = json.loads(pathlib.Path(__file__).with_name("trace_3x3.golden").read_text())
    assert golden["reference_blob"] and golden["cases"]
    for case in golden["cases"]:
        m = {"layers": {"conv": case["shape"]}, "layer_params": {"conv": case["params"]}}
        assert exclusion_reason(m, "conv") is None, case
        assert build_workload_from_trace(m, "conv") == case["expected"], case


def meta(**params):
    """Three layers; `params` overrides a layer's layer_params entry."""
    layers = {"a": [4, 5, 64, 8, 8], "b": [4, 5, 128, 4, 4], "s": [4, 5, 64, 8, 8]}
    lp = {"a": {"cout": 128, "kernel": 3, "stride": 2},
          "b": {"cout": 128, "kernel": 3, "stride": 1},
          "s": {"cout": 128, "kernel": 1, "stride": 2}}
    lp.update(params)
    return {"layers": layers, "layer_params": lp}


def test_cout_comes_from_layer_params_not_the_next_layer():
    m = meta(b={"cout": 96, "kernel": 3, "stride": 1})
    assert build_workload_from_trace(m, "b")["problem"] == {
        "KH": 3, "KW": 3, "CIN": 128, "COUT": 96, "HO": 4, "WO": 4, "T": 4, "shape": "snn-layer"}


def test_a_layer_without_layer_params_is_refused():
    m = meta()
    del m["layer_params"]["b"]
    with pytest.raises(ValueError, match="layer_params.*'b'"):
        build_workload_from_trace(m, "b")


def test_a_layer_params_entry_missing_cout_is_refused():
    with pytest.raises(ValueError, match="cout"):
        build_workload_from_trace(meta(b={"kernel": 3, "stride": 1}), "b")


def test_stride_2_layers_are_excluded_with_a_reason():
    m = meta()
    assert valid_layer_names(m) == ["b"]
    assert "stride 2" in exclusion_reason(m, "a")
    assert "kernel 1" in exclusion_reason(m, "s")
    assert exclusion_reason(m, "b") is None


@pytest.mark.parametrize("hin,win", [(128, 1), (1, 1), (8, 8)])
def test_1x1_replays_gemm_and_pointwise_spatial_dimensions(hin, win):
    m = {"layers": {"fc": [4, 5, 768, hin, win]},
         "layer_params": {"fc": {"cout": 3072, "kernel": 1, "stride": 1}}}
    assert exclusion_reason(m, "fc") is None
    assert valid_layer_names(m) == ["fc"]
    assert build_workload_from_trace(m, "fc")["problem"] == {
        "KH": 1, "KW": 1, "CIN": 768, "COUT": 3072, "HO": hin, "WO": win,
        "T": 4, "shape": "snn-layer"}


def test_unsupported_kernel_remains_excluded():
    m = meta(b={"cout": 128, "kernel": 5, "stride": 1})
    assert "kernel 5x5" in exclusion_reason(m, "b")
    with pytest.raises(ValueError, match="kernel 5x5"):
        build_workload_from_trace(m, "b")


@pytest.mark.parametrize("kernel", [1, 3])
def test_empty_spatial_extent_is_excluded(kernel):
    m = meta(b={"cout": 128, "kernel": kernel, "stride": 1})
    m["layers"]["b"][3] = 0
    assert "too small" in exclusion_reason(m, "b")


def test_building_an_excluded_layer_is_refused():
    with pytest.raises(ValueError, match="stride 2"):
        build_workload_from_trace(meta(), "a")


def test_a_layer_params_that_is_not_a_dict_is_refused():
    m = meta()
    m["layer_params"] = [m["layer_params"]["b"]]
    with pytest.raises(ValueError, match="layer_params"):
        layer_params(m, "b")


@pytest.mark.parametrize("key", ["cout", "kernel", "stride"])
def test_a_bool_cout_kernel_or_stride_is_refused(key):
    with pytest.raises(ValueError, match=key):
        layer_params(meta(b={"cout": 128, "kernel": 3, "stride": 1, key: True}), "b")


def real_meta(trace_dir):
    m = json.loads((INPUT_TRACE / trace_dir / "meta.json").read_text())
    return m["layers"], {n: layer_params(m, n) for n in m["layers"]}


def test_resnet19_blocks_chain_and_downsample_where_meta_says():
    layers, lp = real_meta("resnet19_T4_n5")
    blocks = sorted({n.split("_", 2)[2].rsplit("_conv", 1)[0] for n in layers if "_conv" in n})
    for blk in blocks:
        (c1,) = [n for n in layers if n.endswith(f"{blk}_conv1")]
        (c2,) = [n for n in layers if n.endswith(f"{blk}_conv2")]
        assert lp[c1]["cout"] == layers[c2][2], blk
        halves = layers[c2][3] * 2 == layers[c1][3]
        assert (lp[c1]["stride"] == 2) == halves and (halves or layers[c2][3] == layers[c1][3]), blk
        for sc in [n for n in layers if n.endswith(f"{blk}_shortcut_0")]:
            assert lp[sc] == {"cout": lp[c2]["cout"], "kernel": 1, "stride": lp[c1]["stride"]}, sc
            assert layers[sc][2:] == layers[c1][2:], sc


@pytest.mark.parametrize("trace_dir", ["resnet19_T4_n5", "vgg16_T4_n5"])
def test_a_stride_1_3x3_cout_is_the_next_main_path_cin(trace_dir):
    layers, lp = real_meta(trace_dir)
    main = [n for n in layers if "shortcut" not in n]
    assert all(lp[n]["stride"] == 1 for n in layers if trace_dir.startswith("vgg"))
    for here, nxt in zip(main, main[1:]):
        if lp[here]["kernel"] == 3 and lp[here]["stride"] == 1:
            assert lp[here]["cout"] == layers[nxt][2], (here, nxt)
