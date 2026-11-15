from collections import OrderedDict

from loguru import logger

from archx._core import ArchxGraph
from archx.interface import query_interface
from archx.utils import read_yaml, write_yaml, get_path, create_dir, get_prod


key_value = 'value'
key_unit = 'unit'
legal_aggregation = ['module', 'summation', 'specified']
legal_aggregation_tag = ['module', 'summation']
key_metric = 'metric'
key_instance = 'instance'
key_factor = 'factor'
key_aggregation = 'aggregation'


def create_metric_dict(metric_file: str) -> OrderedDict:
    """
    All metrics need to be included in this file.
    """
    metric_file_full_path = get_path(metric_file)
    metric_dict = read_yaml(get_path(metric_file))[key_metric]

    for metric in metric_dict:
        assert key_unit in metric_dict[metric], \
            logger.error(f'Missing <unit> in metric <{metric}>.')

        if key_aggregation not in metric_dict[metric]:
            metric_dict[metric][key_aggregation] = 'summation'

        assert key_aggregation in metric_dict[metric], \
            logger.error(f'Missing <aggregation> in metric <{metric}>.')
        this_aggregation = metric_dict[metric][key_aggregation].lower()
        assert this_aggregation in legal_aggregation, \
            logger.error(f'Invalid aggregation <{this_aggregation}> in metric <{metric}>; '
                         f'legal values: {legal_aggregation}.')
        metric_dict[metric][key_aggregation] = this_aggregation

    logger.success(f'Create metric dictionary from <{metric_file_full_path}>.')
    return metric_dict


def save_metric_dict(metric_dict: OrderedDict, save_path: str) -> None:
    save_path = get_path(save_path, check_exist=False)
    write_yaml(save_path, OrderedDict({key_metric: metric_dict}))
    logger.success(f'Save metric dictionary to <{save_path}>.')


def load_metric_dict(ckpt_path: str) -> OrderedDict:
    full_path = get_path(ckpt_path)
    metric_dict = read_yaml(full_path)[key_metric]
    logger.success(f'Load metric dictionary from <{full_path}>.')
    return metric_dict


def create_event_metrics(
    event_graph: ArchxGraph,
    architecture_dict: OrderedDict,
    metric_dict: OrderedDict,
    run_dir: str = None,
) -> ArchxGraph:
    """
    Initialise all node metrics to 0.0 then populate leaf (module) nodes
    from hardware interface queries.
    """
    # Build {metric_name: unit} and pass to Rust to initialise all nodes
    metric_units = {m: metric_dict[m][key_unit] for m in metric_dict}
    event_graph.init_metrics(metric_units)

    for name in event_graph.get_all_node_names():
        logger.info(f'Create metrics for event <{name}>.')
    logger.success('Create metrics for all events.')

    event_graph = create_module_metrics(event_graph, architecture_dict, run_dir)
    return event_graph


def create_module_metrics(
    event_graph: ArchxGraph,
    architecture_dict: OrderedDict,
    run_dir: str = None,
) -> ArchxGraph:
    """
    Query each architecture module's hardware interface and push results into
    the Rust graph via set_module_data().
    """
    create_dir(run_dir)
    full_path = get_path(run_dir)

    for module_name in event_graph.get_leaf_names():
        assert module_name in architecture_dict, \
            logger.error(f'Invalid module <{module_name}>.')
        assert 'query' in architecture_dict[module_name], \
            logger.error(f'Missing query information for module <{module_name}>.')
        assert 'class' in architecture_dict[module_name]['query'], \
            logger.error(f'Missing class information in query for module <{module_name}>.')

        module_class = architecture_dict[module_name]['query']['class']
        query = architecture_dict[module_name]['query']
        result = query_interface(module_name, query, output_dir=full_path)

        instance = float(get_prod(architecture_dict[module_name][key_instance]))
        tags = architecture_dict[module_name]['tag']

        # result is a plain dict from query_interface; Rust parses single-op vs multi-op
        event_graph.set_module_data(module_name, result, instance, tags)

        logger.info(f'Create metrics for module <{module_name}> with class <{module_class}>.')

    logger.success('Create metrics for all modules.')
    return event_graph


def query_module_metric(
    event_graph: ArchxGraph,
    metric_dict: OrderedDict,
    metric: str,
    module: str = None,
    operation: str = None,
) -> OrderedDict:
    """
    Query the metric value of a single architecture module.
    """
    assert metric in metric_dict, logger.error(f'Invalid metric <{metric}>.')
    assert key_aggregation in metric_dict[metric], \
        logger.error(f'Missing aggregation in metric <{metric}>.')
    assert metric_dict[metric][key_aggregation] in legal_aggregation, \
        logger.error(f'Invalid aggregation <{metric_dict[metric][key_aggregation]}> for metric <{metric}>; '
                     f'legal values: {legal_aggregation}.')

    result = event_graph.query_module_metric(metric, module, operation)

    if operation is None:
        logger.success(f'Query metric <{metric}> for module <{module}>.')
    else:
        logger.success(f'Query metric <{metric}> for operation <{operation}> '
                       f'in module <{module}>.')
    return OrderedDict(result)


def aggregate_event_metric(
    event_graph: ArchxGraph,
    metric_dict: OrderedDict,
    metric: str,
    workload: str = None,
    event: str = None,
) -> OrderedDict:
    """
    Aggregate a metric from leaf modules up to the target event node.
    Delegates all computation to Rust.
    """
    assert metric in metric_dict, logger.error(f'Invalid metric <{metric}>.')
    cfg = metric_dict[metric]
    assert key_aggregation in cfg, \
        logger.error(f'Missing aggregation in metric <{metric}>.')
    assert cfg[key_aggregation] in legal_aggregation, \
        logger.error(f'Invalid aggregation <{cfg[key_aggregation]}> for metric <{metric}>; '
                     f'legal values: {legal_aggregation}.')

    result = event_graph.aggregate_event_metric(
        metric,
        cfg[key_aggregation],
        cfg[key_unit],
        workload,
        event,
    )

    if workload is not None:
        logger.success(f'Aggregate metric <{metric}> for event <{event}> '
                       f'in workload <{workload}> with aggregation <{cfg[key_aggregation]}>.')
    else:
        logger.success(f'Aggregate metric <{metric}> for event <{event}> '
                       f'with aggregation <{cfg[key_aggregation]}>.')
    return OrderedDict(result)


def aggregate_tag_metric(
    event_graph: ArchxGraph,
    metric_dict: OrderedDict,
    metric: str,
    workload: str = None,
    tag: str = None,
) -> OrderedDict:
    """
    Aggregate a metric across all modules sharing a given tag.
    Delegates all computation to Rust.
    """
    assert tag is not None, logger.error(f'Missing tag in aggregation of metric <{metric}>.')
    assert metric in metric_dict, logger.error(f'Invalid metric <{metric}>.')
    cfg = metric_dict[metric]
    assert key_aggregation in cfg, \
        logger.error(f'Missing aggregation in metric <{metric}>.')
    assert cfg[key_aggregation] != 'specified', \
        logger.error(f'Invalid aggregation <{cfg[key_aggregation]}> for tag <{tag}>; '
                     f'legal values: {legal_aggregation_tag}.')

    # Drive the per-module loop in Python (rather than in Rust) so each module's
    # aggregate_event_metric emits its own SUCCESS trace, matching the original
    # pure-Python engine. Rust only supplies the tag→module lookup.
    tag_nodes = event_graph.get_tag_modules(tag)
    assert len(tag_nodes) > 0, logger.error(f'Invalid tag <{tag}>.')

    tag_metric = OrderedDict({key_value: 0.0, key_unit: cfg[key_unit]})
    for module_name in tag_nodes:
        module_metric = aggregate_event_metric(
            event_graph=event_graph, metric_dict=metric_dict, metric=metric,
            workload=workload, event=module_name)
        assert tag_metric[key_unit] == module_metric[key_unit], \
            logger.error(f'Inconsistent unit in metric <{metric}> for module '
                         f'<{module_name}> with tag <{tag}>.')
        tag_metric[key_value] += module_metric[key_value]
        logger.debug(f'  Total value (module <{module_name}>) = '
                     f'<{module_metric[key_value]}> <{module_metric[key_unit]}>.')

    logger.debug(f'  Total value (tag <{tag}>) = '
                 f'<{tag_metric[key_value]}> <{tag_metric[key_unit]}>.')

    if workload is None:
        logger.success(f'Aggregate metric <{metric}> for tag <{tag}>.')
    else:
        logger.success(f'Aggregate metric <{metric}> for tag <{tag}> '
                       f'in workload <{workload}>.')
    return tag_metric


def aggregate_event_count(
    event_graph: ArchxGraph,
    workload: str = None,
    event: str = None,
) -> float:
    """
    Count how many times `event` executes under `workload` by summing
    count over all paths from workload → event.
    Delegates to Rust for performance.
    """
    result = event_graph.aggregate_event_count(workload=workload, event=event)
    if workload is not None:
        logger.success(f'Aggregate event count for event <{event}> in workload <{workload}>.')
    else:
        logger.success(f'Aggregate event count for event <{event}>.')
    return result
