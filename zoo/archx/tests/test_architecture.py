# following two lines are used in testing
import shutil

from loguru import logger

from archx.architecture import create_architecture_dict, save_architecture_dict, load_architecture_dict
from archx.utils import get_path, check_dict_equal


def test_create_architecture_dict():
    architecture_file = 'examples/mac_1_cycle/input/architecture/example.architecture.yaml'
    architecture_dict = create_architecture_dict(architecture_file)
    for module in architecture_dict:
        logger.info(module)
        print(module, architecture_dict[module], '\n')

    save_architecture_dict(architecture_dict, 'tests/test_architecture/example.architecture_dict.yaml')
    architecture_dict_loaded = load_architecture_dict('tests/test_architecture/example.architecture_dict.yaml')
    assert check_dict_equal(architecture_dict, architecture_dict_loaded)


def test_cleanup():
    path = get_path('tests/test_architecture/')
    shutil.rmtree(path)


if __name__ == "__main__":
    test_create_architecture_dict()
    test_cleanup()

