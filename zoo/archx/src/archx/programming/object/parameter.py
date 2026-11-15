from ortools.sat.python import cp_model

class ParameterEnumerator:
    def __init__(self, model: cp_model.CpModel):
        self.model = model
        self.parameters = {}  # IntVar -> {desc, type, name, param_name}
        self.var_to_values = {}  # IntVar -> values list (for fast lookup)
        self.name_to_var = {}  # var name string -> IntVar (for reverse lookup)
        self.shared_parameters = {}  # IntVar -> {workload configuration name: sibling IntVar}
    
    def add_parameter(self, name: str, param_name: str, value, type: str, sweep: bool, desc: str):
        """
        Add a parameter with multiple possible values.
        
        Args:
            name: Unique identifier for this parameter
            values: List of possible values (e.g., [32, 64, 128] or ['small', 'large'])
        
        Returns:
            OR-Tools IntVar representing index into values list
        """

        full_name = f"{desc}_{type}_{name}_{param_name}"

        if sweep:
            # Multiple values - domain is [0, len-1]
            var = self.model.NewIntVar(0, len(value) - 1, full_name)
            
        else:
            # Single value - still create variable but with domain [0, 0]
            var = self.model.NewIntVar(0, 0, full_name)

        values_list = value if sweep else [value]
            
        self.parameters[var] = {
            'desc': desc,
            'type': type,
            'name': name,
            'param_name': param_name
        }

        # Store flat mapping for fast lookup by var
        self.var_to_values[var] = values_list
        
        # Store reverse lookup by name string
        self.name_to_var[full_name] = var
        
        return var
    
    def get_parameters_from_var(self, var: cp_model.IntVar):
        """Retrieve parameter info given an IntVar."""
        assert isinstance(var, cp_model.IntVar), "'var' must be an instance of cp_model.IntVar."
        assert var in self.parameters, f"IntVar '{var.Name()}' not found in parameter enumerator."
        return self.parameters[var]
    
    def get_parameters_from_name(self, var_name: str):
        """Retrieve parameter info given a variable name string."""
        assert isinstance(var_name, str), "'var_name' must be a string."
        assert var_name in self.name_to_var, f"Variable '{var_name}' not found in parameter enumerator."
        var = self.name_to_var[var_name]
        return self.parameters[var]
    
    def get_values_for_var(self, var: cp_model.IntVar):
        """Retrieve the list of actual values for a given IntVar."""
        assert isinstance(var, cp_model.IntVar), "'var' must be an instance of cp_model.IntVar."
        assert var in self.var_to_values, f"IntVar '{var.Name()}' not found in parameter enumerator."
        return self.var_to_values[var]