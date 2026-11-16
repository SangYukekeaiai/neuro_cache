import pytest

from contracts import require_no_gb


def zero_gb():
    return dict(gb_reads=0, gb_writes=0, weight_packet_hops=0, chain_packet_hops=0,
                dram_accesses=4, l1_delivery_bytes=128)


def test_direct_dram_local_is_allowed():
    require_no_gb(zero_gb(), ['loas.l1_weight_spad.read', 'shared.ddr4.read'])


@pytest.mark.parametrize('field', ['gb_reads', 'gb_writes', 'weight_packet_hops',
                                 'chain_packet_hops', 'gb_other', 'NoCLevel.read'])
def test_nonzero_gb_or_inter_node_activity_is_rejected(field):
    counts = zero_gb()
    counts[field] = 1
    with pytest.raises(ValueError, match='forbids'):
        require_no_gb(counts)


def test_missing_gb_counter_is_not_assumed_zero():
    counts = zero_gb()
    del counts['gb_reads']
    with pytest.raises(ValueError, match='lacks gb_reads'):
        require_no_gb(counts)


def test_even_zero_priced_gb_inventory_is_rejected():
    with pytest.raises(ValueError, match='inventory contains GB'):
        require_no_gb(zero_gb(), ['shared.gb.read'])
