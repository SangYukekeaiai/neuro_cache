import csv, os, copy

from collections import OrderedDict

from archx.utils import get_path


skip_list = ['technology', 'frequency', 'interpolation', 'dynamic_uw', 'leakage_uw', 'area_mm2']
interpolation_list = ['linear', 'quadratic']


def query(name: str, interface: str, query: OrderedDict, input_dir=None, output_dir=None):
    query = copy.deepcopy(query)
    query_class = query['class'].lower()
    del query['class']

    csv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'include/csv')
    csv_file = get_path(os.path.join(csv_dir, query_class + '.csv'))

    with open(csv_file) as csv_file:
        reader = csv.DictReader(csv_file)
        technology_flag = False
        for row in reader:
            n_kernels = query['n_kernels'] if 'n_kernels' in query else float(row['n_kernels'])

            power_w = float(row['power_w']) # in W
            runtime_us = float(row['runtime_us']) # in us
            total_energy_uj = power_w * runtime_us * n_kernels # in uJ
            total_runtime = runtime_us * n_kernels # in us

    output_dict = OrderedDict()
    output_dict['power'] = OrderedDict({'value': power_w, 'unit': 'W'})
    output_dict['energy'] = OrderedDict({'value': total_energy_uj, 'unit': 'uJ'})
    output_dict['runtime'] = OrderedDict({'value': total_runtime, 'unit': 'us'})
    return output_dict