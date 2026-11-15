import importlib.util
import copy
import hashlib
import os
import pickle
import sys
import sysconfig
import tempfile
import types
from collections import OrderedDict
from collections.abc import Mapping, MutableMapping, MutableSequence, Sequence
from loguru import logger

from archx._core import ArchxGraph
from archx.utils import get_path


key_aggregation = 'aggregation'
key_operation = 'operation'
legal_specified = ['parallel', 'sequential']
key_value = 'value'
key_unit = 'unit'
key_subevent = 'subevent'
key_count = 'count'
key_factor = 'factor'
_function_cache = {}
_performance_output_cache = {}
_performance_dependency_cache = {}
_model_id_cache = {}
_library_roots = tuple({
    os.path.realpath(path)
    for path in (sysconfig.get_paths().get('stdlib'),
                 sysconfig.get_paths().get('purelib'),
                 sysconfig.get_paths().get('platlib'),
                 sys.prefix,
                 sys.base_prefix)
    if path
})
_cache_version = 14
_cache_env = 'ARCHX_PERFORMANCE_CACHE_DIR'
_disable_cache_env = 'ARCHX_DISABLE_PERFORMANCE_CACHE'
_missing = ('__archx_missing__',)
_no_default = object()


class _TrackedAccess:
    def __init__(self):
        self.paths = set()

    def record(self, root, path):
        # Every read is recorded, including reads of paths the model wrote itself:
        # the cache key re-reads each path from the untouched original dict, so an
        # extra path only makes the key more discriminating, never stale.
        self.paths.add((root, tuple(path)))


class _TrackedMapping(MutableMapping):
    def __init__(self, value, root, path, tracker):
        self._value = value
        self._root = root
        self._path = tuple(path)
        self._tracker = tracker

    def __getitem__(self, key):
        return _wrap_tracked(
            self._value[key],
            self._root,
            self._path + (key,),
            self._tracker,
        )

    def __setitem__(self, key, value):
        self._value[key] = value

    def __delitem__(self, key):
        del self._value[key]

    def __iter__(self):
        self._tracker.record(self._root, self._path)
        return iter(self._value)

    def __len__(self):
        self._tracker.record(self._root, self._path)
        return len(self._value)

    def __contains__(self, key):
        self._tracker.record(self._root, self._path + (key,))
        return key in self._value

    # get, setdefault and pop all test membership through __contains__ so that a
    # key being absent is recorded as a dependency; the inherited MutableMapping
    # versions reach __getitem__, which raises KeyError before anything is recorded.
    def get(self, key, default=None):
        if key in self:
            return self[key]
        return default

    def setdefault(self, key, default=None):
        if key in self:
            return self[key]
        self[key] = default
        return default

    def pop(self, key, default=_no_default):
        if key in self:
            value = self[key]
            del self[key]
            return value
        if default is _no_default:
            raise KeyError(key)
        return default

    def keys(self):
        self._tracker.record(self._root, self._path)
        return self._value.keys()

    def values(self):
        self._tracker.record(self._root, self._path)
        return (
            _wrap_tracked(value, self._root, self._path + (key,), self._tracker)
            for key, value in self._value.items()
        )

    def items(self):
        self._tracker.record(self._root, self._path)
        return (
            (key, _wrap_tracked(value, self._root, self._path + (key,), self._tracker))
            for key, value in self._value.items()
        )

    def copy(self):
        self._tracker.record(self._root, self._path)
        return self._value.copy()


class _TrackedSequence(Sequence):
    def __init__(self, value, root, path, tracker):
        self._value = value
        self._root = root
        self._path = tuple(path)
        self._tracker = tracker

    def __getitem__(self, index):
        if isinstance(index, slice):
            self._tracker.record(self._root, self._path)
            return self._value[index]
        return _wrap_tracked(
            self._value[index],
            self._root,
            self._path + (index,),
            self._tracker,
        )

    def __iter__(self):
        self._tracker.record(self._root, self._path)
        return iter(self._value)

    def __len__(self):
        self._tracker.record(self._root, self._path)
        return len(self._value)


class _TrackedList(_TrackedSequence, MutableSequence):
    # A list is addressed by position, so any operation that changes its length shifts
    # every later index: a positional path recorded afterwards would re-read a different
    # element from the original. Those operations record the whole-list path instead,
    # freezing the list into the cache key. Over-discriminating, never stale.
    def __setitem__(self, index, value):
        if isinstance(index, slice):
            self._tracker.record(self._root, self._path)
        self._value[index] = value

    def __delitem__(self, index):
        self._tracker.record(self._root, self._path)
        del self._value[index]

    def insert(self, index, value):
        self._tracker.record(self._root, self._path)
        self._value.insert(index, value)


def _wrap_tracked(value, root, path, tracker):
    if isinstance(value, Mapping):
        return _TrackedMapping(value, root, path, tracker)
    if isinstance(value, list):
        return _TrackedList(value, root, path, tracker)
    if isinstance(value, tuple):
        return _TrackedSequence(value, root, path, tracker)
    tracker.record(root, path)
    return value


def _freeze_cache_value(value):
    if isinstance(value, Mapping):
        return tuple((k, _freeze_cache_value(v)) for k, v in sorted(value.items(), key=lambda item: repr(item[0])))
    if isinstance(value, list) or isinstance(value, tuple):
        return tuple(_freeze_cache_value(v) for v in value)
    return value


def _read_path(root_value, path):
    value = root_value
    try:
        for key in path:
            value = value[key]
    except (KeyError, IndexError, TypeError):
        return _missing
    return value


def _performance_cache_enabled():
    return os.environ.get(_disable_cache_env, '').lower() not in ('1', 'true', 'yes')


def _performance_cache_dir():
    cache_dir = os.environ.get(_cache_env)
    if cache_dir is None:
        cache_home = os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))
        cache_dir = os.path.join(cache_home, 'archx', 'performance')
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError as exc:
        logger.warning(f'Disable persistent performance cache; cannot create <{cache_dir}>: {exc}.')
        return None
    return cache_dir


def _cache_hash(payload):
    return hashlib.sha256(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)).hexdigest()


def _file_metadata(file_path: str):
    real_path = os.path.realpath(file_path)
    try:
        stat = os.stat(real_path)
        return (real_path, stat.st_mtime_ns, stat.st_size)
    except OSError:
        return (real_path, None, None)


def _is_project_file(file_path: str):
    real_path = os.path.realpath(file_path)
    return not any(real_path.startswith(root + os.sep) for root in _library_roots)


def _model_files(performance_model):
    """
    Files whose contents shape a model's result: the module holding it plus the project
    modules it imports, followed transitively. Library modules are left out, they change
    only on reinstall.
    """
    namespace = getattr(performance_model, '__globals__', {})
    files = set()
    if namespace.get('__file__'):
        files.add(os.path.realpath(namespace['__file__']))

    pending, seen = [namespace], set()
    while pending:
        for value in list(pending.pop().values()):
            if isinstance(value, types.ModuleType):
                module = value
            else:
                module = sys.modules.get(getattr(value, '__module__', None))
            if module is None or id(module) in seen:
                continue
            seen.add(id(module))
            module_file = getattr(module, '__file__', None)
            if module_file is None or not _is_project_file(module_file):
                continue
            files.add(os.path.realpath(module_file))
            pending.append(vars(module))
    return files


def _performance_model_id(performance_path: str, event_name: str, performance_model=None):
    full_path = get_path(performance_path)
    cache_key = (os.path.realpath(full_path), event_name)
    if cache_key not in _model_id_cache:
        files = {os.path.realpath(full_path)}
        if performance_model is not None:
            files.update(_model_files(performance_model))
        metadata = tuple(_file_metadata(path) for path in sorted(files))
        _model_id_cache[cache_key] = (_cache_version, event_name, metadata)
    return full_path, _model_id_cache[cache_key]


def _dependency_index_path(model_id):
    cache_dir = _performance_cache_dir()
    if cache_dir is None:
        return None
    return os.path.join(cache_dir, _cache_hash(('dependencies', model_id)) + '.deps.pkl')


def _output_cache_path(output_key):
    cache_dir = _performance_cache_dir()
    if cache_dir is None:
        return None
    return os.path.join(cache_dir, _cache_hash(('output', output_key)) + '.pkl')


def _read_pickle(path):
    if path is None or not os.path.isfile(path):
        return None
    try:
        with open(path, 'rb') as f:
            return pickle.load(f)
    except (OSError, pickle.PickleError, EOFError) as exc:
        logger.warning(f'Ignore invalid performance cache file <{path}>: {exc}.')
        return None


def _write_pickle(path, value):
    if path is None:
        return
    cache_dir = os.path.dirname(path)
    try:
        with tempfile.NamedTemporaryFile('wb', dir=cache_dir, delete=False) as f:
            pickle.dump(value, f, protocol=pickle.HIGHEST_PROTOCOL)
            temp_path = f.name
        os.replace(temp_path, path)
    except OSError as exc:
        logger.warning(f'Failed to write performance cache file <{path}>: {exc}.')
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)


def _dependency_sets(model_id):
    if model_id not in _performance_dependency_cache:
        cached = _read_pickle(_dependency_index_path(model_id))
        _performance_dependency_cache[model_id] = list(cached) if cached is not None else []
    return _performance_dependency_cache[model_id]


def _add_dependency_set(model_id, dependency_paths):
    dependencies = tuple(sorted(dependency_paths))
    dependency_sets = _dependency_sets(model_id)
    if dependencies in dependency_sets:
        return dependencies
    dependency_sets.append(dependencies)
    _write_pickle(_dependency_index_path(model_id), dependency_sets)
    return dependencies


def _dependency_values(dependencies, architecture_dict, workload_dict):
    values = []
    for root, path in dependencies:
        root_value = architecture_dict if root == 'architecture' else workload_dict
        values.append((root, path, _freeze_cache_value(_read_path(root_value, path))))
    return tuple(values)


def _performance_output_key(model_id, dependencies, architecture_dict, workload_dict):
    return model_id, dependencies, _dependency_values(
        dependencies,
        architecture_dict,
        workload_dict,
    )


def _read_performance_output(output_key):
    if output_key in _performance_output_cache:
        return copy.deepcopy(_performance_output_cache[output_key])
    cached = _read_pickle(_output_cache_path(output_key))
    if cached is not None:
        _performance_output_cache[output_key] = copy.deepcopy(cached)
        return copy.deepcopy(cached)
    return None


def _write_performance_output(output_key, performance_dict):
    _performance_output_cache[output_key] = copy.deepcopy(performance_dict)
    _write_pickle(_output_cache_path(output_key), performance_dict)


def _run_performance_model_with_tracing(performance_model, architecture_dict, workload_dict):
    tracker = _TrackedAccess()
    performance_dict = performance_model(
        architecture_dict=_TrackedMapping(copy.deepcopy(architecture_dict), 'architecture', (), tracker),
        workload_dict=_TrackedMapping(copy.deepcopy(workload_dict), 'workload', (), tracker),
    )
    return performance_dict, tracker.paths


def import_function_from_path(file_path: str, function: str) -> callable:
    full_path = get_path(file_path)
    cache_key = (full_path, function)
    if cache_key in _function_cache:
        return _function_cache[cache_key]

    spec = importlib.util.spec_from_file_location(function, full_path)
    module_py = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module_py
    spec.loader.exec_module(module_py)

    if hasattr(module_py, function) and callable(getattr(module_py, function)):
        _function_cache[cache_key] = getattr(module_py, function)
        return _function_cache[cache_key]
    else:
        logger.error(f'Invalid function <{function}> at <{full_path}>.')
        exit()


def simulate_performance_one_event(
    event_graph: ArchxGraph,
    architecture_dict: OrderedDict,
    workload_dict: OrderedDict,
    event_name: str,
) -> ArchxGraph:
    """Run the performance model for a single event node and update graph edges."""

    assert event_graph.has_node(event_name), \
        logger.error(f'Invalid event <{event_name}>.')

    performance_path = event_graph.get_performance_path(event_name)

    if performance_path is None or performance_path == 'None':
        assert event_graph.is_leaf(event_name), \
            logger.error(f'Missing performance model for event <{event_name}>.')
        logger.info(f'Module <{event_name}> has no performance model.')
        return event_graph

    # Load and execute the performance model
    performance_model = import_function_from_path(performance_path, function=event_name)
    full_performance_path, model_id = _performance_model_id(performance_path, event_name, performance_model)
    performance_dict = None
    if _performance_cache_enabled():
        for dependencies in _dependency_sets(model_id):
            output_key = _performance_output_key(
                model_id,
                dependencies,
                architecture_dict,
                workload_dict,
            )
            performance_dict = _read_performance_output(output_key)
            if performance_dict is not None:
                logger.debug(f'Use cached performance for event <{event_name}>.')
                break

    if performance_dict is None:
        if _performance_cache_enabled():
            performance_dict, dependency_paths = _run_performance_model_with_tracing(
                performance_model,
                architecture_dict,
                workload_dict,
            )
            dependencies = _add_dependency_set(model_id, dependency_paths)
            output_key = _performance_output_key(
                model_id,
                dependencies,
                architecture_dict,
                workload_dict,
            )
            _write_performance_output(output_key, performance_dict)
        else:
            performance_dict = performance_model(
                architecture_dict=copy.deepcopy(architecture_dict),
                workload_dict=copy.deepcopy(workload_dict),
            )
    assert performance_dict is not None, \
        logger.error(f'No performance model returned for event <{event_name}>')

    # Handle extra metrics returned by performance models (used in 'specified' mode).
    # These are stored as specified_metrics on the node.
    if len(performance_dict) > 1:
        for metric_key in performance_dict:
            if metric_key == key_subevent:
                continue
            val = performance_dict[metric_key]
            event_graph.set_node_specified_metric(
                event_name,
                metric_key,
                float(val[key_value]),
                str(val[key_unit]),
            )

    # Update edge properties for each out-neighbour
    for target_name in event_graph.get_out_neighbors(event_name):
        assert target_name in performance_dict[key_subevent], \
            logger.error(f'  Missing subevent <{target_name}> in the '
                         f'<{event_name}> performance model.')

        subevent_cfg = performance_dict[key_subevent][target_name]

        # count
        if key_count not in subevent_cfg:
            event_graph.set_edge_count(event_name, target_name, 1.0)
            logger.warning(f'  Missing count in subevent <{target_name}>; default to 1.')
        else:
            event_graph.set_edge_count(event_name, target_name,
                                       float(subevent_cfg[key_count]))

        # aggregation
        if key_aggregation in subevent_cfg:
            agg = subevent_cfg[key_aggregation].lower()
            assert agg in legal_specified, \
                logger.error(f'  Invalid aggregation <{subevent_cfg[key_aggregation]}> in the performance model of '
                             f'event <{event_name}> at <{performance_path}>; '
                             f'legal values: {legal_specified}.')
            event_graph.set_edge_aggregation(event_name, target_name, agg)
            if event_graph.is_leaf(target_name):
                logger.warning(f'  Ignore aggregation <{agg}> between event '
                               f'<{event_name}> and module <{target_name}>; '
                               f'aggregation only takes effect between events.')
        else:
            logger.warning(f'  Missing aggregation in subevent <{target_name}>; '
                           f'default to <parallel>.')
            event_graph.set_edge_aggregation(event_name, target_name, 'parallel')

        # operation (only valid for module targets)
        if key_operation in subevent_cfg:
            assert event_graph.is_leaf(target_name), \
                logger.error(f'  Invalid operation between event <{event_name}> '
                             f'and event <{target_name}>; operation should be '
                             f'between event and module.')
            event_graph.set_edge_operation(event_name, target_name,
                                           dict(subevent_cfg[key_operation]))

        # factor
        if key_factor in subevent_cfg:
            factor = subevent_cfg[key_factor]
            assert isinstance(factor, dict), \
                logger.error(f'  Invalid factor <{factor}> between event <{event_name}> '
                             f'and module <{target_name}>; factor should be a dict.')
            event_graph.set_edge_factor(event_name, target_name,
                                        {k: float(v) for k, v in factor.items()})

        edge_count = event_graph.get_edge_count(event_name, target_name)
        edge_agg = event_graph.get_edge_aggregation(event_name, target_name)
        logger.debug(f'  Event <{event_name}> has <{edge_count}> subevent '
                     f'<{target_name}> with specified aggregation <{edge_agg}>.')

    logger.success(f'Simulate event <{event_name}> at <{performance_path}>.')
    return event_graph


def simulate_performance_all_events(
    event_graph: ArchxGraph,
    architecture_dict: OrderedDict,
    workload_dict: OrderedDict,
) -> ArchxGraph:
    for event_name in event_graph.get_all_node_names():
        event_graph = simulate_performance_one_event(
            event_graph, architecture_dict, workload_dict, event_name)

    logger.success('Simulate all events.')
    return event_graph
