from collections import deque
from uuid import uuid4

from sqlalchemy import select

from .models import jobs, workflow_runs
from .queue import TERMINAL, submit


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


def start(connection, project_id, definition):
    order = validate(definition)
    run_id = str(uuid4())
    connection.execute(workflow_runs.insert().values(
        id=run_id, project_id=project_id, definition=definition, node_order=order,
        nodes={name: {"state": "WAITING"} for name in order}, state="RUNNING",
    ))
    return run_id


def reconcile(connection):
    runs = connection.execute(
        select(workflow_runs).where(workflow_runs.c.state == "RUNNING")
        .order_by(workflow_runs.c.checked_at, workflow_runs.c.id)
        .limit(20).with_for_update(skip_locked=True)
    ).mappings().all()
    from .queue import now_ms

    for run in runs:
        nodes = run["nodes"]
        linked = [node["job_id"] for node in nodes.values() if "job_id" in node]
        job_states = dict(connection.execute(
            select(jobs.c.id, jobs.c.state).where(jobs.c.id.in_(linked))
        ).all())
        for name in run["node_order"]:
            node = nodes[name]
            if "job_id" in node:
                node["state"] = job_states[node["job_id"]]
                continue
            spec = run["definition"][name]
            upstream = [nodes[key]["state"] for key in spec["depends_on"]]
            if any(state in ("FAILED", "CANCELLED", "BLOCKED") for state in upstream):
                node["state"] = "BLOCKED"
            elif all(state == "SUCCEEDED" for state in upstream):
                job = submit(
                    connection, run["project_id"], "dag:" + run["id"] + ":" + name,
                    spec["plugin"], spec["parameters"],
                )
                node.update(job_id=job["id"], state=job["state"])
        states = {node["state"] for node in nodes.values()}
        state = "RUNNING"
        if states <= set(TERMINAL) | {"BLOCKED"}:
            state = "SUCCEEDED" if states == {"SUCCEEDED"} else "FAILED"
        connection.execute(workflow_runs.update().where(workflow_runs.c.id == run["id"]).values(
            nodes=nodes, state=state, checked_at=now_ms(connection),
        ))
    return len(runs)

