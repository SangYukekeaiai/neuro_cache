"""Assemble Figure 1 prices from its saved Genus and FN-CACTI banks."""
import hashlib
import json
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MODEL = ROOT.parents[1]/'zoo/archx/zoo/snn_edp'


def load(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


def memory_row(bank, operation):
    metrics = bank['metrics']
    return {'dynamic_energy_nJ': metrics['dynamic_energy'][operation]['value'],
            'leakage_power_mW': metrics['leakage_power']['value'],
            'area_mm2': metrics['area']['value'], 'query': bank['query'],
            'source_report': bank['source_report'],
            'source_report_sha256': bank['source_report_sha256'],
            'assumption': bank['assumption'], 'frequency_MHz': 500}


def build():
    source_paths = {'logic': HERE/'asap7_genus/logic_prices.json',
                    'memory': HERE/'memory/memory_prices.json',
                    'architectures': ROOT/'configs/arch_manifest.json',
                    'hardware': MODEL/'hardware.json', 'dram': MODEL/'energy_table.json'}
    before = {k: digest(p) for k,p in source_paths.items()}
    logic, memory = load(source_paths['logic']), load(source_paths['memory'])
    hardware, dram = load(source_paths['hardware']), load(source_paths['dram'])
    variants = {}
    for name, config in load(source_paths['architectures'])['variants'].items():
        arch = name.split('/')[0]
        configuration = yaml.safe_load((ROOT/config['path']).read_text())['arch']
        node = configuration['storage'][0]
        width = node['pe']['num_pes']*configuration['bitwidths']['BW_WEIGHT']
        capacity = node['local_buffer']['entries']['weight']
        weight = memory['queries'][f'weight_{capacity}_w{width}']
        rows = {}
        for key, spec in hardware.items():
            if not key.startswith(arch+'.') or key == 'gustavsnn.merger_tree2.merge':
                continue
            operation = key.split('.')[-1]
            if key in logic['operations']:
                rows[key] = {**logic['operations'][key], 'source': 'local_genus_primitive_composition',
                             'frequency_MHz': 500}
            else:
                bank = weight if '.l1_weight_spad.' in key else memory['queries']['ptb_spike_buffer']
                if '.l1_weight_spad.' not in key and not key.startswith(('ptb.spike_vector_buffer.', 'ptb.output_spike_queue.')):
                    raise ValueError('unmapped physical price: '+key)
                rows[key] = memory_row(bank, operation)
        # Prices for the fixed buffers are independent of their access contract.
        for buffer in ('psum', 'vmem'):
            for operation in ('read', 'write'):
                rows[f'{arch}.{buffer}_sram.{operation}'] = memory_row(memory['queries'][buffer+'_fixed'], operation)
        for key in ('shared.ddr4.read', 'shared.ddr4_io.byte'):
            rows[key] = dram[key]
        for key, row in rows.items():
            for metric in ('dynamic_energy_nJ','leakage_power_mW','area_mm2'):
                if row[metric] is None or row[metric] < 0:
                    raise ValueError('invalid price: '+key+'.'+metric)
        variants[name] = {'arch_config_sha256': config['sha256'], 'operations': rows}
    if before != {k: digest(p) for k,p in source_paths.items()}:
        raise ValueError('source bank changed during table assembly')
    return {'schema': 'fig1_price_bank_v1', 'frequency_MHz': 500,
            'characterization_source': logic['caveat'], 'memory_assumption': memory['assumption'],
            'variants': variants}, before, source_paths


def main():
    table, hashes, sources = build()
    output = HERE/'energy_table_asap7_syn.json'
    save(output, table)
    save(HERE/'table_manifest.json', {'table': str(output.relative_to(ROOT)),
        'table_sha256': digest(output), 'builder_sha256': digest(Path(__file__)),
        'sources': {k: {'path': str(p), 'sha256': hashes[k]} for k,p in sources.items()},
        'variants': len(table['variants']),
        'pricing_boundary': 'Prices only. Physical inventory and local state-access contracts belong to the count model.',
        'characterization_source': table['characterization_source']})
    print(json.dumps({'table': str(output), 'sha256': digest(output), 'variants': len(table['variants'])}))


if __name__ == '__main__':
    main()
