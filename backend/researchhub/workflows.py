import hashlib
import json
from collections import deque
from uuid import uuid4

from sqlalchemy import select

from .models import jobs, workflow_runs
from .queue import TERMINAL, cancel, now_ms, submit
from .resource_policy import QueueFull

NODE_TERMINAL = set(TERMINAL) | {"BLOCKED", "SKIPPED"}
RUN_TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


def definition_checksum(definition):
    encoded = json.dumps(definition, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate(nodes):
    if not 1 <= len(nodes) <= 64:
        raise ValueError("A workflow must contain 1 to 64 nodes")
    dependents = {name: [] for name in nodes}
    in_degree = {}
    for name, node in nodes.items():
        dependencies = node["depends_on"]
        if not 1 <= len(name) <= 64 or len(set(dependencies)) != len(dependencies):
            raise ValueError("Invalid node name or duplicate dependency")
        for dependency in dependencies:
            if dependency not in nodes:
                raise ValueError("Unknown dependency")
            dependents[dependency].append(name)
        if "input_node" in node and node["input_node"] not in dependencies:
            raise ValueError("Node input must name a direct dependency")
        clause = node.get("when")
        if clause is not None:
            mode = clause["mode"]
            if mode == "result_equals":
                if clause.get("node") not in dependencies or not clause.get("field") or "value" not in clause:
                    raise ValueError("A result condition requires a direct dependency, field and value")
            elif mode not in ("success", "failure", "always"):
                raise ValueError("Unknown dependency condition")
        in_degree[name] = len(dependencies)

    ready = deque(name for name in nodes if in_degree[name] == 0)
    ordered = []
    while ready:
        name = ready.popleft()
        ordered.append(name)
        for dependent in dependents[name]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)
    if len(ordered) != len(nodes):
        raise ValueError("Workflow contains a cycle")
    return ordered


def start(connection, project_id, definition, *, version_id=None, parameters=None, parent_id=None,
          preserved=None):
    order = validate(definition)
    run_id = str(uuid4())
    nodes = {name: {"state": "WAITING"} for name in order}
    if preserved:
        nodes.update(preserved)
    connection.execute(workflow_runs.insert().values(
        id=run_id, project_id=project_id, definition=definition, node_order=order,
        nodes=nodes, state="RUNNING", version_id=version_id, parent_id=parent_id,
        parameters=parameters, definition_checksum=definition_checksum(definition),
    ))
    return run_id


def get_run(connection, project_id, run_id, *, lock=False):
    query = select(workflow_runs).where(workflow_runs.c.project_id == project_id, workflow_runs.c.id == run_id)
    if lock:
        query = query.with_for_update()
    run = connection.execute(query).mappings().one_or_none()
    if run is None:
        raise LookupError("Workflow run not found")
    return run


def cancel_run(connection, project_id, run_id):
    run = get_run(connection, project_id, run_id, lock=True)
    if run["state"] in RUN_TERMINAL:
        return run["state"]
    nodes = run["nodes"]
    for node in nodes.values():
        if node["state"] in NODE_TERMINAL or node.get("reused_from"):
            continue
        node["state"] = cancel(connection, project_id, node["job_id"]) if "job_id" in node else "CANCELLED"
    state = "CANCELLED" if all(node["state"] in NODE_TERMINAL for node in nodes.values()) else "CANCEL_REQUESTED"
    connection.execute(workflow_runs.update().where(workflow_runs.c.id == run_id).values(
        state=state, nodes=nodes, checked_at=now_ms(connection),
    ))
    return state


def rerun(connection, project_id, run_id, failed_node=None):
    run = get_run(connection, project_id, run_id, lock=True)
    if run["state"] not in {"FAILED", "CANCELLED"}:
        raise ValueError("Only a failed or cancelled workflow can be rerun")
    nodes = run["nodes"]
    if failed_node is not None and nodes.get(failed_node, {}).get("state") not in {"FAILED", "CANCELLED"}:
        raise ValueError("The selected node must have failed or been cancelled")
    affected = set()
    for name in run["node_order"]:
        dependencies = run["definition"][name]["depends_on"]
        retry = name == failed_node if failed_node is not None else nodes[name]["state"] not in {"SUCCEEDED", "SKIPPED"}
        if retry or affected.intersection(dependencies):
            affected.add(name)
    preserved = {name: dict(node, reused_from=run_id) for name, node in nodes.items() if name not in affected}
    return start(connection, project_id, run["definition"], version_id=run["version_id"],
                 parameters=run["parameters"], parent_id=run_id, preserved=preserved)


def dependency_state(spec, nodes, results):
    upstream = [nodes[name]["state"] for name in spec["depends_on"]]
    if not all(state in NODE_TERMINAL for state in upstream):
        return "WAITING"
    clause = spec.get("when")
    mode = clause["mode"] if clause else "success"
    if mode == "always":
        return "READY"
    if mode == "failure":
        return "READY" if "FAILED" in upstream else "SKIPPED"
    if mode == "result_equals":
        node = nodes[clause["node"]]
        result = results.get(node.get("job_id"))
        value = clause["value"]
        if (node["state"] == "SUCCEEDED" and isinstance(result, dict) and clause["field"] in result
                and type(result[clause["field"]]) is type(value) and result[clause["field"]] == value):
            return "READY"
        return "SKIPPED"
    if any(state in {"FAILED", "CANCELLED", "BLOCKED"} for state in upstream):
        return "BLOCKED"
    return "SKIPPED" if "SKIPPED" in upstream else "READY"


def reconcile(connection, *, project_id=None):
    query = select(workflow_runs).where(workflow_runs.c.state.in_(("RUNNING", "CANCEL_REQUESTED")))
    if project_id is not None:
        query = query.where(workflow_runs.c.project_id == project_id)
    runs = connection.execute(
        query.order_by(workflow_runs.c.checked_at, workflow_runs.c.id)
        .limit(20).with_for_update(skip_locked=True)
    ).mappings().all()
    for run in runs:
        nodes = run["nodes"]
        linked = [node["job_id"] for node in nodes.values() if "job_id" in node]
        job_rows = connection.execute(select(jobs.c.id, jobs.c.state, jobs.c.result, jobs.c.manifest).where(
            jobs.c.id.in_(linked),
        )).all()
        job_states = {row.id: row.state for row in job_rows}
        results = {row.id: row.result for row in job_rows}
        manifests = {row.id: row.manifest for row in job_rows}
        for name in run["node_order"]:
            node = nodes[name]
            if "job_id" in node:
                node["state"] = job_states[node["job_id"]]
        for name in run["node_order"]:
            node = nodes[name]
            if "job_id" in node or node["state"] in NODE_TERMINAL or run["state"] == "CANCEL_REQUESTED":
                continue
            spec = run["definition"][name]
            ready = dependency_state(spec, nodes, results)
            if ready == "READY":
                parameters = spec["parameters"]
                provenance = spec.get("provenance")
                if "input_node" in spec:
                    upstream = nodes[spec["input_node"]]
                    if upstream["state"] != "SUCCEEDED":
                        node["state"] = "BLOCKED"
                        continue
                    parent_job_id = upstream["job_id"]
                    parameters = results[parent_job_id]
                    provenance = dict(provenance or {}, upstream={
                        "job_id": parent_job_id, "sha256": manifests[parent_job_id]["output_sha256"],
                    })
                try:
                    job = submit(
                        connection, run["project_id"], "dag:" + run["id"] + ":" + name,
                        spec["plugin"], parameters, provenance=provenance,
                    )
                except QueueFull:
                    continue
                node.update(job_id=job["id"], state=job["state"])
            else:
                node["state"] = ready
        states = {node["state"] for node in nodes.values()}
        state = run["state"]
        if states <= NODE_TERMINAL:
            if state == "CANCEL_REQUESTED":
                state = "CANCELLED"
            else:
                state = "SUCCEEDED" if states <= {"SUCCEEDED", "SKIPPED"} else "FAILED"
        connection.execute(workflow_runs.update().where(workflow_runs.c.id == run["id"]).values(
            nodes=nodes, state=state, checked_at=now_ms(connection),
        ))
    return len(runs)

