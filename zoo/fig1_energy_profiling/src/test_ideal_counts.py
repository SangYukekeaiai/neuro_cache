import numpy as np
import pytest

from ideal_counts import needed_lines


def test_hand_checked_corner_and_center():
    corner = np.zeros((2, 2, 2, 2), dtype=np.uint8)
    corner[0, 0, 0, 0] = 1
    actual = needed_lines(corner, 3)
    expected = np.zeros((3, 3, 2), dtype=bool)
    expected[:2, :2, 0] = True
    assert np.array_equal(actual, expected)
    center = np.zeros((1, 1, 3, 3), dtype=np.uint8)
    center[0, 0, 1, 1] = 1
    assert needed_lines(center, 3).all()


def test_all_ones_is_compulsory_and_zero_has_no_demand():
    for kernel in (1, 3):
        assert needed_lines(np.ones((4, 3, 4, 4), dtype=np.uint8), kernel).sum() == kernel*kernel*3
        assert not needed_lines(np.zeros((4, 3, 4, 4), dtype=np.uint8), kernel).any()


@pytest.mark.parametrize('kernel', [1, 3])
def test_matches_explicit_convolution_walk(kernel):
    sample = np.random.default_rng(71).integers(0, 2, (3, 2, 4, 5), dtype=np.uint8)
    expected = np.zeros((kernel, kernel, 2), dtype=bool)
    pad = (kernel-1)//2
    for t in range(3):
        for ci in range(2):
            for oh in range(4):
                for ow in range(5):
                    for kh in range(kernel):
                        for kw in range(kernel):
                            ih, iw = oh+kh-pad, ow+kw-pad
                            if 0 <= ih < 4 and 0 <= iw < 5 and sample[t, ci, ih, iw]:
                                expected[kh, kw, ci] = True
    assert np.array_equal(needed_lines(sample, kernel), expected)


def test_native_address_union_ignores_retouches_across_ticks_and_tiles():
    from types import SimpleNamespace as Object
    from ideal_counts import native_demand
    addresses=[(0,0,0,0,4),(0,0,0,2,4),(0,0,1,0,2)]
    core=Object(core_id=0,weight_addresses=addresses)
    tick=Object(cores=[core])
    def trace(repeats):
        return Object(workload_dims={'KH':1,'KW':1,'CIN':2,'COUT':4},
                      tiles=[Object(ticks=[tick,tick]) for _ in range(repeats)])
    once,records,stream=native_demand(trace(1))
    repeated,repeated_records,repeated_stream=native_demand(trace(100))
    assert once.dtype==np.bool_ and int(once.sum())==6
    assert np.array_equal(repeated,once)
    assert repeated_records==100*records and repeated_stream==100*stream
    assert int(repeated.sum())<repeated_stream


def test_spike_repetition_does_not_change_needed_weights():
    sample=np.zeros((1,2,4,4),dtype=np.uint8)
    sample[0,0,1,1]=1
    repeated=np.repeat(sample,32,axis=0)
    assert np.array_equal(needed_lines(repeated,3),needed_lines(sample,3))
