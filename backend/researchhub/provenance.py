"""Build project-scoped lineage from immutable run snapshots and fenced attempts."""
from sqlalchemy import select

from .models import events, jobs, workflow_versions
from .workflows import definition_checksum, get_run


def manifest(connection, project_id, run_id):
    run = get_run(connection, project_id, run_id)
    ids = {node["job_id"] for node in run["nodes"].values() if "job_id" in node}
    linked_jobs = {job["id"]: job for job in connection.execute(select(jobs).where(
        jobs.c.project_id == project_id, jobs.c.id.in_(ids),
    )).mappings()}
    attempts = {job_id: [] for job_id in linked_jobs}
    for event in connection.execute(select(events).where(events.c.job_id.in_(linked_jobs)).order_by(events.c.id)).mappings():
        attempts[event["job_id"]].append(dict(event))
    nodes = {}
    for name in run["node_order"]:
        node = run["nodes"][name]
        spec = run["definition"][name]
        job = linked_jobs.get(node.get("job_id"))
        job_manifest = (job["manifest"] or {}) if job else {}
        parameters = job["parameters"] if job else spec["parameters"]
        nodes[name] = {
            **node,
            "plugin": spec["plugin"],
            "parameters": parameters,
            "parameter_sha256": definition_checksum(parameters),
            "dataset": job["provenance"] if job else spec.get("provenance"),
            "attempt_events": attempts[job["id"]] if job else [],
            "output_sha256": job_manifest.get("output_sha256"),
            "job_manifest": job_manifest or None,
        }
    version = None
    if run["version_id"]:
        version = connection.execute(select(
            workflow_versions.c.id, workflow_versions.c.definition_id, workflow_versions.c.version,
            workflow_versions.c.checksum,
        ).where(workflow_versions.c.id == run["version_id"])).mappings().one()
    return {
        "run_id": run["id"], "project_id": project_id, "state": run["state"],
        "correlation_id": run["correlation_id"], "created_at_ms": run["created_at"],
        "completed_at_ms": run["completed_at"],
        "version": dict(version) if version else None, "parent_run_id": run["parent_id"],
        "definition_sha256": run["definition_checksum"], "parameters": run["parameters"],
        "nodes": nodes,
    }


def compare(connection, project_id, left, right):
    first = manifest(connection, project_id, left)
    second = manifest(connection, project_id, right)
    fields = ("parameter_sha256", "dataset", "output_sha256", "plugin", "state")
    changes = {}
    for name in sorted(first["nodes"].keys() | second["nodes"].keys()):
        before = first["nodes"].get(name, {})
        after = second["nodes"].get(name, {})
        changed = {field: {"before": before.get(field), "after": after.get(field)}
                   for field in fields if before.get(field) != after.get(field)}
        if changed:
            changes[name] = changed
    return {"left": left, "right": right, "nodes": changes,
            "parameters_changed": first["parameters"] != second["parameters"],
            "definition_changed": first["definition_sha256"] != second["definition_sha256"]}
