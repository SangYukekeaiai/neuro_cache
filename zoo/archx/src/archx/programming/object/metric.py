from loguru import logger

class Metric:
    def __init__(self):
        self.metrics = {'metric': {}}

    def add_metric(self, name: str, unit: str, aggregation: str):
        assert isinstance(name, str), "'name' parameter must be of type 'str'."
        assert isinstance(unit, str), "'unit' parameter must be of type 'str'."
        assert isinstance(aggregation, str), "'aggregation' parameter must be of type 'str'."

        self.metrics['metric'][name] = {
            "unit": unit,
            "aggregation": aggregation
        }

        logger.info(f"Added metric '{name}'.")
        logger.debug(f"\tUnit: {unit}")
        logger.debug(f"\tAggregation: {aggregation}")

    def to_yaml(self):
        return self.metrics