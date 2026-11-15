import os, csv

from loguru import logger

from archx.utils import strip_list, read_yaml, create_dir


linear_interpolation_keywords = ['acc', 'add', 'sub', 'reg', 'rng', 'shifter']
quadratic_interpolation_keywords = ['multiplier']


tech_map = {
    'NanGate45': '45',
    'ASAP7': '7',
    'TNN7': '7',
    }


def extract(technology, frequency):
    """
    technology node name
    frequency in MHz
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    rpt_dir = f'{current_dir}/syn_pnr_rpt/{technology}'
    csv_dir = f'{current_dir}/syn_pnr_csv/'
    create_dir(csv_dir)

    for module in os.listdir(rpt_dir):
        interpolation = 'linear'
        for keyword in linear_interpolation_keywords:
            if keyword in module:
                interpolation = 'linear'
        for keyword in quadratic_interpolation_keywords:
            if keyword in module:
                interpolation = 'quadratic'
        
        module_rpt = f'{rpt_dir}/{module}/{module}_DETAILS.rpt'

        # read from module_rpt
        with open(module_rpt, 'r') as file:
            for entry in file:
                elems = entry.strip().split(',')
                elems = strip_list(elems)
                if len(elems) > 0:
                    if str(elems[0]) == 'postRouteOpt':
                        area = float(elems[4]) / 10**6 # mm^2
                        leakage = float(elems[6]) # uW
                        dynamic = float(elems[7]) # uW

        assert dynamic != 0, logger.error(f'dynamic power={dynamic} for {module} is 0')
        assert leakage != 0, logger.error(f'leakage power={leakage} for {module} is 0')
        assert area != 0, logger.error(f'area={area} for {module} is 0')

        # parsing parameter dict
        header_ = []
        default_ = []
        param_dict = read_yaml(f'{current_dir}/param.yaml')
        if module in param_dict.keys() and param_dict[module] != None:
            for item_ in param_dict[module].items():
                header_.append(item_[0].lower())
                default_.append(item_[1])

        # generate csv table with parameters
        module_csv = csv_dir + module + '.csv'
        with open(module_csv, 'w') as f:
            csvwriter = csv.writer(f)
            header = ['technology', 'frequency', 'dynamic_uw', 'leakage_uw', 'area_mm2', 'num_instances', 'interpolation'] + header_
            csvwriter.writerow(header)
            content = [tech_map[technology], frequency, dynamic, leakage, area, 1, interpolation] + default_
            csvwriter.writerow(content)
    

if __name__ == '__main__':
    technology = 'TNN7'
    frequency = 100
    extract(technology, frequency)

