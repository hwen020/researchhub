"""Fixed scientific pipelines assembled from dataset versions."""
from . import mobility
from .plugins import validate_parameters
from .registry import compute_inputs
from .workflows import start

PIPELINES = {
    "genomics": (
        ("dataset-validation", "genomics-validate@1"),
        ("preprocessing", "genomics-preprocess@1"),
        ("age-association", "genomics-associate@1"),
        ("multiple-testing", "genomics-correct@1"),
        ("report", "genomics-report@1"),
    ),
    "mobility": (
        ("dataset-validation", "mobility-validate@1"),
        ("temporal-processing", "mobility-temporal@1"),
        ("mobility-analysis", "mobility-analyze@1"),
        ("spatial-aggregation", "mobility-spatial@1"),
        ("exports", "mobility-report@1"),
    ),
}


def start_research(connection, storage, project_id, dataset_id, version, discipline, timezone="UTC"):
    plugin = "age-association@1" if discipline == "genomics" else "mobility-validate@1"
    parameters, provenance = compute_inputs(connection, storage, project_id, dataset_id, version, plugin)
    if discipline == "genomics":
        parameters = validate_parameters(plugin, parameters)
    else:
        parameters["timezone"] = timezone
        mobility.validate_observations(parameters)
    definition = {}
    previous = None
    for name, stage in PIPELINES[discipline]:
        spec = {"plugin": stage, "parameters": {}, "depends_on": [], "provenance": provenance}
        if previous is None:
            spec["parameters"] = parameters
        else:
            spec["depends_on"] = [previous]
            spec["input_node"] = previous
        definition[name] = spec
        previous = name
    return start(connection, project_id, definition)
