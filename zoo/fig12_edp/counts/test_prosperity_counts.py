import pytest
import prosperity_counts as prosperity
import spinalflow_counts as spinal

spinal.cap_threads(1)
import numpy as np


def test_frontend_not_repeated_over_cout_and_seed_bound():
    trace = np.ones((4, 1, 2, 8, 1), dtype=np.uint8)
    tile = {"T": 4, "HO": 8, "WO": 1, "CIN": 2, "COUT": 4}
    counts = prosperity.count_sample(trace, 0, cout=16, kernel=1, tile=tile, d_out=0.25)
    assert counts["N_rows"] == 64
    assert counts["SORT"] == 2 * 32 * 5 * 2
    assert counts["R_p"] == 2 * 4
    assert counts["A_p"] == 32
    assert counts["seed_reads_bound"] == counts["psum_writes"] == 64 * 16
    bigger = prosperity.count_sample(trace, 0, cout=32, kernel=1, tile=tile, d_out=0.25)
    assert bigger["N_rows"] == counts["N_rows"] and bigger["SORT"] == counts["SORT"]
    assert bigger["R_p"] == 2 * counts["R_p"]


def test_missing_3x3_records_are_not_replaced_by_mean():
    trace = np.ones((4, 1, 1, 8, 1), dtype=np.uint8)
    tile = {"T": 4, "HO": 8, "WO": 1, "CIN": 1, "COUT": 4}
    with pytest.raises(ValueError, match="missing exact"):
        prosperity.count_sample(trace, 0, cout=4, kernel=3, tile=tile, d_out=0.25)
    counts = prosperity.count_sample(trace, 0, cout=4, kernel=3, tile=tile, records=12, d_out=0.25)
    assert counts["R_p"] == 12 and counts["A_p"] == 48


def test_actual_digest_anchors():
    path = spinal.ROOT / "zoo/wt500_fig3cfg/stokes/s3_digest.md"
    records = prosperity.digest_anchors(path)
    assert records[("spikinglm_t4_T4_n500", "layer_05_core_bert_encoder_layer_0_intermediate_dense", 0)] == 3909120
    assert records[("loas_resnet19_T4_n500", "layer_14_core_layer2_2_conv2", 0)] == 2606528
    assert len(records) == 2


def test_real_exact_csv_join_and_provenance(tmp_path):
    import csv
    output = tmp_path / 'joined.csv'
    assert prosperity.main([
        '--record-counts', str(spinal.ROOT / 'zoo/fig12_edp/counts/prosperity_sample0_records.csv'),
        '--trace-root', '/work/nvme/bebv/yyu9/input_trace_delta',
        '--capture', 'C01/sma_azo_vgg_dvs128_gesture_T16_n500',
        '--layer', 'layer_01_core_block2_0_0', '--sample-count', '1',
        '--threads', '1', '--output', str(output)]) == 0
    row, = list(csv.DictReader(output.open()))
    assert int(row['R_p']) == 8275200
    assert row['records_source'] == 'exact_pipeline_csv'
    assert int(row['seed_reads_bound']) == int(row['psum_writes']) == 4194304 * 128


def test_explicit_output_density_required():
    with pytest.raises(ValueError, match='d_out is required'):
        prosperity.count_sample(np.ones((1, 1, 1, 1, 1)), 0, cout=4,
                                kernel=1, tile={'COUT': 4})
