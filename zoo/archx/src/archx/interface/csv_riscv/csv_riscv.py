import csv, os, copy

from collections import OrderedDict
from loguru import logger

from archx.utils import get_path, interpolate_oneD_linear, interpolate_oneD_quadratic


skip_list = ['technology', 'frequency', 'interpolation', 'dynamic_uw', 'leakage_uw', 'area_mm2']
interpolation_list = ['linear', 'quadratic']


def query(name: str, interface: str, query: OrderedDict, input_dir=None, output_dir=None):
    query = copy.deepcopy(query)
    query_class = query['class'].lower()
    query_technology = query['technology']
    query_frequency = query['frequency']
    del query['class']
    del query['technology']
    del query['frequency']

    csv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'include/csv')
    csv_file = get_path(os.path.join(csv_dir, query_class + '.csv'))

    with open(csv_file) as csv_file_obj:
        reader = list(csv.DictReader(csv_file_obj))
        # Check if there are multiple instruction types (column 'instruction')
        has_instruction = 'instruction' in reader[0]
        instructions = set(row['instruction'] for row in reader) if has_instruction else set()

        # If multiple instructions, only dynamic_energy is per-instruction; leakage_power and area use the first matching row
        if has_instruction and len(instructions) > 1:
            output_dict = OrderedDict()
            output_dict['technology'] = OrderedDict({'value': query_technology, 'unit': 'nm'})
            output_dict['frequency'] = OrderedDict({'value': query_frequency, 'unit': 'MHz'})
            dyn_energy_dict = OrderedDict()
            leakage_power_mW = None
            area_mm2 = None
            first_found = False
            for row in reader:
                if row['technology'] == str(query_technology):
                    instr = row['instruction']
                    dynamic_power_mW = float(row['dynamic_uw'])
                    # frequency scaling
                    dynamic_power_mW *= (query_frequency / float(row['frequency']))
                    dyn_energy_dict[instr] = OrderedDict({'value': dynamic_power_mW / query_frequency, 'unit': 'nJ'})
                    if not first_found:
                        leakage_power_mW = float(row['leakage_uw'])
                        area_mm2 = float(row['area_mm2'])
                        first_found = True
            output_dict['dynamic_energy'] = dyn_energy_dict
            output_dict['leakage_power'] = OrderedDict({'value': leakage_power_mW, 'unit': 'mW'})
            output_dict['area'] = OrderedDict({'value': area_mm2, 'unit': 'mm^2'})
            return output_dict
        else:
            technology_flag = False
            for row in reader:
                interpolation = row['interpolation'].lower()
                if row['technology'] == str(query_technology):
                    technology_flag = True
                    dynamic_power_mW = float(row['dynamic_uw']) # in mW
                    leakage_power_mW = float(row['leakage_uw']) # in mW
                    area_mm2 = float(row['area_mm2']) # in mm^2
                    dynamic_power_mW *= (query_frequency / float(row['frequency'])) # in mW
                    for attr_key in query:
                        assert attr_key in row, logger.error(f'Invalid query attribute <{attr_key}>.')
                    for attr_key in row:
                        if attr_key not in skip_list:
                            if attr_key not in query:
                                query[attr_key] = 1
                            if interpolation == 'linear':
                                dynamic_power_mW   = interpolate_oneD_linear(    query[attr_key], [{'x': 0, 'y': 0}, {'x': float(row[attr_key]), 'y': dynamic_power_mW}])
                                leakage_power_mW   = interpolate_oneD_linear(    query[attr_key], [{'x': 0, 'y': 0}, {'x': float(row[attr_key]), 'y': leakage_power_mW}])
                                area_mm2           = interpolate_oneD_linear(    query[attr_key], [{'x': 0, 'y': 0}, {'x': float(row[attr_key]), 'y': area_mm2}])
                            elif interpolation == 'quadratic':
                                dynamic_power_mW   = interpolate_oneD_quadratic( query[attr_key], [{'x': 0, 'y': 0}, {'x': float(row[attr_key]), 'y': dynamic_power_mW}])
                                leakage_power_mW   = interpolate_oneD_quadratic( query[attr_key], [{'x': 0, 'y': 0}, {'x': float(row[attr_key]), 'y': leakage_power_mW}])
                                area_mm2           = interpolate_oneD_quadratic( query[attr_key], [{'x': 0, 'y': 0}, {'x': float(row[attr_key]), 'y': area_mm2}])
                            else:
                                assert interpolation in interpolation_list, logger.error(f'Invalid interpolation <{interpolation}> in <{csv_file}>. Valid options are <{str(interpolation_list)}>.')
            assert technology_flag is True, logger.error(f'Invalid technology: <{query_technology}> for <{name}>.')
            energy_per_event_nJ = dynamic_power_mW / query_frequency
            output_dict = OrderedDict()
            output_dict['technology'] = OrderedDict({'value': query_technology, 'unit': 'nm'})
            output_dict['frequency'] = OrderedDict({'value': query_frequency, 'unit': 'MHz'})
            output_dict['dynamic_energy'] = OrderedDict({'value': energy_per_event_nJ, 'unit': 'nJ'})
            output_dict['leakage_power'] = OrderedDict({'value': leakage_power_mW, 'unit': 'mW'})
            output_dict['area'] = OrderedDict({'value': area_mm2, 'unit': 'mm^2'})
            return output_dict

