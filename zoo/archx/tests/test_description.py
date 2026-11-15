import os, shutil

from archx.utils import get_path


RUN_DIR = 'tests/test_description'


def test_compile_description():
    from archx.main import import_compile_module

    run_dir = get_path(RUN_DIR, check_exist=False)
    os.makedirs(run_dir, exist_ok=True)
    compile_module = import_compile_module(get_path('examples/systolic_array/description.py'))
    compile_module.description(path=run_dir)

    configurations = os.path.join(run_dir, 'configurations.csv')
    assert os.path.isfile(configurations)
    with open(configurations) as f:
        rows = [line for line in f if line.strip()]
    assert len(rows) - 1 == 256


def test_cleanup():
    shutil.rmtree(get_path(RUN_DIR))


if __name__ == "__main__":
    test_compile_description()
    test_cleanup()
