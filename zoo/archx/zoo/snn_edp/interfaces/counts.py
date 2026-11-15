"""Price-free initialization for archx CLI count checkpoints."""
def query(module, interface, query, input_dir, output_dir):
    return {name: {'value': 0.0, 'unit': unit} for name, unit in (
        ('dynamic_energy','nJ'), ('leakage_power','mW'), ('area','mm^2'))}
