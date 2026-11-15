# following two lines are used in testing
import shutil

from loguru import logger

from archx.workload import create_workload_dict, save_workload_dict, load_workload_dict
from archx.utils import get_path, check_dict_equal


def test_create_workload_dict():
    workload_file = 'examples/mac_1_cycle/input/workload/example.workload.yaml'
    workload_dict = create_workload_dict(workload_file)
    for module in workload_dict:
        logger.info(module, workload_dict[module], '\n')

    save_workload_dict(workload_dict, 'tests/test_workload/example.workload_dict.yaml')
    workload_dict_loaded = load_workload_dict('tests/test_workload/example.workload_dict.yaml')
    assert check_dict_equal(workload_dict, workload_dict_loaded)


def test_cleanup():
    path = get_path('tests/test_workload/')
    shutil.rmtree(path)


if __name__ == "__main__":
    test_create_workload_dict()
    test_cleanup()

