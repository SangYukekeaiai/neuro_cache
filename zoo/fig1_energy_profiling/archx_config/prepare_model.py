"""Instantiate the approved one-node hardware inventory without prices."""
from model import *
import yaml


def main():
    source = load(BACKEND/'zoo/snn_edp/hardware.json')
    segments = load(ROOT/'configs/segment_map.json')['local_operations']
    manifest = load(ROOT/'configs/arch_manifest.json')
    variants = {}; inventory = {}
    for variant, entry in manifest['variants'].items():
        arch, size = variant.split('/')
        cfg = yaml.safe_load((ROOT/entry['path']).read_text())['arch']
        node = cfg['storage'][0]; pes = node['pe']['num_pes']; width = pes*cfg['bitwidths']['BW_WEIGHT']
        rows = {}
        for key, spec in source.items():
            if not key.startswith(arch+'.') or key == 'gustavsnn.merger_tree2.merge': continue
            module = key.split('.')[1]
            count = spec['physical_instances']
            if arch == 'loas':
                if module in ('adder16','reg16','and_gate'): count = pes*32
                elif module in ('bsf32','lif_unit','spike_prefix_scan32'): count = pes
            elif arch == 'ptb':
                if module == 'adder16': count = pes*8
                elif module == 'reg16': count = pes*32
                elif module == 'lif_unit': count = pes
            else:
                if module in ('adder16','reg16','lif_core','potential_regfile'): count = pes
                elif module == 'leading_spike_detector': count = 1
            expression = spec['count_expression']; query = dict(spec['query'])
            if module == 'l1_weight_spad':
                query.update(width=width, depth=node['local_buffer']['entries']['weight']*8//width)
                if key.endswith('.write'): expression = f'l1_delivery_bytes*8/{width}'
            rows[key] = {'instances':count, 'expression':expression, 'segment':segments[key],
                         'inventory_segment':segments[key], 'query':query}
        for buffer, bits in (('psum',16), ('vmem',32)):
            capacity = manifest['state_buffers']['fixed_capacity_bytes'][buffer]
            for operation in ('read','write'):
                rows[f'{arch}.{buffer}_sram.{operation}'] = {
                    'instances':1,'expression':'0','segment':'on_chip_sram','inventory_segment':'on_chip_sram',
                    'query':{'class':'sram','technology':7,'frequency':500,'bank':1,'width':bits,'depth':capacity*8//bits},
                    'contract':'capacity/feasibility provision only; state dynamic activity remains in native register/LIF/RF operations'}
        for key, expression, instances in (('shared.ddr4.read','dram_accesses',1), ('shared.ddr4_io.byte','dram_bytes',0)):
            rows[key] = {'instances':instances, 'expression':expression, 'segment':'off_chip_weights',
                         'inventory_segment':'off_chip_other','query':{'class':key.split('.')[1]},
                         'contract':'all emitted DRAM payload is weight; standing DRAM/IO inventory belongs to off-chip other'}
        variants[variant] = rows
        inventory[variant] = {k.rsplit('.',1)[0]: {'instances':s['instances'], 'segment':s['inventory_segment'], 'query':s['query']}
                              for k,s in rows.items()}
    save(ROOT/'archx_config/hardware.json', {'variants':variants,
        'source_hardware_sha256':digest(BACKEND/'zoo/snn_edp/hardware.json'),
        'state_contract':'zero added dynamic state-SRAM accesses; fixed provisions contribute area/leakage once',
        'gustavsnn_contract':'one HO stream, eight COUT lanes, one detector, no two-stream merger'})
    manifest['energy_inventory'] = inventory
    manifest['state_buffers']['dynamic_access_contract'] = 'No added SRAM boundary; register/LIF/RF activity retained. Fixed SRAM provisions charge area/leakage once.'
    save(ROOT/'configs/arch_manifest.json', manifest)
    print('12 hardware configurations; state dynamic access expressions all zero')


if __name__ == '__main__': main()
