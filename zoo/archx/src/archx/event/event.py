from loguru import logger

from archx._core import ArchxGraph
from archx.utils import read_yaml, get_path


def create_event_graph(event_file: str) -> ArchxGraph:
    """
    Create an event graph whose nodes are events and architecture modules.
    Returns an ArchxGraph (Rust-backed) instead of a graph_tool.Graph.
    """
    event_file_full_path = get_path(event_file)
    event_dict = read_yaml(event_file_full_path)['event']

    graph = ArchxGraph()

    # First pass: add all explicitly declared event nodes
    for event, properties in event_dict.items():
        graph.add_node(event, properties.get('performance', None))

    # Second pass: add architecture module leaf nodes not yet in the graph
    for event, properties in event_dict.items():
        for subevent in properties.get('subevent', []):
            if not graph.has_node(subevent):
                graph.add_node(subevent, None)

    # Third pass: add directed edges (event → subevent)
    # Defaults set by Rust: count=1.0, aggregation='parallel', operation={}, factor={}
    for event, properties in event_dict.items():
        for subevent in properties.get('subevent', []):
            merged = graph.add_edge(event, subevent)
            if merged:
                logger.warning(f'Duplicate subevent <{subevent}> under event <{event}>; '
                               f'merging into a single edge.')

    logger.success(f'Create event graph from <{event_file_full_path}>.')
    return graph


def save_event_graph(event_graph: ArchxGraph, save_path: str) -> None:
    save_path = get_path(save_path, check_exist=False)
    event_graph.save_json(save_path)
    logger.success(f'Save event graph to <{save_path}>.')


def load_event_graph(ckpt_path: str) -> ArchxGraph:
    full_path = get_path(ckpt_path)
    graph = ArchxGraph.load_json(full_path)
    logger.success(f'Load event graph from <{full_path}>.')
    return graph
