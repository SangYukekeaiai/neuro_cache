"""Pin timestep order at the decoded native-tile level, not just a YAML list."""
import itertools
import yaml
from schedule_spec import resident, strategy
from lays.parsers.layer import SNNProb, DIM_COUT, DIM_HO, DIM_WO, DIM_T
from lays.nocsim.schedule.decode import schedule_from_strategy
from lays.nocsim.schedule.steps import StepInfo
from lays.nocsim.schedule.tiles import iter_node_tiles


def test_gustav_t_advances_before_pixels_and_weight_reuse(tmp_path):
    problem={'shape':'snn-layer','KH':3,'KW':3,'CIN':2,'COUT':16,'HO':2,'WO':3,'T':4}
    path=tmp_path/'workload.yaml';path.write_text(yaml.safe_dump({'problem':problem}))
    prob=SNNProb(path);tile=resident(problem,'gustavsnn',144,8)
    schedule=schedule_from_strategy(strategy(problem,tile,'gustavsnn'),prob)
    tiles=list(iter_node_tiles(schedule,prob))
    actual=[tuple(t.tile_offset.get(d,0) for d in (DIM_COUT,DIM_HO,DIM_WO,DIM_T)) for t in tiles]
    expected=list(itertools.product((0,8),range(2),range(3),range(4)))
    assert actual==expected
    assert all(t.node_bound[DIM_HO]==t.node_bound[DIM_WO]==t.node_bound[DIM_T]==1 for t in tiles)
    info=StepInfo(schedule,prob)
    assert [i for i in range(len(tiles)) if info.weight_changes(i,0)]==[0,24]
    assert all(getattr(info,n) for n in ('is_psum_gb_free','is_vmem_gb_free','is_psum_dram_free','is_vmem_dram_free'))


def test_temporal_batch_arches_have_no_outer_t_loop(tmp_path):
    problem={'shape':'snn-layer','KH':3,'KW':3,'CIN':2,'COUT':32,'HO':2,'WO':3,'T':4}
    path=tmp_path/'workload.yaml';path.write_text(yaml.safe_dump({'problem':problem}))
    prob=SNNProb(path)
    for arch in ('loas','ptb'):
        tile=resident(problem,arch,288,8)
        schedule=schedule_from_strategy(strategy(problem,tile,arch),prob)
        tiles=list(iter_node_tiles(schedule,prob))
        assert all(t.node_bound[DIM_T]==4 and t.tile_offset.get(DIM_T,0)==0 for t in tiles)
        assert all(loop.dim!=DIM_T for loop in schedule.dram_temporal_loops)
        assert [(t.tile_offset.get(DIM_HO,0),t.tile_offset.get(DIM_WO,0),t.tile_offset.get(DIM_COUT,0)) for t in tiles]==list(itertools.product(range(2),range(3),(0,16)))
