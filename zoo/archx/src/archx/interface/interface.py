import shutil, os, sys, copy
import importlib.util
import hashlib
import pickle
import tempfile
import time

from collections import OrderedDict
from loguru import logger

from archx.utils import get_path


key_interface = 'interface'
key_cache_env = 'ARCHX_INTERFACE_CACHE_DIR'
key_cache_version = 1
_interface_module_cache = {}
_interface_output_cache = {}
_interface_signature_cache = {}
_lock_poll_seconds = 0.05
_lock_timeout_seconds = 300


def _freeze_cache_value(value):
    if isinstance(value, dict):
        return tuple((k, _freeze_cache_value(v)) for k, v in sorted(value.items()))
    if isinstance(value, list):
        return tuple(_freeze_cache_value(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_freeze_cache_value(v) for v in value)
    return value


def _interface_output_cache_key(module: str, interface: str, query: OrderedDict, input_dir=None):
    if input_dir is not None:
        input_dir = os.path.realpath(input_dir)
    return interface, _freeze_cache_value(query), input_dir


def _interface_cache_dir():
    cache_dir = os.environ.get(key_cache_env)
    if cache_dir is None:
        cache_home = os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))
        cache_dir = os.path.join(cache_home, 'archx', 'interface')
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError as exc:
        logger.warning(f'Disable persistent interface cache; cannot create <{cache_dir}>: {exc}.')
        return None
    return cache_dir


def _interface_signature(interface_dir: str):
    """
    Fingerprint every file under an interface directory, covering the data it reads
    (csv tables, cacti configs, compiled binaries) as well as its own python code.
    Walked once per directory per process.
    """
    if interface_dir not in _interface_signature_cache:
        entries = []
        for root, dir_names, file_names in os.walk(interface_dir):
            dir_names[:] = sorted(name for name in dir_names if name != '__pycache__')
            for file_name in sorted(file_names):
                file_path = os.path.join(root, file_name)
                relative_path = os.path.relpath(file_path, interface_dir)
                try:
                    stat = os.stat(file_path)
                    entries.append((relative_path, stat.st_mtime_ns, stat.st_size))
                except OSError:
                    entries.append((relative_path, None, None))
        signature_payload = (os.path.realpath(interface_dir), entries)
        _interface_signature_cache[interface_dir] = hashlib.sha256(
            pickle.dumps(signature_payload, protocol=pickle.HIGHEST_PROTOCOL)).hexdigest()
    return _interface_signature_cache[interface_dir]


def _interface_cache_path(cache_key, dst_file: str):
    cache_dir = _interface_cache_dir()
    if cache_dir is None:
        return None

    key_payload = (key_cache_version, cache_key, _interface_signature(os.path.dirname(dst_file)))
    cache_hash = hashlib.sha256(pickle.dumps(key_payload, protocol=pickle.HIGHEST_PROTOCOL)).hexdigest()
    return os.path.join(cache_dir, cache_hash + '.pkl')


def _read_interface_disk_cache(cache_path):
    if cache_path is None or not os.path.isfile(cache_path):
        return None
    try:
        with open(cache_path, 'rb') as f:
            return pickle.load(f)
    except (OSError, pickle.PickleError, EOFError) as exc:
        logger.warning(f'Ignore invalid interface cache file <{cache_path}>: {exc}.')
        return None


def _write_interface_disk_cache(cache_path, query_result):
    if cache_path is None:
        return
    cache_dir = os.path.dirname(cache_path)
    try:
        with tempfile.NamedTemporaryFile('wb', dir=cache_dir, delete=False) as f:
            pickle.dump(query_result, f, protocol=pickle.HIGHEST_PROTOCOL)
            temp_path = f.name
        os.replace(temp_path, cache_path)
    except OSError as exc:
        logger.warning(f'Failed to write interface cache file <{cache_path}>: {exc}.')
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)


def _acquire_interface_cache_lock(cache_path):
    if cache_path is None:
        return None
    lock_path = cache_path + '.lock'
    deadline = time.time() + _lock_timeout_seconds
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return lock_path
        except FileExistsError:
            cached = _read_interface_disk_cache(cache_path)
            if cached is not None:
                return None
            if time.time() >= deadline:
                try:
                    os.remove(lock_path)
                except OSError:
                    pass
            time.sleep(_lock_poll_seconds)


def _release_interface_cache_lock(lock_path):
    if lock_path is None:
        return
    try:
        os.remove(lock_path)
    except OSError:
        pass


def _load_interface_module(interface: str, dst_file: str):
    cache_key = os.path.realpath(dst_file)
    if cache_key not in _interface_module_cache:
        spec = importlib.util.spec_from_file_location(
            'query_' + str(interface),
            dst_file,
        )
        module_py = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module_py
        spec.loader.exec_module(module_py)
        _interface_module_cache[cache_key] = module_py
    return _interface_module_cache[cache_key]


def query_interface(module: str, query: OrderedDict, input_dir=None, output_dir=None) -> OrderedDict:
    """
    query is a dictionary with query configurations
    """
    query = copy.deepcopy(query)
    assert key_interface in query, logger.error(f'Invalid query: <{query}>. Must contain <{key_interface}>. Possible undefined attribute in archtitecture dictionary.')
    q_interface = query[key_interface]
    dst_file = os.path.join(os.path.dirname(__file__), q_interface, q_interface + '.py')

    # find proper query interface code
    module_py = _load_interface_module(q_interface, dst_file)
    
    # actual query
    del query[key_interface]
    cache_key = _interface_output_cache_key(module, q_interface, query, input_dir)
    if cache_key in _interface_output_cache:
        return copy.deepcopy(_interface_output_cache[cache_key])

    cache_path = _interface_cache_path(cache_key, dst_file)
    cached_result = _read_interface_disk_cache(cache_path)
    if cached_result is not None:
        _interface_output_cache[cache_key] = copy.deepcopy(cached_result)
        return copy.deepcopy(cached_result)

    lock_path = _acquire_interface_cache_lock(cache_path)
    cached_result = _read_interface_disk_cache(cache_path)
    if cached_result is not None:
        _interface_output_cache[cache_key] = copy.deepcopy(cached_result)
        _release_interface_cache_lock(lock_path)
        return copy.deepcopy(cached_result)

    try:
        query_result = module_py.query(module, q_interface, query, input_dir, output_dir)
        _write_interface_disk_cache(cache_path, query_result)
    finally:
        _release_interface_cache_lock(lock_path)

    _interface_output_cache[cache_key] = copy.deepcopy(query_result)

    return copy.deepcopy(query_result)
    

def register_interface(name: str, interface_dir: str) -> None:
    assert name != key_interface, logger.error(f'Invalid interface name: <{name}>.')
    src_dir = get_path(interface_dir)
    dst_dir = os.path.join(os.path.dirname(__file__), name)
    if os.path.isdir(dst_dir):
        logger.warning(f'Interface <{name}> exists at <{dst_dir}>.')
    else:
        shutil.copytree(src_dir, dst_dir)
        _interface_module_cache.pop(os.path.realpath(os.path.join(dst_dir, name + '.py')), None)
        _interface_output_cache.clear()
        _interface_signature_cache.pop(dst_dir, None)
        logger.success(f'Register interface <{name}> from <{src_dir}> to <{dst_dir}>.')


def unregister_interface(name: str) -> None:
    assert name != key_interface, logger.error(f'Invalid interface name: <{name}>.')
    dst_dir = os.path.join(os.path.dirname(__file__), name)
    if os.path.isdir(dst_dir):
        shutil.rmtree(dst_dir)
        _interface_module_cache.pop(os.path.realpath(os.path.join(dst_dir, name + '.py')), None)
        _interface_output_cache.clear()
        _interface_signature_cache.pop(dst_dir, None)
        logger.success(f'Unregister interface <{name}> to <{dst_dir}>.')
    else:
        logger.warning(f'Interface <{name}> does not exist at <{dst_dir}>.')


def copy_interface(name: str, interface_dir: str) -> None:
    assert name != key_interface, logger.error(f'Invalid interface name: <{name}>.')
    src_dir = os.path.join(os.path.dirname(__file__), name)
    dst_dir = os.path.join(os.getcwd(), interface_dir)
    if os.path.isdir(src_dir) and not os.path.isdir(dst_dir):
        shutil.copytree(src_dir, dst_dir)
        logger.success(f'Copy interface: <{name}> from <{src_dir}> to: <{dst_dir}>.')
    elif not os.path.isdir(src_dir):
        logger.warning(f'Interface <{name}> does not exist at <{src_dir}>.')
    elif os.path.isdir(src_dir):
        logger.warning(f'Interface <{name}> exists at <{dst_dir}>.')
