"""PostgreSQL scheduling policy shared by HTTP, DAG and worker transactions."""
import os

from sqlalchemy import case, func, select, text

from .models import jobs, projects, workers

ACTIVE = ("RUNNING", "CANCEL_REQUESTED")
READY = ("QUEUED", "RETRYING")
CAPABILITIES = ("GENERAL", "GENOMICS", "GEOSPATIAL", "HIGH_MEMORY")
AGING_MS = 30_000
DEFAULT_SYSTEM_LIMIT = 10_000
QUOTA_FIELDS = ("max_concurrent", "max_queued", "quota_cpu", "quota_memory")


class QueueFull(ValueError):
    pass


def system_limit():
    limit = int(os.getenv("RESEARCHHUB_SYSTEM_QUEUE_LIMIT", str(DEFAULT_SYSTEM_LIMIT)))
    if limit < 1:
        raise ValueError("System queue limit must be positive")
    return limit


def scheduling_lock(connection):
    if connection.dialect.name == "postgresql":
        connection.execute(text(
            "SELECT pg_advisory_xact_lock(1475938179, hashtext(current_schema()))"
        ))


def requirements(plugin, capability, cpu_units, memory_units, priority):
    required = "GENERAL"
    if plugin.startswith("mobility-"):
        required = "GEOSPATIAL"
    elif plugin == "age-association@1" or plugin.startswith("genomics-"):
        required = "GENOMICS"
    capability = capability or required
    if capability not in CAPABILITIES:
        raise ValueError("Unknown worker capability")
    if required != "GENERAL" and capability != required:
        raise ValueError(f"The plugin requires {required}")
    for value, low, high in ((cpu_units, 1, 1024), (memory_units, 1, 1024), (priority, 0, 10)):
        if type(value) is not int or not low <= value <= high:
            raise ValueError("Invalid logical resource units or priority")
    return dict(capability=capability, cpu_units=cpu_units, memory_units=memory_units,
                priority=priority)


def project_usage(connection, project_id):
    active = jobs.c.state.in_(ACTIVE)
    row = connection.execute(select(
        func.count().filter(active).label("active"),
        func.count().filter(jobs.c.state.in_(READY)).label("queued"),
        func.coalesce(func.sum(jobs.c.cpu_units).filter(active), 0).label("cpu_units"),
        func.coalesce(func.sum(jobs.c.memory_units).filter(active), 0).label("memory_units"),
    ).where(jobs.c.project_id == project_id, jobs.c.state.in_(ACTIVE + READY))).mappings().one()
    return dict(row)


def admit(connection, project_id, resources):
    quota = connection.execute(select(projects).where(projects.c.id == project_id)).mappings().one()
    if resources["cpu_units"] > quota["quota_cpu"] or resources["memory_units"] > quota["quota_memory"]:
        raise ValueError("Job exceeds project logical resource quota")
    usage = project_usage(connection, project_id)
    # Active attempts keep a queue slot so lease recovery and retry cannot overfill the queue.
    if usage["queued"] + usage["active"] >= quota["max_queued"]:
        raise QueueFull("Project queue is saturated")
    outstanding = connection.execute(select(func.count()).select_from(jobs).where(
        jobs.c.state.in_(ACTIVE + READY),
    )).scalar_one()
    if outstanding >= system_limit():
        raise QueueFull("System queue is saturated")


def candidate(connection, timestamp, capabilities, cpu_units, memory_units, project_id=None):
    usage = select(
        jobs.c.project_id,
        func.count().label("active"),
        func.sum(jobs.c.cpu_units).label("cpu"),
        func.sum(jobs.c.memory_units).label("memory"),
    ).where(jobs.c.state.in_(ACTIVE)).group_by(jobs.c.project_id).subquery()
    # Ceiling makes the oldest jobs tie at max priority and then win by age.
    effective_priority = case(
        (jobs.c.priority + (timestamp - jobs.c.created_at) / AGING_MS >= 10, 10),
        else_=jobs.c.priority + func.floor((timestamp - jobs.c.created_at) / AGING_MS),
    )
    query = select(jobs).join(projects, jobs.c.project_id == projects.c.id).outerjoin(
        usage, usage.c.project_id == jobs.c.project_id,
    ).where(
        jobs.c.state.in_(READY), jobs.c.available_at <= timestamp,
        jobs.c.capability.in_(capabilities),
        jobs.c.cpu_units <= cpu_units, jobs.c.memory_units <= memory_units,
        func.coalesce(usage.c.active, 0) < projects.c.max_concurrent,
        func.coalesce(usage.c.cpu, 0) + jobs.c.cpu_units <= projects.c.quota_cpu,
        func.coalesce(usage.c.memory, 0) + jobs.c.memory_units <= projects.c.quota_memory,
    ).order_by(
        projects.c.last_dispatch, effective_priority.desc(), jobs.c.created_at,
        jobs.c.available_at, jobs.c.id,
    ).limit(1).with_for_update(of=jobs, skip_locked=True)
    if project_id is not None:
        query = query.where(jobs.c.project_id == project_id)
    return connection.execute(query).mappings().one_or_none()


def dispatch_project(connection, project_id):
    sequence = select(func.coalesce(func.max(projects.c.last_dispatch), 0) + 1).scalar_subquery()
    connection.execute(projects.update().where(projects.c.id == project_id).values(last_dispatch=sequence))


def wait_reason(job, quota, usage, eligible_workers, timestamp):
    if job["available_at"] > timestamp:
        return "retry_backoff"
    if (usage["active"] >= quota["max_concurrent"]
            or usage["cpu_units"] + job["cpu_units"] > quota["quota_cpu"]
            or usage["memory_units"] + job["memory_units"] > quota["quota_memory"]):
        return "project_resources"
    if not any(job["capability"] in worker["capabilities"]
               and worker["cpu_units"] >= job["cpu_units"]
               and worker["memory_units"] >= job["memory_units"] for worker in eligible_workers):
        return "no_matching_worker"
    return "awaiting_dispatch"


def online_workers(connection, timestamp):
    return connection.execute(select(workers).where(
        workers.c.last_seen > timestamp - 10_000
    ).order_by(workers.c.id)).mappings().all()
