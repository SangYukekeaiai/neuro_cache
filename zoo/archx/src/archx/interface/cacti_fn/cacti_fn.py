import subprocess, os, copy, platform, hashlib
import xml.etree.ElementTree as ET

from collections import OrderedDict

from loguru import logger


# FN-CACTI (https://github.com/marg-tools/FN-CACTI) is PCACTI patched for FinFET /
# NC-FinFET. It uses hardcoded 14 nm FinFET data and PCACTI XML device data for
# 7 nm FinFET and 14/22 nm CMOS. Scratch-RAM (sram) and cache are modeled.

device_configs = {
    (14, 'finfet'): (0.7, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8),
    (7, 'finfet'): (0.7, 0.45, 0.30),
    (14, 'cmos'): (0.80, 0.55),
    (22, 'cmos'): (0.80,),
}

default_xml_device_files = {
    (7, 'finfet'): 'xmls/devices/finfet_7nm_std.xml',
    (14, 'cmos'): 'xmls/devices/cmos_14nm_std.xml',
    (22, 'cmos'): 'xmls/devices/cmos_22nm_hp.xml',
}
scaled_7nm_device_file = 'xmls/devices/finfet_7nm_0p7.xml'


def cacti_fn_signature(
    mem_type: str,
    tech_node_nm: str,
    cfg_dict: OrderedDict,
    origin_cfg_file: str
):
    """
    Identify a run by everything that shapes its report: the memory type, the device
    node, the knobs written into the config, and the base config and XML file contents.
    """
    with open(origin_cfg_file, 'rb') as origin:
        origin_cfg = origin.read()
    knobs = sorted((str(key), str(value)) for key, value in cfg_dict.items())
    payload = repr((mem_type, str(tech_node_nm), knobs)).encode() + origin_cfg
    device_key = (int(tech_node_nm), cfg_dict.get('transistor', 'finfet'))
    if device_key != (14, 'finfet') or 'device_file' in cfg_dict:
        default_device = default_xml_device_files.get(device_key)
        if device_key == (7, 'finfet') and float(cfg_dict.get('voltage', device_configs[device_key][0])) == 0.7:
            default_device = scaled_7nm_device_file
        device_file = cfg_dict.get('device_file', default_device)
        if device_file is not None:
            default_cell = 'finfet_sram_6T1.xml' if device_key[1] == 'finfet' else 'cmos_sram_6T.xml'
            cell_file = cfg_dict.get('sram_cell_file', os.path.join('xmls/sram_cells', default_cell))
            run_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'include/cacti_fn')
            xml_files = [device_file, cell_file]
            if 'sram_cell_file' in cfg_dict:
                cell = ET.parse(os.path.join(run_dir, cell_file))
                xml_files.extend(node.text for node in cell.findall('./transistor_parameters/*/device_type'))
            for xml_file in dict.fromkeys(xml_files):
                with open(os.path.join(run_dir, xml_file), 'rb') as source:
                    payload += repr((xml_file, source.read())).encode()
    return hashlib.sha256(payload).hexdigest()[:12]


def cacti_fn_run(
    mem_type: str,
    tech_node_nm: str,
    cfg_dict: OrderedDict,
    origin_cfg_file=None,
    target_cfg_file=None,
    result_file=None
):
    """
    Write an SRAM or cache config and run FN-CACTI. SRAM uses width (bits), depth,
    and bank. Cache uses size (bits), width (line bits), associativity, and bank.
    Cache access_mode is normal (default), sequential, or fast, with one read-write
    port. SRAM uses normal access, one read port, and one write port.
    Both accept
    wire_technology (nm, defaults to the device node), transistor (default finfet),
    voltage (V), device_file, and sram_cell_file (paths relative to include/cacti_fn).
    Supported devices: 14 nm FinFET at 0.2 to 0.8 V in 0.1 steps (default 0.7),
    7 nm FinFET at 0.7 V (default, first-order scaled) or 0.45/0.30 V,
    14 nm CMOS at 0.80/0.55 V, and 22 nm CMOS at
    0.80 V. XML paths default to the first listed voltage; no voltage interpolation.
    """
    assert mem_type in ['sram', 'cache'], logger.error(f'Invalid <{mem_type}> in cacti_fn; valid values: [sram, cache]')
    tech_node_nm = int(tech_node_nm)
    transistor = cfg_dict.get('transistor', 'finfet')
    supported = '14 nm finfet: 0.2 to 0.8 V in 0.1 steps; 7 nm finfet: 0.7 V (default, first-order scaled) or 0.45/0.30 V; 14 nm cmos: 0.80/0.55 V; 22 nm cmos: 0.80 V'
    device_key = (tech_node_nm, transistor)
    message = f'Unsupported device <{tech_node_nm} nm {transistor}> in cacti_fn; supported: {supported}.'
    if device_key not in device_configs:
        logger.error(message)
        raise AssertionError(message)
    voltages = device_configs[device_key]

    tech_node_um = tech_node_nm / 1000
    wire_node_um = int(cfg_dict.get('wire_technology', tech_node_nm)) / 1000
    voltage = float(cfg_dict.get('voltage', voltages[0]))
    message = f'Invalid voltage <{voltage}> for <{tech_node_nm} nm {transistor}> in cacti_fn; supported: {supported}. No voltage interpolation.'
    if voltage not in voltages:
        logger.error(message)
        raise AssertionError(message)

    bank_count = int(cfg_dict['bank'])
    block_bits = int(cfg_dict['width'])
    # shortcut: CACTI models whole bytes, so odd widths are over-provisioned to the next byte
    block_bytes = -(-block_bits // 8)
    if block_bytes * 8 != block_bits:
        logger.warning(f'width <{block_bits}> rounded up to {block_bytes * 8} bits ({block_bytes} bytes) for cacti_fn')
    block_bits = block_bytes * 8
    if mem_type == 'cache':
        associativity = int(cfg_dict['associativity'])
        assert associativity == cfg_dict['associativity'] and associativity >= 1 and associativity & (associativity - 1) == 0, logger.error('cache associativity must be an integer power of two >= 1')
        size_bits = int(cfg_dict['size'])
        assert size_bits % 8 == 0, logger.error('cache size must be a multiple of 8 bits')
        total_bytes = size_bits // 8
        assert total_bytes % (block_bytes * associativity * bank_count) == 0, logger.error('cache size in bytes must be divisible by line bytes * associativity * bank')
        access_mode = cfg_dict.get('access_mode', 'normal')
        assert access_mode in ['normal', 'sequential', 'fast'], logger.error('cache access_mode must be normal, sequential, or fast')
    else:
        associativity = 1
        total_bytes = bank_count * int(cfg_dict['depth']) * block_bytes
        access_mode = 'normal'

    with open(origin_cfg_file, 'r') as original, open(target_cfg_file, 'w') as target:
        target.write('-transistor type - "' + transistor + '"\n')
        target.write('-technology node ' + str(tech_node_um) + '\n')
        target.write('-wire technology node ' + str(wire_node_um) + '\n')
        target.write('-operating voltage ' + str(voltage) + '\n')
        if 'device_file' in cfg_dict:
            target.write('-device file - "' + cfg_dict['device_file'] + '"\n')
        elif device_key == (7, 'finfet') and voltage == 0.7:
            target.write('-device file - "' + scaled_7nm_device_file + '"\n')
        if 'sram_cell_file' in cfg_dict:
            target.write('-sram cell file - "' + cfg_dict['sram_cell_file'] + '"\n')
        target.write('-size ' + str(total_bytes) + '\n')
        target.write('-block size ' + str(block_bytes) + '\n')
        target.write('-bus width ' + str(block_bits) + '\n')
        target.write('-uca bank ' + str(bank_count) + '\n')
        target.write('-memory type "' + ('cache' if mem_type == 'cache' else 'ram') + '"\n')
        target.write('-associativity ' + str(associativity) + '\n')
        target.write('-tag size "default"\n')
        target.write('-read-write port ' + ('1' if mem_type == 'cache' else '0') + '\n')
        target.write('-exclusive read port ' + ('0' if mem_type == 'cache' else '1') + '\n')
        target.write('-exclusive write port ' + ('0' if mem_type == 'cache' else '1') + '\n')
        target.write('-access mode - "' + access_mode + '"\n')
        for entry in original:
            target.write(entry)

    run_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'include/cacti_fn')

    # Binaries are stored per host as 'cacti-<system>-<machine>'; build from source
    # via 'make' when the host's binary is absent (same scheme as cacti7).
    cacti_bin = 'cacti-' + platform.system() + '-' + platform.machine()
    bin_path = os.path.join(run_dir, cacti_bin)
    if not os.path.exists(bin_path):
        logger.info('No FN-CACTI binary for <' + cacti_bin + '>; building from source via make.')
        subprocess.run(['make', 'all'], cwd=run_dir, check=True)
        if not os.path.exists(bin_path):
            os.replace(os.path.join(run_dir, 'cacti'), bin_path)

    with open(result_file, 'w') as report:
        subprocess.run(
            ['./' + cacti_bin, '-infile', target_cfg_file],
            cwd=run_dir,
            stdout=report,
            check=True,
        )


# FN-CACTI reorders the CACTI report, so fields are located by label, not line number.
report_labels = OrderedDict([
    ('bank', 'Number of banks:'),
    ('cycle_time_ns', 'Cycle time (ns):'),
    ('energy_rd_nJ', 'Total dynamic read energy per access (nJ):'),
    ('energy_wr_nJ', 'Total dynamic write energy per access (nJ):'),
    ('leakage_bank_mW', 'Total leakage power of a bank'),
    ('height_x_width_mm', 'Cache height x width (mm):'),
])


def parse_report_sram(
    report=None
):
    """
    Return (energy_per_rd_nJ, energy_per_wr_nJ, leakage_power_mW, total_area_mm2, max_freq_MHz)
    from the first occurrence of each labeled field in the DETAILED FN-CACTI report.
    """
    fields = {}
    with open(report, 'r') as cacti_out:
        for entry in cacti_out:
            for key, label in report_labels.items():
                if key not in fields and label in entry:
                    fields[key] = entry.split(':', 1)[-1].strip()
    missing = [label for key, label in report_labels.items() if key not in fields]
    assert not missing, logger.error(f'Check {report} for sram FN-CACTI failure; missing {missing}.')

    bank = float(fields['bank'])
    cycle_time = float(fields['cycle_time_ns'])
    height, width = (float(side) for side in fields['height_x_width_mm'].split('x'))

    energy_per_rd_nJ = float(fields['energy_rd_nJ'])
    energy_per_wr_nJ = float(fields['energy_wr_nJ'])
    leakage_power_mW = float(fields['leakage_bank_mW']) * bank
    total_area_mm2 = height * width
    max_freq = 1 / cycle_time * 1000
    return energy_per_rd_nJ, energy_per_wr_nJ, leakage_power_mW, total_area_mm2, max_freq


def query(name: str, interface: str, query: OrderedDict, input_dir=None, output_dir=None):
    query = copy.deepcopy(query)
    query_class = query['class'].lower()
    query_technology = query['technology']
    query_frequency = query['frequency']
    del query['class']
    del query['technology']
    del query['frequency']

    assert os.path.isdir(output_dir), logger.error(f'Invalid output dir <{output_dir}>.')
    assert query_class in ['sram', 'cache'], logger.error(f'Invalid <{query_class}> in cacti_fn; valid values: [sram, cache]')

    origin_cfg_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sram.cfg')
    assert os.path.isfile(origin_cfg_file), logger.error(f'Invalid FN-CACTI config file <{origin_cfg_file}>.')

    if query_class == 'cache':
        post_fix = '.cache' + '.size' + str(query['size']) + '.width' + str(query['width']) + '.assoc' + str(query['associativity']) + '.bank' + str(query['bank'])
    else:
        post_fix = '.sram' + '.width' + str(query['width']) + '.depth' + str(query['depth']) + '.bank' + str(query['bank'])
    post_fix = post_fix + '.tech' + str(query_technology) + '.' + cacti_fn_signature(query_class, query_technology, query, origin_cfg_file)

    target_cfg_file = os.path.join(output_dir, name + post_fix + '.cacti_fn.cfg')
    cacti_report = os.path.join(output_dir, name + post_fix + '.cacti_fn.rpt')

    target_cfg_file_flag = target_cfg_file + '.flag'
    run_needed = not os.path.exists(target_cfg_file_flag)
    if run_needed:
        cacti_fn_run(query_class, query_technology, query, origin_cfg_file, target_cfg_file, cacti_report)

    energy_per_rd_nJ, energy_per_wr_nJ, leakage_power_mW, total_area_mm2, _ = parse_report_sram(cacti_report)
    if run_needed:
        with open(target_cfg_file_flag, 'a') as f:
            f.write(target_cfg_file_flag)

    output_dict = OrderedDict()
    output_dict['technology'] = OrderedDict({'value': query_technology, 'unit': 'nm'})
    output_dict['frequency'] = OrderedDict({'value': query_frequency, 'unit': 'MHz'})
    output_dict['dynamic_energy'] = OrderedDict({'read': OrderedDict({'value': energy_per_rd_nJ, 'unit': 'nJ'}),
                                                 'write': OrderedDict({'value': energy_per_wr_nJ, 'unit': 'nJ'})})
    output_dict['leakage_power'] = OrderedDict({'value': leakage_power_mW, 'unit': 'mW'})
    output_dict['area'] = OrderedDict({'value': total_area_mm2, 'unit': 'mm^2'})

    return output_dict
