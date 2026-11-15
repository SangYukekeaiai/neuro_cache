"""One event per module to populate the energy-query graph, not a latency model."""


def spinalflow_stub(architecture_dict, workload_dict):
    subevents = {}
    for name, module in architecture_dict.items():
        event = {"count": workload_dict["configuration"]["events"]}
        if module["query"]["interface"] == "cacti_fn":
            event["operation"] = {"dynamic_energy": "read"}
        subevents[name] = event
    return {"subevent": subevents}
