from loguru import logger
from copy import deepcopy

# TODO:
#   - Finalize method signitures
#   - Finalize assertion messages
#   - Allow sweeping objects to be passed.
#   - Allow add_module to pass query as **kwargs

class Architecture():
    def __init__(self, parameter_enumerator):
        self.parameter_enumerator = parameter_enumerator

    def add_attributes(self, **kwargs):
        assert kwargs, "At least one attribute must be provided."

        param_dict = {}
        for key, value in kwargs.items():
            sweep = isinstance(value, list)
            attr_param = self.parameter_enumerator.add_parameter(name='attribute',
                                                                  param_name=key,
                                                                  value=value,
                                                                  type='attribute',
                                                                  sweep=sweep,
                                                                  desc='architecture')
            param_dict[key] = attr_param
            logger.info(f"Added attribute: {key}")
            logger.debug(f"\tValue: {value}")

        return param_dict

    def add_module(self, name, instance, tag, query):
        assert isinstance(name, str) or isinstance(name, list), "Module name must be a string or list of strings."
        assert isinstance(instance, list), "Module instance must be a list."
        assert isinstance(tag, list), "Module tag must be a list."
        assert isinstance(query, dict), "Module query must be a dictionary."

        if isinstance(name, list):
            param_list = {}
            for module_name in name:
                param_dict = self._module(module_name, instance, tag, query)
                param_list[module_name] = param_dict
            return param_list
        else:
            return self._module(name, instance, tag, query)

    def _module(self, name, instance, tag, query):
        assert isinstance(name, str), "Module name must be a string."

        # check if instance is a sweep (list of lists) or not
        inst_sweep = None
        for inst in instance:
            sweep_check = isinstance(inst, list)
            if inst_sweep is None:
                inst_sweep = sweep_check
            else:
                assert inst_sweep == sweep_check, "All instance entries must be of the same type (sweep or non-sweep)."
                
        inst_param = self.parameter_enumerator.add_parameter(name=name,
                                                              param_name='instance',
                                                              value=instance,
                                                              type='module',
                                                              sweep=inst_sweep,
                                                              desc='architecture')
        
        tag_sweep = None
        tag_param = self.parameter_enumerator.add_parameter(name=name,
                                                              param_name='tag',
                                                              value=tag,
                                                              type='module',
                                                              sweep=tag_sweep,
                                                              desc='architecture')


        logger.info(f"Added module: {name}")
        logger.debug(f"\tInstance: {instance}")
        logger.debug(f"\tTag: {tag}")
        
        query_param_dict = {}
        for key, value in query.items():
            sweep = isinstance(value, list)
            query_param = self.parameter_enumerator.add_parameter(name=name, 
                                                              param_name=key,
                                                              value=value,
                                                              type='module',
                                                              sweep=sweep,
                                                              desc='architecture')
            query_param_dict[key] = query_param
            logger.debug(f"\tQuery - {key}: {value}")
            
        param_dict = {
            'instance': inst_param,
            'tag': tag_param,
            'query': query_param_dict
        }

        return param_dict
    
    def to_yaml(self, config):
        architecture_dict = {'architecture': {'attribute': {}, 'module': {}}}
        
        for var_name, value in config.items():
            # Look up parameter info using the variable name string
            param_info = self.parameter_enumerator.get_parameters_from_name(var_name)
            type_ = param_info['type']
            name = param_info['name']
            param_name = param_info['param_name']
            copy_value = deepcopy(value)

            if type_ == 'attribute':
                architecture_dict['architecture']['attribute'][param_name] = copy_value
            elif type_ == 'module':
                if name not in architecture_dict['architecture']['module']:
                    architecture_dict['architecture']['module'][name] = {}
                
                if param_name in ['instance', 'tag']:
                    architecture_dict['architecture']['module'][name][param_name] = copy_value
                else:
                    # Query parameters
                    if 'query' not in architecture_dict['architecture']['module'][name]:
                        architecture_dict['architecture']['module'][name]['query'] = {}
                    architecture_dict['architecture']['module'][name]['query'][param_name] = copy_value
        
        return architecture_dict
        