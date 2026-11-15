# following two lines are used in testing
import sys, shutil

from loguru import logger

from archx.architecture import create_architecture_dict, save_architecture_dict
from archx.event import create_event_graph, save_event_graph
from archx.metric import create_metric_dict, save_metric_dict, aggregate_event_metric, create_event_metrics, query_module_metric, aggregate_tag_metric
from archx.workload import create_workload_dict, save_workload_dict
from archx.performance import simulate_performance_all_events
from archx.utils import get_path


# set up run_name
run_name = 'mac_2_cycle'

input_root = 'examples/' + run_name + '/input/'
output_root = 'tests/' + run_name + '/'

arch_input_file = input_root + 'architecture/example.architecture.yaml'
arch_dict_output_file = output_root + 'example.architecture_dict.yaml'

metric_input_file = input_root + 'metric/example.metric.yaml'
metric_dict_output_file = output_root + 'example.metric_dict.yaml'

event_input_file = input_root + 'event/example.event.yaml'
event_graph_w_perf_output_file = output_root + 'example.event_graph_w_perf.json'

workload_input_file = input_root + 'workload/example.workload.yaml'
workload_dict_output_file = output_root + 'example.workload_dict.yaml'

logger.remove()
logger.add(sys.stderr, level='DEBUG')

logger.info(f'\n----------------------------------------------\nStep 1: Create architectue dict\n----------------------------------------------\n')
architecture_dict = create_architecture_dict(arch_input_file)
save_architecture_dict(architecture_dict=architecture_dict, save_path=arch_dict_output_file)

logger.info(f'\n----------------------------------------------\nStep 2: Create metric dict\n----------------------------------------------\n')
metric_dict = create_metric_dict(metric_input_file)
save_metric_dict(metric_dict=metric_dict, save_path=metric_dict_output_file)

logger.info(f'\n----------------------------------------------\nStep 3: Creat workload dict\n----------------------------------------------\n')
workload_dict = create_workload_dict(workload_input_file)
save_workload_dict(workload_dict=workload_dict, save_path=workload_dict_output_file)

logger.info(f'\n----------------------------------------------\nStep 4: Creat event graph\n----------------------------------------------\n')
event_graph = create_event_graph(event_input_file)
save_event_graph(event_graph=event_graph, save_path=event_graph_w_perf_output_file)

logger.info(f'\n----------------------------------------------\nStep 5: Update metrics for events and modules\n----------------------------------------------\n')
event_graph = create_event_metrics(event_graph, architecture_dict, metric_dict, run_dir=output_root)

logger.info(f'\n----------------------------------------------\nStep 6: Simulate performance\n----------------------------------------------\n')
event_graph = simulate_performance_all_events(event_graph, architecture_dict, workload_dict)


def test_area():
    logger.info(f'\n----------------------------------------------\nStep 7: Aggregate results\n----------------------------------------------\n')

    index = 0

    index += 1
    metric = 'area'
    workload = 'gemm16'
    event = 'sram'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'area'
    workload = 'gemm16'
    event = 'sram_rd'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'area'
    workload = 'gemm16'
    event = 'sram_wr'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'area'
    workload = 'gemm16'
    event = 'mac_array'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'area'
    workload = 'gemm16'
    event = 'gemm16'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')


def test_leakage_power():
    logger.info(f'\n----------------------------------------------\nStep 7: Aggregate results\n----------------------------------------------\n')

    index = 0

    index += 1
    metric = 'leakage_power'
    workload = 'gemm16'
    event = 'sram'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'leakage_power'
    workload = 'gemm16'
    event = 'sram_rd'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'leakage_power'
    workload = 'gemm16'
    event = 'sram_wr'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'leakage_power'
    workload = 'gemm16'
    event = 'mac_array'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'leakage_power'
    workload = 'gemm16'
    event = 'gemm16'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')


def test_dynamic_energy():
    logger.info(f'\n----------------------------------------------\nStep 7: Aggregate results\n----------------------------------------------\n')

    index = 0

    index += 1
    metric = 'dynamic_energy'
    workload = 'gemm16'
    event = 'sram'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')
    
    index += 1
    metric = 'dynamic_energy'
    workload = 'gemm16'
    event = 'sram_rd'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'dynamic_energy'
    workload = 'gemm16'
    event = 'sram_wr'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')
    
    index += 1
    metric = 'dynamic_energy'
    workload = 'gemm16'
    event = 'multiplier'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'dynamic_energy'
    workload = 'gemm16'
    event = 'mac_array'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'dynamic_energy'
    workload = 'gemm16'
    event = 'gemm16'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'dynamic_energy'
    workload = None
    event = 'sram_rd'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'dynamic_energy'
    workload = None
    event = 'sram_wr'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')
    
    index += 1
    metric = 'dynamic_energy'
    workload = None
    event = 'mac_array'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'dynamic_energy'
    workload = None
    event = 'gemm16'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')


def test_cycle_count():
    logger.info(f'\n----------------------------------------------\nStep 7: Aggregate results\n----------------------------------------------\n')

    index = 0

    index += 1
    metric = 'cycle_count'
    workload = 'gemm16'
    event = 'mac_array'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'cycle_count'
    workload = 'gemm32'
    event = 'mac_array'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'cycle_count'
    workload = 'gemm16'
    event = 'gemm16'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'cycle_count'
    workload = None
    event = 'mac_array'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')


def test_runtime():
    logger.info(f'\n----------------------------------------------\nStep 7: Aggregate results\n----------------------------------------------\n')

    index = 0

    index += 1
    metric = 'runtime'
    workload = 'gemm16'
    event = 'mac_array'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'runtime'
    workload = 'gemm32'
    event = 'mac_array'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'runtime'
    workload = 'gemm16'
    event = 'gemm16'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}> in workload <{workload}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'runtime'
    workload = None
    event = 'mac_array'
    logger.info(f'\n\nTest <{index}>: Aggregate <{metric}> for event <{event}>.')
    result = aggregate_event_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, event=event)
    logger.success(f'result <{result}>.')


def test_module():
    logger.info(f'\n----------------------------------------------\nStep 7: Aggregate results\n----------------------------------------------\n')
    index = 0
    index += 1
    metric = 'dynamic_energy'
    workload = None
    module = 'sram'
    logger.info(f'\n\nTest <{index}>: Query <{metric}> for module <{module}>.')
    result = query_module_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, module=module, operation='read')
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'dynamic_energy'
    workload = None
    module = 'multiplier'
    logger.info(f'\n\nTest <{index}>: Query <{metric}> for module <{module}>.')
    result = query_module_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, module=module, operation='read')
    logger.success(f'result <{result}>.')


def test_tag():
    logger.info(f'\n----------------------------------------------\nStep 7: Aggregate results\n----------------------------------------------\n')
    index = 0
    index += 1
    metric = 'area'
    workload = 'gemm16'
    tag = 'onchip'
    logger.info(f'\n\nTest <{index}>: Query <{metric}> for tag <{tag}> in workload <{workload}>.')
    result = aggregate_tag_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, tag=tag)
    logger.success(f'result <{result}>.')

    index += 1
    metric = 'dynamic_energy'
    workload = 'gemm16'
    tag = 'onchip'
    logger.info(f'\n\nTest <{index}>: Query <{metric}> for tag <{tag}>.')
    result = aggregate_tag_metric(event_graph=event_graph, metric_dict=metric_dict, metric=metric, workload=workload, tag=tag)
    logger.success(f'result <{result}>.')


def test_cleanup():
    path = get_path(output_root)
    shutil.rmtree(path)


if __name__ == '__main__':
    test_area()
    test_leakage_power()
    test_dynamic_energy()
    test_cycle_count()
    test_runtime()
    test_module()
    test_tag()
    test_cleanup()

