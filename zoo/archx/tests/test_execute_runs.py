"""Batch execution (<archx -x>) exit codes and failed_runs.txt placement."""

import os
import shutil
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT = os.path.join(REPO, 'examples', 'mac_1_cycle', 'input')
ARCHX = shutil.which('archx')


def good_line(run_dir):
    return (
        f'-a {INPUT}/architecture/example.architecture.yaml '
        f'-m {INPUT}/metric/example.metric.yaml '
        f'-w {INPUT}/workload/example.workload.yaml '
        f'-e {INPUT}/event/example.event.yaml '
        f'-r {run_dir} -c {run_dir}/checkpoint.json'
    )


def bad_line(run_dir):
    return (
        f'-a {INPUT}/architecture/does_not_exist.architecture.yaml '
        f'-m {INPUT}/metric/example.metric.yaml '
        f'-w {INPUT}/workload/example.workload.yaml '
        f'-e {INPUT}/event/example.event.yaml '
        f'-r {run_dir} -c {run_dir}/checkpoint.json'
    )


def write_runs(path, lines):
    with open(path, 'w') as f:
        for line in lines:
            f.write(line + '\n')
    return path


def execute(runs_file, batch_dir):
    assert ARCHX is not None, 'archx console script not on PATH'
    return subprocess.run(
        [ARCHX, '-x', str(runs_file), '-r', str(batch_dir)],
        cwd=REPO, capture_output=True, text=True,
    )


def failing_batch(tmp_path, batch_dir):
    """Run a batch with one failing line; returns its failed_runs.txt path."""
    runs = write_runs(tmp_path / 'runs_bad.txt', [bad_line(tmp_path / 'bad')])
    execute(runs, batch_dir)
    return os.path.join(batch_dir, 'failed_runs.txt')


def test_failing_batch_exits_2_and_writes_failed_runs_in_run_dir(tmp_path):
    batch_dir = tmp_path / 'batch'
    failing = bad_line(tmp_path / 'bad')
    runs = write_runs(tmp_path / 'runs.txt', [failing, good_line(tmp_path / 'good')])

    result = execute(runs, batch_dir)

    assert result.returncode == 2, result.stderr
    failed_file = batch_dir / 'failed_runs.txt'
    assert failed_file.is_file()
    assert failing in failed_file.read_text()


def test_clean_batch_in_same_run_dir_exits_0_and_removes_stale_failed_runs(tmp_path):
    batch_dir = tmp_path / 'batch'
    batch_dir.mkdir()
    failed_file = failing_batch(tmp_path, batch_dir)
    assert os.path.isfile(failed_file)

    runs = write_runs(tmp_path / 'runs_good.txt', [good_line(tmp_path / 'good')])
    result = execute(runs, batch_dir)

    assert result.returncode == 0, result.stderr
    assert not os.path.exists(failed_file)


def test_compile_full_with_failing_run_exits_2(tmp_path):
    """<-compile ... -full> must surface a partial batch failure the same way <-x> does."""
    description = tmp_path / 'description.py'
    description.write_text(
        'import pandas as pd\n\n\n'
        'def description(path):\n'
        f'    rows = [{{"arch_path": "{INPUT}/architecture/{{}}.architecture.yaml".format(name),\n'
        f'             "event_path": "{INPUT}/event/example.event.yaml",\n'
        f'             "metric_path": "{INPUT}/metric/example.metric.yaml",\n'
        f'             "work_path": "{INPUT}/workload/example.workload.yaml",\n'
        '             "run_path": path + "/" + name,\n'
        '             "checkpoint_path": path + "/" + name + "/checkpoint.json"}\n'
        '            for name in ("example", "does_not_exist")]\n'
        '    pd.DataFrame(rows).to_csv(path + "/configurations.csv", index=False)\n'
    )
    run_dir = tmp_path / 'compiled'

    assert ARCHX is not None, 'archx console script not on PATH'
    result = subprocess.run(
        [ARCHX, '-compile', str(description), '-full', '-r', str(run_dir)],
        cwd=REPO, capture_output=True, text=True,
    )

    assert result.returncode == 2, result.stderr
    assert (run_dir / 'failed_runs.txt').is_file()


def test_clean_batch_in_other_run_dir_keeps_first_dirs_failed_runs(tmp_path):
    first_dir = tmp_path / 'first'
    first_dir.mkdir()
    failed_file = failing_batch(tmp_path, first_dir)
    assert os.path.isfile(failed_file)

    second_dir = tmp_path / 'second'
    runs = write_runs(tmp_path / 'runs_good.txt', [good_line(tmp_path / 'good')])
    result = execute(runs, second_dir)

    assert result.returncode == 0, result.stderr
    assert os.path.isfile(failed_file)
    assert not (second_dir / 'failed_runs.txt').exists()
