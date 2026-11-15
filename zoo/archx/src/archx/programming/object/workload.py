from loguru import logger
from copy import deepcopy

class Workload():
    def __init__(self, parameter_enumerator):
        self.parameter_enumerator = parameter_enumerator
        self.configurations = []

    def add_configuration(self, name):
        assert isinstance(name, (str, list)), "'name' parameter must be of type 'str' or a list of 'str'."

        if isinstance(name, list):
            config_dict = {}
            for config_name in name:
                config_dict[config_name] = self._configuration(config_name)
            return config_dict
        else:
            return self._configuration(name)

    def _configuration(self, name: str):
        assert isinstance(name, str), "'name' parameter must be of type 'str'."
        assert all(config.name != name for config in self.configurations), f"Configuration '{name}' already exists in workload."

        configuration = Configuration(name, self.parameter_enumerator)
        self.configurations.append(configuration)
        logger.info(f"Added configuration '{name}'.")
        return configuration
    
    def to_yaml(self, config):
        workload_dict = {'workload': {
            'name': None,
            'configuration': {}
        }}

        for var_name, value in config.items():
            param_info = self.parameter_enumerator.get_parameters_from_name(var_name)
            config_name = param_info['name']
            param_name = param_info['param_name']
            copy_value = deepcopy(value)
            
            if workload_dict['workload']['name'] is None:
                workload_dict['workload']['name'] = config_name
            workload_dict['workload']['configuration'][param_name] = copy_value
        
        return workload_dict

    def add_parameters(self, configs: list, parameter_name: str, parameter_value, sweep: bool = None):
        assert isinstance(configs, list), "'configs' parameter must be of type 'list'."
        assert all(isinstance(name, Configuration) for name in configs), "'configs' parameter must be a list of 'Configuration' objects."

        param_dict = {}

        for name in configs:
            param_dict[name] = name.add_parameter(parameter_name=parameter_name, parameter_value=parameter_value, sweep=sweep)

        # a shared parameter is one logical parameter declared for several configurations:
        # record the siblings so constraints written against one configuration's copy are
        # applied to each configuration's own solve (workloads never sweep across configs)
        group = {config.name: param['parameter'] for config, param in param_dict.items()}
        for parameter in group.values():
            self.parameter_enumerator.shared_parameters[parameter] = group

        return param_dict

class Configuration():
    def __init__(self, name: str, parameter_enumerator):
        self.name = name
        self.parameter_enumerator = parameter_enumerator

    def add_parameter(self, parameter_name: str, parameter_value, sweep: bool = None):
        assert isinstance(parameter_name, str), "'parameter_name' parameter must be of type 'str'."
        assert isinstance(sweep, (bool, type(None))), "'sweep' parameter must be of type 'bool'."
        assert (isinstance(parameter_value, list) and isinstance(sweep, bool)) or (not isinstance(parameter_value, list)) , "If 'parameter_value' is a list, 'sweep' must be defined as either True or False."

        sweep = sweep if sweep is not None else False

        parameter_param = self.parameter_enumerator.add_parameter(name=self.name,
                                                                  param_name=parameter_name,
                                                                  value=parameter_value,
                                                                  type='parameter',
                                                                  sweep=sweep,
                                                                  desc='workload')

        param_dict = {
            'parameter': parameter_param
        }

        logger.info(f"Added parameter '{parameter_name}' to configuration '{self.name}'.")
        logger.debug(f"\tValue: {parameter_value}")
        logger.debug(f"\tSweep: {sweep}")

        return param_dict