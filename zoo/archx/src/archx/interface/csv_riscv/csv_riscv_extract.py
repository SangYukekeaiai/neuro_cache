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

        module_path = os.path.join(rpt_dir, module)
        if not os.path.isdir(module_path):
            continue

        # Find all subdirectories in module_path
        subdirs = [d for d in os.listdir(module_path) if os.path.isdir(os.path.join(module_path, d))]

        # Special case: if only one subdir and its name matches the module, check for another level
        if len(subdirs) == 1 and subdirs[0] == module:
            deeper_path = os.path.join(module_path, module)
            deeper_subdirs = [d for d in os.listdir(deeper_path) if os.path.isdir(os.path.join(deeper_path, d))]
            # If there are no deeper subdirs, treat as old style, else use deeper_path
            if not deeper_subdirs:
                subdirs = [module]
                module_path = deeper_path
            else:
                # Should not happen with your current structure, but fallback
                subdirs = deeper_subdirs
                module_path = deeper_path

        # If no subdirs, fallback to old behavior
        if not subdirs:
            subdirs = ['']

        # Prepare CSV
        module_csv = os.path.join(csv_dir, module + '.csv')
        param_dict = read_yaml(f'{current_dir}/param.yaml')
        header_ = []
        default_ = []
        if module in param_dict.keys() and param_dict[module] is not None:
            for item_ in param_dict[module].items():
                header_.append(item_[0].lower())
                default_.append(item_[1])

        # Add instruction column if multiple subdirs with different names
        add_instruction_col = len(subdirs) > 1 or (subdirs[0] != '' and subdirs[0] != module)
        with open(module_csv, 'w') as f:
            csvwriter = csv.writer(f)
            header = ['technology', 'frequency', 'dynamic_uw', 'leakage_uw', 'area_mm2', 'num_instances', 'interpolation']
            if add_instruction_col:
                header.append('instruction')
            header += header_
            csvwriter.writerow(header)

            # If multiple subdirs, collect all leakage and area for averaging
            avg_leakage = None
            avg_area = None
            if add_instruction_col and len(subdirs) > 0:
                leakage_list = []
                area_list = []
                # First pass: collect all leakage and area
                for subdir in subdirs:
                    if subdir == '' or subdir == module:
                        rpt_path = os.path.join(module_path, module, f'{module}_DETAILS.rpt')
                        if not os.path.exists(rpt_path):
                            rpt_path = os.path.join(module_path, f'{module}_DETAILS.rpt')
                    else:
                        rpt_path = os.path.join(module_path, subdir, f'{subdir}_DETAILS.rpt')
                    if not os.path.exists(rpt_path):
                        continue
                    with open(rpt_path, 'r') as file:
                        for entry in file:
                            elems = entry.strip().split(',')
                            elems = strip_list(elems)
                            if len(elems) > 0:
                                if str(elems[0]) == 'postRouteOpt':
                                    area = float(elems[4]) / 10**6 # mm^2
                                    leakage = float(elems[6]) # uW
                                    area_list.append(area)
                                    leakage_list.append(leakage)
                if leakage_list:
                    avg_leakage = sum(leakage_list) / len(leakage_list)
                if area_list:
                    avg_area = sum(area_list) / len(area_list)

            for subdir in subdirs:
                # Determine rpt path
                if subdir == '' or subdir == module:
                    rpt_path = os.path.join(module_path, module, f'{module}_DETAILS.rpt')
                    if not os.path.exists(rpt_path):
                        rpt_path = os.path.join(module_path, f'{module}_DETAILS.rpt')
                else:
                    rpt_path = os.path.join(module_path, subdir, f'{subdir}_DETAILS.rpt')
                if not os.path.exists(rpt_path):
                    logger.warning(f'RPT file not found: {rpt_path}')
                    continue

                # read from rpt_path
                area = leakage = dynamic = None
                with open(rpt_path, 'r') as file:
                    for entry in file:
                        elems = entry.strip().split(',')
                        elems = strip_list(elems)
                        if len(elems) > 0:
                            if str(elems[0]) == 'postRouteOpt':
                                area = float(elems[4]) / 10**6 # mm^2
                                leakage = float(elems[6]) # uW
                                dynamic = float(elems[7]) # uW

                assert dynamic not in (None, 0), logger.error(f'dynamic power={dynamic} for {module} is 0')
                # Use average leakage and area if multiple lines
                if add_instruction_col and avg_leakage is not None and avg_area is not None:
                    leakage = avg_leakage
                    area = avg_area
                assert leakage not in (None, 0), logger.error(f'leakage power={leakage} for {module} is 0')
                assert area not in (None, 0), logger.error(f'area={area} for {module} is 0')

                content = [tech_map[technology], frequency, dynamic, leakage, area, 1, interpolation]
                if add_instruction_col:
                    content.append(subdir if subdir != '' else module)
                content += default_
                csvwriter.writerow(content)
    

if __name__ == '__main__':
    technology = 'NanGate45'
    frequency = 400
    extract(technology, frequency)

