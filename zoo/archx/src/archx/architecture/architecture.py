from collections import OrderedDict
from loguru import logger

from archx.utils import read_yaml, write_yaml, get_path, uniquify_list


key_module = 'module'
key_attribute = 'attribute'
key_path = 'path'
key_tag = 'tag'
key_instance = 'instance'
key_query = 'query'
key_architecture = 'architecture'


def create_architecture_dict(architecture_file: str, architecture_dict: OrderedDict=None, parent_module: str=None, parent_attribute_dict: OrderedDict=None) -> OrderedDict:
    """
    creates an architecture dictionary, whose keys are unique hardware modules.
    each module has its tag list, instance list, and query dict.
    """
    if architecture_dict is None:
        architecture_dict = OrderedDict()
    
    if parent_attribute_dict is None:
        parent_attribute_dict = OrderedDict()

    # read in architectural yaml
    architecture_file_full_path = get_path(architecture_file)
    loaded_dict = read_yaml(architecture_file_full_path)[key_architecture]

    if key_attribute in loaded_dict:
        attribute_dict = loaded_dict[key_attribute]
    else:
        # heritage parent attributes if nothing is speficied
        attribute_dict = parent_attribute_dict
        
    module_dict = loaded_dict[key_module]

    for module in module_dict:
        if key_path not in module_dict[module]:
            # propagate tag
            if parent_module is not None:
                if key_tag not in module_dict[module]:
                    module_dict[module][key_tag] = []
                module_dict[module][key_tag].append(parent_module)
            module_dict[module][key_tag].append(module)
            module_dict[module][key_tag] = uniquify_list(module_dict[module][key_tag])
            
            # propagate instance, default to 1
            if key_instance not in module_dict[module]:
                module_dict[module][key_instance] = [1]
            
            # propagate attribute
            for attr in attribute_dict:
                if attr not in module_dict[module][key_query]:
                    module_dict[module][key_query][attr] = attribute_dict[attr]

            # register module
            assert module not in architecture_dict, logger.error(f'Invalid repetition of module <{module}>.')
            architecture_dict[module] = module_dict[module]
        else:
            # load architecture from path
            new_architecture_file = get_path(module_dict[module][key_path])
            architecture_dict = create_architecture_dict(new_architecture_file, architecture_dict, module, attribute_dict)
    logger.success(f'Creat architecture dictionary from <{architecture_file_full_path}>.')
    return architecture_dict


def save_architecture_dict(architecture_dict: OrderedDict, save_path: str) -> None:
    """
    save architecture to a checkpoint
    """
    save_path = get_path(save_path, check_exist=False)
    architecture_dict_ckpt = OrderedDict({key_architecture: OrderedDict({key_module : architecture_dict})})
    write_yaml(save_path, architecture_dict_ckpt)
    logger.success(f'Save architecture dictionary to <{save_path}>.')


def load_architecture_dict(ckpt_path: str) -> OrderedDict:
    """
    load architecture from a checkpoint, and bypass attribute processing and path loading
    """
    full_path = get_path(ckpt_path)
    architecture_dict = read_yaml(full_path)[key_architecture][key_module]
    logger.success(f'Load architecture dictionary from <{full_path}>.')
    return architecture_dict

