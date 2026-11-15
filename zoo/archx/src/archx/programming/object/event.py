from loguru import logger
from copy import deepcopy

class Event:
    def __init__(self, parameter_enumerator=None):
        self.events = {'event': {}}
        self.parameter_enumerator = parameter_enumerator
        self.swept_candidates = {}  # event name -> list of candidate subevent lists

    def add_event(self, name=None, subevent=None, performance=None, event_dict=None):
        if event_dict is not None:
            assert isinstance(event_dict, dict), "'event_dict' parameter must be of type 'dict'."
            param_dict = {}
            for name, subevent in event_dict.items():
                assert isinstance(name, str), "Event names must be of type 'str'."
                assert isinstance(subevent, list), "Event subevents must be of type 'list'."
                param = self._add_event(name, subevent, performance)
                if param is not None:
                    param_dict[name] = param
            return param_dict if param_dict else None

        else:
            assert isinstance(name, str) or (
                isinstance(name, list) and all(isinstance(n, str) for n in name)
            ), "'name' parameter must be of type 'str' or list of type 'str'."

            assert isinstance(subevent, list), "'subevent' parameter must be of type 'list'."
            assert isinstance(performance, str), "'performance' parameter must be of type 'str'."

            if isinstance(name, list):
                param_dict = {}
                for n in name:
                    param = self._add_event(n, subevent, performance)
                    if param is not None:
                        param_dict[n] = param
                return param_dict if param_dict else None
            else:
                return self._add_event(name, subevent, performance)


    def _add_event(self, name, subevent: list, performance: str):
        assert name not in self.events['event'], f"Event '{name}' already exists in event."

        # check if subevent is a sweep (list of lists) or not, mirroring module instances
        sub_sweep = None
        for sub in subevent:
            sweep_check = isinstance(sub, list)
            if sub_sweep is None:
                sub_sweep = sweep_check
            else:
                assert sub_sweep == sweep_check, "All subevent entries must be of the same type (sweep or non-sweep)."

        if sub_sweep:
            assert self.parameter_enumerator is not None, \
                "Event sweeping requires a parameter enumerator."
            sub_param = self.parameter_enumerator.add_parameter(name=name,
                                                                param_name='subevent',
                                                                value=subevent,
                                                                type='event',
                                                                sweep=True,
                                                                desc='event')
            # subevent is resolved per configuration in to_yaml()
            self.events['event'][name] = {'subevent': None, 'performance': performance}
            self.swept_candidates[name] = deepcopy(subevent)

            logger.info(f"Added event: {name}")
            for i, sub in enumerate(subevent):
                logger.debug(f"\tSubevent candidate {i}: {sub}")
            logger.debug(f"\tPerformance: {performance}")

            return {'subevent': sub_param}
        else:
            self.events['event'][name] = {'subevent': deepcopy(subevent), 'performance': performance}

            logger.info(f"Added event: {name}")
            for sub in subevent:
                logger.debug(f"\tSubevent: {sub}")
            logger.debug(f"\tPerformance: {performance}")

            return None

    def _prune_unreachable(self, events):
        """
        Drop events unreachable from the root events. Roots are events never
        referenced as a subevent anywhere, including in any sweep candidate list,
        so an unselected sweep branch does not masquerade as a root.
        """
        referenced = set()
        for name, event in self.events['event'].items():
            if name in self.swept_candidates:
                for candidate in self.swept_candidates[name]:
                    referenced.update(candidate)
            else:
                referenced.update(event['subevent'])

        roots = [name for name in events if name not in referenced]

        visited = set()
        stack = list(roots)
        while stack:
            current = stack.pop()
            if current in visited or current not in events:
                continue
            visited.add(current)
            stack.extend(events[current]['subevent'])

        return {name: event for name, event in events.items() if name in visited}

    def to_yaml(self, config=None):
        events = deepcopy(self.events['event'])

        if config is not None:
            for var_name, value in config.items():
                param_info = self.parameter_enumerator.get_parameters_from_name(var_name)
                events[param_info['name']]['subevent'] = deepcopy(value)

            for name, event in events.items():
                assert event['subevent'] is not None, \
                    f"Swept event '{name}' has no resolved subevent; missing configuration."

            # each generated event graph keeps only the selected branches
            events = self._prune_unreachable(events)
        else:
            for name, event in events.items():
                assert event['subevent'] is not None, \
                    f"Swept event '{name}' requires a configuration to resolve."

        return {'event': events}
