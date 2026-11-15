import argparse
import concurrent.futures
import contextlib
import importlib.util
import os
import shutil
import shlex
import sys
import time

import pandas as pd
import pyfiglet
from tqdm import tqdm

from loguru import logger

from archx.architecture import create_architecture_dict, save_architecture_dict
from archx.event import create_event_graph, save_event_graph
from archx.metric import create_metric_dict, create_event_metrics, save_metric_dict
from archx.workload import create_workload_dict, save_workload_dict
from archx.performance import simulate_performance_all_events
from archx.utils import bcolors, write_yaml, read_yaml
from archx.interface import register_interface, unregister_interface, copy_interface
from archx.programming.graph.agraph import _generate_runs, _gui


STEP_SEPARATOR = '----------------------------------------------'
FAILED_RUNS_FILE = 'failed_runs.txt'


def create_argument_parser():
    parser = argparse.ArgumentParser(
        description='Archx is a framework to explore the design space of hardware architecture.')
    parser.add_argument('-r', '--run_dir', type=str, default=None,
                        help = 'Run directory to store outputs.')
    parser.add_argument('-a', '--architecture_yaml', type=str, default=None,
                        help = 'Path to architecture yaml.')
    parser.add_argument('-m', '--metric_yaml', type=str, default=None,
                        help = 'Path to metric yaml.')
    parser.add_argument('-w', '--workload_yaml', type=str, default=None,
                        help = 'Path to workload yaml.')
    parser.add_argument('-e', '--event_yaml', type=str, default=None,
                        help = 'Path to event yaml.')
    parser.add_argument('-c', '--checkpoint', type=str, default=None,
                        help = 'Path to checkpoint, which requires <.json> format.')
    parser.add_argument('-l', '--log_level', type=str, default='INFO',
                        help = 'Level of logger.')
    parser.add_argument('-d', '--delete', action='store_true', default=False,
                        help = 'Delete run directory if it exists.')
    parser.add_argument('-p', '--path', type=str, default=None, help = 'Path to Archx description and performance directory.')
    parser.add_argument('-s', '--save_yaml', action='store_true', default=False, help = 'Save yaml files in run directory.')
    parser.add_argument('-ireg', '--register_interface', action='store_true', default=False, help = 'Register a new interface.')
    parser.add_argument('-iureg', '--unregister_interface', action='store_true', default=False, help = 'Unregister a new interface.')
    parser.add_argument('-icopy', '--copy_interface', action='store_true', default=False, help = 'Copy an existing interface.')
    parser.add_argument('-iname', '--interface_name', type=str, default=None, help = 'Name of the interface.')
    parser.add_argument('-idir', '--interface_dir', type=str, default=None, help = 'Directory of the interface.')

    # frontend programming parse
    parser.add_argument('-compile', '--compile', type=str, default=None,
                        help = 'Path to archx frontent python file for configuration sweeping.')
    parser.add_argument('-extract', '--extract', type=str, default=None,
                        help = 'Extract unfiltered configuration results from generated csv file.')
    parser.add_argument('-f', '--filter', type=str, default=None,
                        help = 'Open GUI to filter configurations from generated csv file.')
    parser.add_argument('-ff', '--filter_full', action='store_true', default=False,
                        help = 'Enable full mode for frontend programming filtering (filter + execute).')
    parser.add_argument('-t', '--tabular', action='store_true', default=False,
                        help = 'Add logger debug to terminal output.')
    parser.add_argument('-x', '--execute', type=str, default=None,
                        help = 'Path to generated configuration runs text file for execution.')
    parser.add_argument('-full', '--full', action='store_true', default=False,
                        help = 'Enable full mode for frontend programming (compile, extract, filter, execute).')

    return parser


def parse_commandline_args():
    """
    parse command line inputs
    """
    parser = create_argument_parser()
    return parser.parse_args()


def print_banner():
    for text, color, kwargs in [
        ('Archx', bcolors.Magenta, {}),
        ('UnaryLab', bcolors.Yellow, {}),
        ('https://github.com/UnaryLab/archx', bcolors.UNDERLINE + bcolors.Green, {'font': 'term'}),
    ]:
        print(color + pyfiglet.figlet_format(text, **kwargs) + bcolors.ENDC)


def configure_import_path(args):
    path = args.path if args.path is not None else os.getcwd()
    path = os.path.abspath(path)
    if path not in sys.path:
        sys.path.insert(0, path)


def delete_run_dir_if_requested(args, log=True):
    if args.delete and os.path.isdir(args.run_dir):
        shutil.rmtree(args.run_dir)
        if log:
            logger.info(f'Delete existing run directory <{args.run_dir}>.')


def handle_interface_command(args):
    assert (args.register_interface + args.unregister_interface + args.copy_interface <= 1), \
        logger.error('Only one interface option can be selected at a time: <-regi>, <-uregi>, or <-copyi>.')

    if args.register_interface:
        assert args.interface_name is not None, \
            logger.error(f'Interface name is required for registration via <-iname>.')
        assert args.interface_dir is not None, \
            logger.error(f'Interface directory is required for registration via <-idir>.')
        register_interface(args.interface_name, args.interface_dir)
        return True

    if args.unregister_interface:
        assert args.interface_name is not None, \
            logger.error(f'Interface name is required for unregistration via <-iname>.')
        unregister_interface(args.interface_name)
        return True

    if args.copy_interface:
        assert args.interface_name is not None, \
            logger.error(f'Interface name is required for copying via <-iname>.')
        assert args.interface_dir is not None, \
            logger.error(f'Interface directory is required for copying via <-idir>.')
        copy_interface(args.interface_name, args.interface_dir)
        return True

    return False


def default_run_dir_from_compile(args):
    """When compiling without an explicit <-r>, derive the run directory from the
    compile file path by dropping its extension (e.g. .../description.py -> .../description/)."""
    if args.compile is not None and args.run_dir is None:
        args.run_dir = os.path.splitext(args.compile)[0]
        logger.info(f'No <-r> given; defaulting run directory to <{args.run_dir}> from compile path <{args.compile}>.')


def prepare_run_dir(args, log=True):
    assert args.run_dir is not None, logger.error(f'Run directory is required via <-r> or <-run_dir>.')
    if not os.path.isdir(args.run_dir):
        os.makedirs(args.run_dir)
        created = True
    else:
        created = False

    if not args.run_dir.endswith('/'):
        args.run_dir += '/'

    if log:
        if created:
            logger.info(f'Create run directory <{args.run_dir}>.')
        else:
            logger.info(f'Find run directory <{args.run_dir}>.')

    return args.run_dir


def configure_logging(args):
    logger.remove()
    output_log = args.run_dir + '/log/archx' + '-' + str(time.time()) + '.log'
    logger.add(output_log, level=args.log_level)

    from archx import set_log_level

    set_log_level(args.log_level)

    if args.tabular:
        logger.add(sys.stdout, level=args.log_level)
        logger.info('Enable logger output to terminal.')

    return output_log


def is_archx_run(args):
    return (
        args.architecture_yaml is not None
        and args.metric_yaml is not None
        and args.workload_yaml is not None
        and args.event_yaml is not None
        and args.checkpoint is not None
    )


def log_step(step, message):
    logger.success(f'\n{STEP_SEPARATOR}\nStep {step}: {message}\n{STEP_SEPARATOR}')


def run_archx(args, output_log):
    assert args.checkpoint.endswith('.json'), \
        logger.error('Invalid event checkpoint format; requires <.json>.')

    log_step(1, 'Create architectue dict')
    architecture_dict = create_architecture_dict(args.architecture_yaml)

    log_step(2, 'Create metric dict')
    metric_dict = create_metric_dict(args.metric_yaml)

    log_step(3, 'Creat workload dict')
    workload_dict = create_workload_dict(args.workload_yaml)

    log_step(4, 'Creat event graph')
    event_graph = create_event_graph(args.event_yaml)

    log_step(5, 'Create metrics for all events and modules')
    event_graph = create_event_metrics(event_graph, architecture_dict, metric_dict, run_dir=args.run_dir)

    log_step(6, 'Simulate performance')
    event_graph = simulate_performance_all_events(event_graph, architecture_dict, workload_dict)

    log_step(7, 'Save event graph and log')
    save_event_graph(event_graph=event_graph, save_path=args.checkpoint)

    if args.save_yaml:
        save_architecture_dict(architecture_dict=architecture_dict, save_path=args.run_dir + '/architecture.yaml')
        save_metric_dict(metric_dict=metric_dict, save_path=args.run_dir + '/metric.yaml')
        save_workload_dict(workload_dict=workload_dict, save_path=args.run_dir + '/workload.yaml')
        write_yaml(args.run_dir + '/event.yaml', read_yaml(args.event_yaml))
        logger.success(f'Save dictionaries to <{args.run_dir}>.')

    logger.success(f'Save log to <{output_log}>.')


def import_compile_module(compile_path):
    assert os.path.isfile(compile_path), logger.error(f'Invalid compile file path <{compile_path}>.')

    spec = importlib.util.spec_from_file_location("compile_module", compile_path)
    compile_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compile_module)

    assert hasattr(compile_module, 'description'), \
        logger.error(f'Compile file <{compile_path}> does not contain <description()> function.')
    return compile_module


def runs_path(args):
    return args.run_dir + '/runs.txt'


def generate_runs_from_csv(csv_path, output_path):
    assert os.path.isfile(csv_path), logger.error(f'Invalid extract csv file <{csv_path}>.')
    df = pd.read_csv(csv_path)
    _generate_runs(df=df, path=output_path)


def filter_runs_from_csv(csv_path, output_path):
    assert os.path.isfile(csv_path), logger.error(f'Invalid filter csv file <{csv_path}>.')
    df = pd.read_csv(csv_path)
    _gui(df=df, path=output_path)


def parse_run_line(line, parent_args, tabular_mode):
    argv = shlex.split(line)
    if tabular_mode and '-t' not in argv and '--tabular' not in argv:
        argv.append(tabular_mode)

    args = create_argument_parser().parse_args(argv)
    if args.path is None:
        args.path = parent_args.path
    if args.path is None:
        args.path = os.getcwd()
    return args


def run_one_config(line, parent_args, tabular_mode):
    args = parse_run_line(line, parent_args, tabular_mode)
    configure_import_path(args)
    delete_run_dir_if_requested(args, log=False)
    prepare_run_dir(args, log=False)
    output_log = configure_logging(args)
    logger.info(f'Run directory <{args.run_dir}> is ready.')

    if not is_archx_run(args):
        raise ValueError(f'Invalid run line <{line}>; missing required ArchX run arguments.')

    run_archx(args, output_log)


def run_one_config_worker(line, parent_args, tabular_mode):
    try:
        run_one_config(line, parent_args, tabular_mode)
        return line, None
    except BaseException as exc:
        return line, repr(exc)


def read_run_lines(execute_path):
    with open(execute_path, 'r') as f:
        return [line.strip() for line in f if line.strip()]


def failed_runs_path(run_dir):
    return os.path.abspath(os.path.join(run_dir, FAILED_RUNS_FILE))


def write_failed_runs(failed_lines, path):
    if failed_lines:
        with open(path, 'w') as f:
            for line in failed_lines:
                f.write(line + '\n')
    else:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)


def execute_runs(execute_path, tabular_mode, parent_args):
    """Run every configuration line in <execute_path>; returns the number of failed runs."""
    assert os.path.isfile(execute_path), logger.error(f'Invalid execute runs file <{execute_path}>.')

    start = time.time()
    failed_path = failed_runs_path(parent_args.run_dir)
    run_lines = read_run_lines(execute_path)
    workers = os.cpu_count() or 1
    failed_lines = []

    logger.info(f'Executing <{len(run_lines)}> runs from <{execute_path}> with <{workers}> workers.')
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(run_one_config_worker, line, parent_args, tabular_mode)
            for line in run_lines
        ]
        completed_runs = tqdm(
            concurrent.futures.as_completed(futures),
            total=len(futures),
            desc='ArchX runs',
            unit='run',
            dynamic_ncols=True,
        )
        for future in completed_runs:
            line, error = future.result()
            if error is not None:
                failed_lines.append(line)
                logger.error(f'Run failed: {line}\n{error}')

    write_failed_runs(failed_lines, failed_path)
    runtime = int(time.time() - start)
    logger.success(f'Execution of runs in <{execute_path}> completed in <{runtime}> seconds.')
    if failed_lines:
        logger.warning(f'Some runs failed. Check <{failed_path}> for failed commands.')
    return len(failed_lines)


def run_compile_mode(args, tabular_mode):
    """Compile the description; with -full also run the batch, returning the failed-run count."""
    compile_module = import_compile_module(args.compile)
    compile_module.description(path=args.run_dir)
    logger.success(f'Compile generation completed in <{args.run_dir}>.')

    if not args.full:
        return 0

    configurations_path = args.run_dir + '/configurations.csv'
    execute_path = runs_path(args)
    generate_runs_from_csv(configurations_path, execute_path)

    if args.filter_full:
        filter_runs_from_csv(configurations_path, execute_path)

    return execute_runs(execute_path, tabular_mode, args)


def run_extract_mode(args):
    generate_runs_from_csv(args.extract, runs_path(args))
    logger.success(f'Extract runs.txt file compiled in <{args.extract}>.')


def run_filter_mode(args):
    filter_runs_from_csv(args.filter, runs_path(args))
    logger.success(f'Filter runs.txt file compiled in <{args.filter}>.')


def main():
    """Exit code: 0 all runs succeeded, 2 the batch ran but some runs failed."""
    args = parse_commandline_args()

    print_banner()
    configure_import_path(args)
    default_run_dir_from_compile(args)
    delete_run_dir_if_requested(args)

    if handle_interface_command(args):
        sys.exit(0)

    prepare_run_dir(args)
    output_log = configure_logging(args)
    tabular_mode = "-t" if args.tabular else ""

    if is_archx_run(args):
        run_archx(args, output_log)
    elif args.compile:
        if run_compile_mode(args, tabular_mode):
            return 2
    elif args.extract:
        run_extract_mode(args)
    elif args.filter:
        run_filter_mode(args)
    elif args.execute:
        if execute_runs(args.execute, tabular_mode, args):
            return 2


if __name__ == '__main__':
    sys.exit(main())
