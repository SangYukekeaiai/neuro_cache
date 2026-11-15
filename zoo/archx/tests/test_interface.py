# following two lines are used in testing
import shutil
import importlib

import pytest
from loguru import logger

from archx.interface import query_interface, register_interface, unregister_interface, copy_interface
from archx.interface.cacti7.cacti7 import cacti7_run
from archx.interface.cacti_fn.cacti_fn import cacti_fn_run, cacti_fn_signature, parse_report_sram as parse_report_sram_fn, query as query_cacti_fn
from archx.utils import get_path, create_dir


def test_query_interface_csv_cmos():
    module = 'ireg'
    query = {
        'class': 'multiplier',
        'interface': 'csv_cmos',
        'technology': 45,
        'frequency': 400,
        'width': 32
    }
    output = query_interface(module, query)
    logger.info('test_query_interface_csv_cmos: ', output)


def test_query_interface_output_cache(monkeypatch, tmp_path):
    interface_module = importlib.import_module('archx.interface.interface')
    interface_module._interface_output_cache.clear()
    monkeypatch.setenv('ARCHX_INTERFACE_CACHE_DIR', str(tmp_path))

    class DummyInterface:
        calls = 0

        @staticmethod
        def query(name, interface, query, input_dir=None, output_dir=None):
            DummyInterface.calls += 1
            return {'area': {'value': DummyInterface.calls, 'unit': 'mm^2'}}

    monkeypatch.setattr(
        interface_module,
        '_load_interface_module',
        lambda interface, dst_file: DummyInterface,
    )

    query = {'class': 'mac', 'interface': 'dummy_cache', 'width': 32}
    first = query_interface('mac0', query, output_dir='/tmp/run0')
    first['area']['value'] = 999

    second = query_interface('mac1', query, output_dir='/tmp/run1')

    assert DummyInterface.calls == 1
    assert second == {'area': {'value': 1, 'unit': 'mm^2'}}

    interface_module._interface_output_cache.clear()


def test_query_interface_persistent_output_cache(monkeypatch, tmp_path):
    interface_module = importlib.import_module('archx.interface.interface')
    interface_module._interface_output_cache.clear()
    monkeypatch.setenv('ARCHX_INTERFACE_CACHE_DIR', str(tmp_path))

    class DummyInterface:
        calls = 0

        @staticmethod
        def query(name, interface, query, input_dir=None, output_dir=None):
            DummyInterface.calls += 1
            return {'area': {'value': DummyInterface.calls, 'unit': 'mm^2'}}

    monkeypatch.setattr(
        interface_module,
        '_load_interface_module',
        lambda interface, dst_file: DummyInterface,
    )

    query = {'class': 'mac', 'interface': 'dummy_persistent_cache', 'width': 32}
    first = query_interface('mac0', query, output_dir='/tmp/run0')
    interface_module._interface_output_cache.clear()
    second = query_interface('mac1', query, output_dir='/tmp/run1')

    assert DummyInterface.calls == 1
    assert first == second == {'area': {'value': 1, 'unit': 'mm^2'}}

    interface_module._interface_output_cache.clear()


def test_cacti7_run_uses_platform_binary_directly(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, cwd=None, stdout=None, check=None):
        calls.append({'cmd': cmd, 'cwd': cwd, 'check': check})
        stdout.write('fake cacti report')

    def fail_call(*args, **kwargs):
        raise AssertionError('cacti7_run should not use shell copy/remove commands')

    monkeypatch.setattr('archx.interface.cacti7.cacti7.platform.system', lambda: 'Linux')
    monkeypatch.setattr('archx.interface.cacti7.cacti7.platform.machine', lambda: 'x86_64')
    monkeypatch.setattr('archx.interface.cacti7.cacti7.subprocess.run', fake_run)
    monkeypatch.setattr('archx.interface.cacti7.cacti7.subprocess.call', fail_call)

    origin_cfg = tmp_path / 'origin.cfg'
    target_cfg = tmp_path / 'target.cfg'
    result_file = tmp_path / 'result.rpt'
    origin_cfg.write_text('-dummy option 1\n')

    cacti7_run(
        'sram',
        45,
        {'width': 16, 'depth': 512, 'bank': 32},
        origin_cfg_file=str(origin_cfg),
        target_cfg_file=str(target_cfg),
        result_file=str(result_file),
    )

    assert len(calls) == 1
    assert calls[0]['cmd'][0] == './cacti-Linux-x86_64'
    assert calls[0]['cmd'][1:] == ['-infile', str(target_cfg)]
    assert calls[0]['check'] is True
    assert result_file.read_text() == 'fake cacti report'


@pytest.mark.parametrize('interface,technology,block_key,bus_key,size_key', [
    ('cacti7', 45, '-block size (bytes)', '-output/input bus width', '-size (bytes)'),
    ('cacti_fn', 14, '-block size', '-bus width', '-size'),
])
def test_cacti_run_rounds_width_to_bytes(monkeypatch, tmp_path, interface, technology,
                                       block_key, bus_key, size_key):
    module = importlib.import_module(f'archx.interface.{interface}.{interface}')
    monkeypatch.setattr(module.os.path, 'exists', lambda path: True)
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: None)
    origin_cfg = tmp_path / 'origin.cfg'
    target_cfg = tmp_path / 'target.cfg'
    origin_cfg.write_text('')
    knobs = {'width': 7, 'depth': 1024, 'bank': 4}
    messages = []
    sink = logger.add(messages.append, format='{message}', level='WARNING')
    try:
        getattr(module, f'{interface}_run')(
            'sram', technology, knobs,
            origin_cfg_file=str(origin_cfg), target_cfg_file=str(target_cfg),
            result_file=str(tmp_path / 'result.rpt'),
        )
    finally:
        logger.remove(sink)

    lines = target_cfg.read_text().splitlines()
    assert f'{block_key} 1' in lines
    assert f'{bus_key} 8' in lines
    assert f'{size_key} 4096' in lines
    assert knobs['width'] == 7
    assert any(f'width <7> rounded up to 8 bits (1 bytes) for {interface}' in message for message in messages)


def test_cacti_fn_run_writes_finfet_config(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, cwd=None, stdout=None, check=None):
        calls.append({'cmd': cmd, 'cwd': cwd, 'check': check})
        stdout.write('fake fn-cacti report')

    monkeypatch.setattr('archx.interface.cacti_fn.cacti_fn.platform.system', lambda: 'Linux')
    monkeypatch.setattr('archx.interface.cacti_fn.cacti_fn.platform.machine', lambda: 'x86_64')
    monkeypatch.setattr('archx.interface.cacti_fn.cacti_fn.os.path.exists', lambda path: True)
    monkeypatch.setattr('archx.interface.cacti_fn.cacti_fn.subprocess.run', fake_run)

    origin_cfg = tmp_path / 'origin.cfg'
    target_cfg = tmp_path / 'target.cfg'
    result_file = tmp_path / 'result.rpt'
    origin_cfg.write_text('-dummy option 1\n')

    cacti_fn_run(
        'sram',
        14,
        {'width': 64, 'depth': 1024, 'bank': 32, 'wire_technology': 7},
        origin_cfg_file=str(origin_cfg),
        target_cfg_file=str(target_cfg),
        result_file=str(result_file),
    )

    cfg = target_cfg.read_text()
    for line in ['-transistor type - "finfet"', '-technology node 0.014', '-wire technology node 0.007',
                 '-operating voltage 0.7', '-size 262144', '-block size 8', '-bus width 64', '-uca bank 32',
                 '-memory type "ram"', '-associativity 1', '-tag size "default"',
                 '-read-write port 0', '-exclusive read port 1', '-exclusive write port 1',
                 '-access mode - "normal"', '-dummy option 1']:
        assert line in cfg, line
    assert calls[0]['cmd'] == ['./cacti-Linux-x86_64', '-infile', str(target_cfg)]
    assert calls[0]['check'] is True
    assert '-device file' not in cfg
    assert '-sram cell file' not in cfg


@pytest.mark.parametrize('technology,transistor,voltage', [
    (7, 'finfet', 0.7),
    (14, 'cmos', 0.8),
    (22, 'cmos', 0.8),
])
def test_cacti_fn_run_writes_xml_config(monkeypatch, tmp_path, technology, transistor,
                                       voltage):
    monkeypatch.setattr('archx.interface.cacti_fn.cacti_fn.os.path.exists', lambda path: True)
    monkeypatch.setattr('archx.interface.cacti_fn.cacti_fn.subprocess.run', lambda *args, **kwargs: None)
    origin_cfg = tmp_path / 'origin.cfg'
    target_cfg = tmp_path / 'target.cfg'
    origin_cfg.write_text('-dummy option 1\n')

    cacti_fn_run(
        'sram', technology,
        {'width': 64, 'depth': 1024, 'bank': 4, 'transistor': transistor},
        origin_cfg_file=str(origin_cfg), target_cfg_file=str(target_cfg),
        result_file=str(tmp_path / 'result.rpt'),
    )

    cfg = target_cfg.read_text()
    assert f'-technology node {technology / 1000}' in cfg
    assert f'-transistor type - "{transistor}"' in cfg
    assert f'-operating voltage {voltage}' in cfg
    if transistor == 'cmos':
        assert '-device file' not in cfg
    else:
        assert '-device file - "xmls/devices/finfet_7nm_0p7.xml"' in cfg
    assert '-sram cell file' not in cfg


def test_cacti_fn_run_writes_scaled_7nm_config(monkeypatch, tmp_path):
    monkeypatch.setattr('archx.interface.cacti_fn.cacti_fn.os.path.exists', lambda path: True)
    monkeypatch.setattr('archx.interface.cacti_fn.cacti_fn.subprocess.run', lambda *args, **kwargs: None)
    origin_cfg = tmp_path / 'origin.cfg'
    target_cfg = tmp_path / 'target.cfg'
    origin_cfg.write_text('-dummy option 1\n')

    cacti_fn_run(
        'sram', 7,
        {'width': 64, 'depth': 1024, 'bank': 4, 'voltage': 0.7},
        origin_cfg_file=str(origin_cfg), target_cfg_file=str(target_cfg),
        result_file=str(tmp_path / 'result.rpt'),
    )

    cfg = target_cfg.read_text()
    assert '-operating voltage 0.7' in cfg
    assert '-device file - "xmls/devices/finfet_7nm_0p7.xml"' in cfg


@pytest.mark.parametrize('access_mode', [None, 'sequential'])
def test_cacti_fn_run_writes_cache_config(monkeypatch, tmp_path, access_mode):
    monkeypatch.setattr('archx.interface.cacti_fn.cacti_fn.os.path.exists', lambda path: True)
    monkeypatch.setattr('archx.interface.cacti_fn.cacti_fn.subprocess.run', lambda *args, **kwargs: None)
    origin_cfg = tmp_path / 'origin.cfg'
    target_cfg = tmp_path / 'target.cfg'
    origin_cfg.write_text('')

    knobs = {'size': 2097152 * 8, 'width': 512, 'associativity': 16, 'bank': 16}
    if access_mode is not None:
        knobs['access_mode'] = access_mode
    cacti_fn_run(
        'cache', 14, knobs,
        origin_cfg_file=str(origin_cfg), target_cfg_file=str(target_cfg),
        result_file=str(tmp_path / 'result.rpt'),
    )

    lines = target_cfg.read_text().splitlines()
    for line in ['-size 2097152', '-block size 64', '-bus width 512', '-uca bank 16',
                 '-associativity 16', '-memory type "cache"', '-tag size "default"',
                 '-read-write port 1', '-exclusive read port 0', '-exclusive write port 0',
                 f'-access mode - "{access_mode or "normal"}"']:
        assert line in lines


def test_cacti_fn_run_rejects_fully_associative_cache():
    with pytest.raises(AssertionError):
        cacti_fn_run('cache', 14, {'size': 2097152 * 8, 'width': 512,
                                 'associativity': 0, 'bank': 16})


def test_cacti_fn_run_rejects_invalid_cache_access_mode():
    with pytest.raises(AssertionError):
        cacti_fn_run('cache', 14, {'size': 2097152 * 8, 'width': 512,
                                 'associativity': 16, 'bank': 16, 'access_mode': 'invalid'})


def test_cacti_fn_run_rejects_5nm_devices():
    with pytest.raises(AssertionError, match='Unsupported device <5 nm finfet>'):
        cacti_fn_run('sram', 5, {'width': 64, 'depth': 1024, 'bank': 4})


def test_cacti_fn_run_writes_xml_overrides(monkeypatch, tmp_path):
    monkeypatch.setattr('archx.interface.cacti_fn.cacti_fn.os.path.exists', lambda path: True)
    monkeypatch.setattr('archx.interface.cacti_fn.cacti_fn.subprocess.run', lambda *args, **kwargs: None)
    origin_cfg = tmp_path / 'origin.cfg'
    target_cfg = tmp_path / 'target.cfg'
    origin_cfg.write_text('-dummy option 1\n')

    cacti_fn_run(
        'sram', 7,
        {'width': 64, 'depth': 1024, 'bank': 4, 'voltage': 0.30,
         'device_file': 'custom/device.xml', 'sram_cell_file': 'custom/cell.xml'},
        origin_cfg_file=str(origin_cfg), target_cfg_file=str(target_cfg),
        result_file=str(tmp_path / 'result.rpt'),
    )

    cfg = target_cfg.read_text()
    assert '-transistor type - "finfet"' in cfg
    assert '-operating voltage 0.3' in cfg
    assert '-device file - "custom/device.xml"' in cfg
    assert '-sram cell file - "custom/cell.xml"' in cfg


@pytest.mark.parametrize('technology,transistor,voltage', [
    (14, 'finfet', 0.55), (7, 'finfet', 0.6), (14, 'cmos', 0.7), (22, 'cmos', 0.55),
])
def test_cacti_fn_run_rejects_invalid_voltage(technology, transistor, voltage):
    with pytest.raises(AssertionError, match='No voltage interpolation'):
        cacti_fn_run('sram', technology, {'transistor': transistor, 'voltage': voltage})


def test_cacti_fn_signature_changes_with_device_contents(tmp_path):
    module = importlib.import_module('archx.interface.cacti_fn.cacti_fn')
    device_file = tmp_path / 'device.xml'
    source_file = module.os.path.join(module.os.path.dirname(module.__file__), 'include/cacti_fn/xmls/devices/finfet_7nm_std.xml')
    shutil.copyfile(source_file, device_file)
    origin_cfg = tmp_path / 'origin.cfg'
    origin_cfg.write_text('-temperature 300\n')
    knobs = {'width': 64, 'depth': 1024, 'bank': 4, 'device_file': str(device_file)}

    before = cacti_fn_signature('sram', 7, knobs, str(origin_cfg))
    device_file.write_text(device_file.read_text() + '\n<!-- changed -->\n')
    after = cacti_fn_signature('sram', 7, knobs, str(origin_cfg))

    assert before != after


def test_cacti7_query_does_not_cache_invalid_report(monkeypatch, tmp_path):
    module = importlib.import_module('archx.interface.cacti7.cacti7')

    def fake_run(mem_type, technology, cfg_dict, origin_cfg_file, target_cfg_file, result_file):
        with open(result_file, 'w') as report:
            report.write('broken report\n')

    monkeypatch.setattr(module, 'cacti7_run', fake_run)

    with pytest.raises(AssertionError):
        module.query(
            name='t', interface='cacti7',
            query={'class': 'sram', 'technology': 45, 'frequency': 1000,
                   'width': 64, 'depth': 1024, 'bank': 4},
            output_dir=str(tmp_path),
        )

    assert not list(tmp_path.glob('*.flag'))


def test_cacti_fn_query_does_not_cache_invalid_report(monkeypatch, tmp_path):
    module = importlib.import_module('archx.interface.cacti_fn.cacti_fn')
    real_exists = module.os.path.exists
    monkeypatch.setattr(module.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(module.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(module.os.path, 'exists', lambda path: str(path).endswith('cacti-Linux-x86_64') or real_exists(path))
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: kwargs['stdout'].write('broken report\n'))

    with pytest.raises(AssertionError):
        query_cacti_fn(
            name='t', interface='cacti_fn',
            query={'class': 'sram', 'technology': 14, 'frequency': 1000,
                   'width': 64, 'depth': 1024, 'bank': 4},
            output_dir=str(tmp_path),
        )

    assert not list(tmp_path.glob('*.flag'))


def test_cacti_fn_parse_report_by_label(tmp_path):
    report = tmp_path / 'fake.rpt'
    report.write_text(
        'cache type                    : Scratch RAM\n'
        '    Number of banks: 4\n'
        '    Access time (ns): 0.5\n'
        '    Cycle time (ns):  0.25\n'
        '    Total dynamic read energy per access (nJ): 0.01\n'
        '    Total dynamic write energy per access (nJ): 0.02\n'
        '    Total leakage power of a bank (mW): 1.5\n'
        '    Cache height x width (mm): 0.2 x 0.5\n'
    )
    rd, wr, leak, area, freq = parse_report_sram_fn(str(report))
    assert (rd, wr, leak) == (0.01, 0.02, 6.0)
    assert abs(area - 0.1) < 1e-12
    assert freq == 4000.0


def test_query_interface_cacti7_sram():
    module = 'isram'
    query = {
        'class': 'sram',
        'interface': 'cacti7',
        'technology': 45,
        'frequency': 400,
        'width': 16,
        'depth': 512,
        'bank': 32
    }
    path = get_path('tests')
    path = path + '/test_interface/'
    create_dir(path)
    output = query_interface(module, query, output_dir=path)
    logger.info('test_query_interface_cacti7_sram: ', output)


def test_query_interface_cacti_fn_sram(monkeypatch, tmp_path):
    interface_module = importlib.import_module('archx.interface.interface')
    monkeypatch.setattr(interface_module, '_interface_output_cache', {})
    monkeypatch.setenv('ARCHX_INTERFACE_CACHE_DIR', str(tmp_path))
    module = 'isram_fn'
    query = {
        'class': 'sram',
        'interface': 'cacti_fn',
        'technology': 7,
        'frequency': 1000,
        'width': 64,
        'depth': 1024,
        'bank': 4,
    }
    path = get_path('tests')
    path = path + '/test_interface/'
    create_dir(path)
    output = query_interface(module, query, output_dir=path)

    assert output['area']['value'] > 0
    assert output['leakage_power']['value'] > 0
    assert output['dynamic_energy']['read']['value'] > 0
    assert output['technology'] == {'value': 7, 'unit': 'nm'}


def test_query_interface_cacti7_dram():
    module = 'ocdram'
    query = {
        'class': 'dram',
        'interface': 'cacti7',
        'technology': 45,
        'frequency': 400,
        'bandwidth': 25.6,
        'size': 1073741824 # 1GB in bytes
    }
    path = get_path('tests')
    path = path + '/test_interface/'
    create_dir(path)
    output = query_interface(module, query, output_dir=path)
    logger.info('test_query_interface_cacti7_dram: ', output)


def test_copy_interface():
    name = 'csv_cmos'
    path = 'tests/test_interface/dummy_csv_cmos'
    copy_interface(name, path)


def test_register_interface():
    name = 'dummy_csv_cmos'
    path = 'tests/test_interface/dummy_csv_cmos'
    register_interface(name, path)


def test_unregister_interface():
    name = 'dummy_csv_cmos'
    unregister_interface(name)


def test_cleanup():
    path = 'tests/test_interface/dummy_csv_cmos'
    shutil.rmtree(path)
    path = get_path('tests/test_interface/')
    shutil.rmtree(path)


if __name__ == "__main__":
    test_query_interface_csv_cmos()
    test_query_interface_cacti7_sram()
    test_query_interface_cacti7_dram()
    test_copy_interface()
    test_register_interface()
    test_unregister_interface()
    test_cleanup()
