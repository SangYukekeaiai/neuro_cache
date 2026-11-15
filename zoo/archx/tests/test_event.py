import shutil

from loguru import logger

from archx.event import create_event_graph, save_event_graph, load_event_graph
from archx.utils import get_path, create_dir


def test_create_event_graph():
    event_file = 'examples/mac_1_cycle/input/event/example.event.yaml'
    event_graph = create_event_graph(event_file)

    create_dir('tests/test_event/')

    ckpt_file = 'tests/test_event/example.event.json'
    save_event_graph(event_graph, ckpt_file)
    event_graph_ckpt = load_event_graph(ckpt_file)

    # Verify the checkpoint round-trips correctly: same node names and edges
    nodes_orig = set(event_graph.get_all_node_names())
    nodes_ckpt = set(event_graph_ckpt.get_all_node_names())
    assert nodes_orig == nodes_ckpt, f'Node mismatch: {nodes_orig} != {nodes_ckpt}'

    edges_orig = set()
    for src in event_graph.get_all_node_names():
        for tgt in event_graph.get_out_neighbors(src):
            edges_orig.add((src, tgt))

    edges_ckpt = set()
    for src in event_graph_ckpt.get_all_node_names():
        for tgt in event_graph_ckpt.get_out_neighbors(src):
            edges_ckpt.add((src, tgt))

    assert edges_orig == edges_ckpt, f'Edge mismatch: {edges_orig} != {edges_ckpt}'

    logger.success('Graph checkpoint round-trip verified.')


def test_cleanup():
    path = get_path('tests/test_event/')
    shutil.rmtree(path)


if __name__ == "__main__":
    test_create_event_graph()
    test_cleanup()
