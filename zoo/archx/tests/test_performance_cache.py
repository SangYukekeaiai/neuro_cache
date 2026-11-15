import importlib
from collections import OrderedDict
from collections.abc import MutableSequence

from archx.performance import simulate_performance_one_event


class DummyEventGraph:
    def __init__(self, performance_path, node_name='kernel'):
        self.performance_path = performance_path
        self.node_name = node_name

    def has_node(self, event_name):
        return event_name == self.node_name

    def get_performance_path(self, event_name):
        return self.performance_path

    def is_leaf(self, event_name):
        return True

    def get_out_neighbors(self, event_name):
        return []


def test_performance_cache_uses_traced_dependencies(monkeypatch, tmp_path):
    performance_module = importlib.import_module('archx.performance.performance')
    performance_module._performance_output_cache.clear()
    performance_module._performance_dependency_cache.clear()
    monkeypatch.setenv('ARCHX_PERFORMANCE_CACHE_DIR', str(tmp_path / 'cache'))

    count_file = tmp_path / 'calls.txt'
    count_file.write_text('0')
    monkeypatch.setenv('ARCHX_TEST_COUNT_FILE', str(count_file))

    performance_file = tmp_path / 'kernel.performance.py'
    performance_file.write_text(
        "from collections import OrderedDict\n"
        "import os\n"
        "\n"
        "def kernel(architecture_dict, workload_dict=None):\n"
        "    count_file = os.environ['ARCHX_TEST_COUNT_FILE']\n"
        "    calls = int(open(count_file).read()) + 1\n"
        "    open(count_file, 'w').write(str(calls))\n"
        "    _ = architecture_dict['used']['value'] * workload_dict['configuration']['m']\n"
        "    return OrderedDict({'subevent': OrderedDict()})\n"
    )

    graph = DummyEventGraph(str(performance_file))
    first_arch = OrderedDict({
        'used': OrderedDict({'value': 4}),
        'irrelevant': OrderedDict({'value': 1}),
    })
    second_arch = OrderedDict({
        'used': OrderedDict({'value': 4}),
        'irrelevant': OrderedDict({'value': 999}),
    })
    workload = OrderedDict({'configuration': OrderedDict({'m': 8, 'unused': 1})})

    simulate_performance_one_event(graph, first_arch, workload, 'kernel')
    simulate_performance_one_event(graph, second_arch, workload, 'kernel')

    assert count_file.read_text() == '1'

    changed_arch = OrderedDict({
        'used': OrderedDict({'value': 5}),
        'irrelevant': OrderedDict({'value': 999}),
    })
    simulate_performance_one_event(graph, changed_arch, workload, 'kernel')

    assert count_file.read_text() == '2'

    performance_module._performance_output_cache.clear()
    performance_module._performance_dependency_cache.clear()


def test_performance_cache_allows_model_to_write_derived_inputs(monkeypatch, tmp_path):
    performance_module = importlib.import_module('archx.performance.performance')
    performance_module._performance_output_cache.clear()
    performance_module._performance_dependency_cache.clear()
    monkeypatch.setenv('ARCHX_PERFORMANCE_CACHE_DIR', str(tmp_path / 'cache'))

    count_file = tmp_path / 'calls.txt'
    count_file.write_text('0')
    monkeypatch.setenv('ARCHX_TEST_COUNT_FILE', str(count_file))

    performance_file = tmp_path / 'derived.performance.py'
    performance_file.write_text(
        "from collections import OrderedDict\n"
        "import os\n"
        "\n"
        "def derived(architecture_dict, workload_dict=None):\n"
        "    count_file = os.environ['ARCHX_TEST_COUNT_FILE']\n"
        "    calls = int(open(count_file).read()) + 1\n"
        "    open(count_file, 'w').write(str(calls))\n"
        "    configuration = workload_dict['configuration']\n"
        "    configuration.update({'derived': configuration['src'] * 2})\n"
        "    _ = configuration['derived']\n"
        "    return OrderedDict({'subevent': OrderedDict()})\n"
    )

    graph = DummyEventGraph(str(performance_file), node_name='derived')
    architecture = OrderedDict({'used': OrderedDict({'value': 4})})
    workload = OrderedDict({'configuration': OrderedDict({'src': 3, 'unused': 1})})

    simulate_performance_one_event(graph, architecture, workload, 'derived')

    assert count_file.read_text() == '1'
    assert 'derived' not in workload['configuration']

    unread_changed = OrderedDict({'configuration': OrderedDict({'src': 3, 'unused': 999})})
    simulate_performance_one_event(graph, architecture, unread_changed, 'derived')

    assert count_file.read_text() == '1'

    src_changed = OrderedDict({'configuration': OrderedDict({'src': 5, 'unused': 999})})
    simulate_performance_one_event(graph, architecture, src_changed, 'derived')

    assert count_file.read_text() == '2'

    performance_module._performance_output_cache.clear()
    performance_module._performance_dependency_cache.clear()


def _tracked_model(monkeypatch, tmp_path, name, body):
    """Build a performance model whose body is `body` and that counts its own calls."""
    performance_module = importlib.import_module('archx.performance.performance')
    performance_module._performance_output_cache.clear()
    performance_module._performance_dependency_cache.clear()
    monkeypatch.setenv('ARCHX_PERFORMANCE_CACHE_DIR', str(tmp_path / 'cache'))

    count_file = tmp_path / 'calls.txt'
    count_file.write_text('0')
    monkeypatch.setenv('ARCHX_TEST_COUNT_FILE', str(count_file))

    performance_file = tmp_path / f'{name}.performance.py'
    performance_file.write_text(
        "from collections import OrderedDict\n"
        "import os\n"
        "\n"
        f"def {name}(architecture_dict, workload_dict=None):\n"
        "    count_file = os.environ['ARCHX_TEST_COUNT_FILE']\n"
        "    calls = int(open(count_file).read()) + 1\n"
        "    open(count_file, 'w').write(str(calls))\n"
        + body
        + "    return OrderedDict({'subevent': OrderedDict()})\n"
    )
    return DummyEventGraph(str(performance_file), node_name=name), count_file


# The pop override itself is covered by test_pop_default_on_absent_key_records_the_absence;
# for a key that is present, the override and the inherited pop record the same path.
def test_read_through_alias_of_popped_key_stays_a_dependency(monkeypatch, tmp_path):
    graph, count_file = _tracked_model(
        monkeypatch, tmp_path, 'popped',
        "    configuration = workload_dict.pop('configuration')\n"
        "    _ = configuration['batch']\n",
    )
    architecture = OrderedDict({'used': OrderedDict({'value': 4})})

    simulate_performance_one_event(
        graph, architecture, OrderedDict({'configuration': OrderedDict({'batch': 8})}), 'popped')
    assert count_file.read_text() == '1'

    simulate_performance_one_event(
        graph, architecture, OrderedDict({'configuration': OrderedDict({'batch': 9})}), 'popped')
    assert count_file.read_text() == '2'


def test_sequence_write_keeps_other_indices_as_dependencies(monkeypatch, tmp_path):
    graph, count_file = _tracked_model(
        monkeypatch, tmp_path, 'dims',
        "    shape = workload_dict['shape']\n"
        "    shape[0] = shape[0] * 2\n"
        "    _ = shape[1]\n",
    )
    architecture = OrderedDict({'used': OrderedDict({'value': 4})})

    simulate_performance_one_event(
        graph, architecture, OrderedDict({'shape': [2, 3]}), 'dims')
    assert count_file.read_text() == '1'

    simulate_performance_one_event(
        graph, architecture, OrderedDict({'shape': [2, 4]}), 'dims')
    assert count_file.read_text() == '2'


def test_read_through_alias_of_overwritten_key_stays_a_dependency(monkeypatch, tmp_path):
    graph, count_file = _tracked_model(
        monkeypatch, tmp_path, 'alias',
        "    original = workload_dict['configuration']\n"
        "    workload_dict['configuration'] = OrderedDict({'src': 0})\n"
        "    _ = original['src']\n",
    )
    architecture = OrderedDict({'used': OrderedDict({'value': 4})})

    simulate_performance_one_event(
        graph, architecture, OrderedDict({'configuration': OrderedDict({'src': 3})}), 'alias')
    assert count_file.read_text() == '1'

    simulate_performance_one_event(
        graph, architecture, OrderedDict({'configuration': OrderedDict({'src': 5})}), 'alias')
    assert count_file.read_text() == '2'


def test_setdefault_on_absent_key_records_the_absence(monkeypatch, tmp_path):
    graph, count_file = _tracked_model(
        monkeypatch, tmp_path, 'defaulted',
        "    configuration = workload_dict['configuration']\n"
        "    _ = configuration.setdefault('heads', 8)\n",
    )
    architecture = OrderedDict({'used': OrderedDict({'value': 4})})

    simulate_performance_one_event(
        graph, architecture, OrderedDict({'configuration': OrderedDict({'src': 1})}), 'defaulted')
    assert count_file.read_text() == '1'

    supplied = OrderedDict({'configuration': OrderedDict({'src': 1, 'heads': 99})})
    simulate_performance_one_event(graph, architecture, supplied, 'defaulted')
    assert count_file.read_text() == '2'


def test_pop_default_on_absent_key_records_the_absence(monkeypatch, tmp_path):
    graph, count_file = _tracked_model(
        monkeypatch, tmp_path, 'popdefault',
        "    configuration = workload_dict['configuration']\n"
        "    _ = configuration.pop('heads', 8)\n",
    )
    architecture = OrderedDict({'used': OrderedDict({'value': 4})})

    simulate_performance_one_event(
        graph, architecture, OrderedDict({'configuration': OrderedDict({'src': 1})}), 'popdefault')
    assert count_file.read_text() == '1'

    supplied = OrderedDict({'configuration': OrderedDict({'src': 1, 'heads': 99})})
    simulate_performance_one_event(graph, architecture, supplied, 'popdefault')
    assert count_file.read_text() == '2'


def test_list_pop_then_negative_read_is_not_stale(monkeypatch, tmp_path):
    graph, count_file = _tracked_model(
        monkeypatch, tmp_path, 'poplist',
        "    shape = workload_dict['shape']\n"
        "    shape.pop()\n"
        "    _ = shape[-1]\n",
    )
    architecture = OrderedDict({'used': OrderedDict({'value': 4})})

    simulate_performance_one_event(
        graph, architecture, OrderedDict({'shape': [1, 2, 9]}), 'poplist')
    assert count_file.read_text() == '1'

    # the model reads 2 then 5; a positional dependency alone cannot tell the two apart
    simulate_performance_one_event(
        graph, architecture, OrderedDict({'shape': [1, 5, 9]}), 'poplist')
    assert count_file.read_text() == '2'


def test_list_insert_then_positional_read_is_not_stale(monkeypatch, tmp_path):
    graph, count_file = _tracked_model(
        monkeypatch, tmp_path, 'inslist',
        "    shape = workload_dict['shape']\n"
        "    shape.insert(0, 0)\n"
        "    _ = shape[1]\n",
    )
    architecture = OrderedDict({'used': OrderedDict({'value': 4})})

    simulate_performance_one_event(
        graph, architecture, OrderedDict({'shape': [7, 3]}), 'inslist')
    assert count_file.read_text() == '1'

    # the model reads 7 then 8
    simulate_performance_one_event(
        graph, architecture, OrderedDict({'shape': [8, 3]}), 'inslist')
    assert count_file.read_text() == '2'


def test_list_delete_then_positional_read_is_not_stale(monkeypatch, tmp_path):
    graph, count_file = _tracked_model(
        monkeypatch, tmp_path, 'dellist',
        "    shape = workload_dict['shape']\n"
        "    del shape[0]\n"
        "    _ = shape[0]\n",
    )
    architecture = OrderedDict({'used': OrderedDict({'value': 4})})

    simulate_performance_one_event(
        graph, architecture, OrderedDict({'shape': [4, 3]}), 'dellist')
    assert count_file.read_text() == '1'

    # the model reads 3 then 6
    simulate_performance_one_event(
        graph, architecture, OrderedDict({'shape': [4, 6]}), 'dellist')
    assert count_file.read_text() == '2'


def test_list_slice_assign_then_positional_read_is_not_stale(monkeypatch, tmp_path):
    graph, count_file = _tracked_model(
        monkeypatch, tmp_path, 'slicesetlist',
        "    shape = workload_dict['shape']\n"
        "    shape[0:1] = [0, 0]\n"
        "    _ = shape[2]\n",
    )
    architecture = OrderedDict({'used': OrderedDict({'value': 4})})

    simulate_performance_one_event(
        graph, architecture, OrderedDict({'shape': [7, 3]}), 'slicesetlist')
    assert count_file.read_text() == '1'

    # the model reads 3 then 6, at an index the original list does not even have
    simulate_performance_one_event(
        graph, architecture, OrderedDict({'shape': [7, 6]}), 'slicesetlist')
    assert count_file.read_text() == '2'


def test_list_slice_delete_then_positional_read_is_not_stale(monkeypatch, tmp_path):
    graph, count_file = _tracked_model(
        monkeypatch, tmp_path, 'slicedellist',
        "    shape = workload_dict['shape']\n"
        "    del shape[0:1]\n"
        "    _ = shape[0]\n",
    )
    architecture = OrderedDict({'used': OrderedDict({'value': 4})})

    simulate_performance_one_event(
        graph, architecture, OrderedDict({'shape': [4, 3, 5]}), 'slicedellist')
    assert count_file.read_text() == '1'

    # the model reads 3 then 6
    simulate_performance_one_event(
        graph, architecture, OrderedDict({'shape': [4, 6, 5]}), 'slicedellist')
    assert count_file.read_text() == '2'


def test_tracked_tuple_does_not_advertise_mutation():
    performance_module = importlib.import_module('archx.performance.performance')
    tracker = performance_module._TrackedAccess()

    wrapped_tuple = performance_module._wrap_tracked((1, 2), 'workload', ('shape',), tracker)
    assert not isinstance(wrapped_tuple, MutableSequence)
    assert not hasattr(wrapped_tuple, 'append')
    assert wrapped_tuple[1] == 2

    wrapped_list = performance_module._wrap_tracked([1, 2], 'workload', ('shape',), tracker)
    assert isinstance(wrapped_list, MutableSequence)
