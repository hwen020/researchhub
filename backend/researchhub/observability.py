"""Structured correlation and bounded runtime observations."""
from contextvars import ContextVar
import json
import os
import sys
from uuid import uuid4

from sqlalchemy import func, select

from .models import artifacts, events, jobs, workflow_runs

request_id = ContextVar("request_id", default=None)
WINDOW_MS = 86_400_000
SAMPLE_LIMIT = 20_000


def correlation_id(existing=None):
    return existing or request_id.get() or str(uuid4())


def emit(event, **fields):
    if os.getenv("RESEARCHHUB_STRUCTURED_LOGS", "1") == "1":
        print(json.dumps({"event": event, **fields}, separators=(",", ":")), file=sys.stderr, flush=True)


def runtime_snapshot(connection, timestamp, distribution):
    since = timestamp - WINDOW_MS
    workflow_times = connection.execute(select(
        (workflow_runs.c.completed_at - workflow_runs.c.created_at).label("duration")
    ).where(workflow_runs.c.completed_at >= since, workflow_runs.c.created_at.is_not(None))
        .order_by(workflow_runs.c.completed_at.desc()).limit(SAMPLE_LIMIT)).scalars().all()
    artifact_timing = connection.execute(select(artifacts.c.publish_ms).where(
        artifacts.c.created_at >= since, artifacts.c.publish_ms.is_not(None),
    ).order_by(artifacts.c.created_at.desc()).limit(SAMPLE_LIMIT)).scalars().all()
    storage = connection.execute(select(artifacts.c.state, func.count(), func.sum(artifacts.c.size))
                                 .group_by(artifacts.c.state)).all()
    failure_events = connection.execute(select(events.c.job_id, events.c.state, events.c.reason, events.c.timestamp)
                                        .where(events.c.timestamp >= since)
                                        .order_by(events.c.timestamp.desc(), events.c.id.desc())
                                        .limit(SAMPLE_LIMIT)).all()
    classifications = {}
    lost = {}
    recovery = []
    for row in reversed(failure_events):
        if row.state in {"FAILED", "RETRYING"}:
            classifications[row.reason] = classifications.get(row.reason, 0) + 1
        if row.state == "RETRYING" and row.reason in {"lease_expired", "deadline_exceeded"}:
            lost[row.job_id] = row.timestamp
        if row.state == "RUNNING" and row.job_id in lost:
            recovery.append(row.timestamp - lost.pop(row.job_id))
    depths = connection.execute(select(jobs.c.project_id, func.count().label("size")).where(
        jobs.c.state.in_(("QUEUED", "RETRYING")),
    ).group_by(jobs.c.project_id).order_by(func.count().desc(), jobs.c.project_id).limit(100)).all()
    return {
        "project_queue_depth": {project: size for project, size in depths},
        "workflow_completion_ms": distribution(workflow_times),
        "artifact_publish_ms": distribution(artifact_timing),
        "artifact_counts": {state: count for state, count, _ in storage},
        "artifact_storage_bytes": sum(size for _, _, size in storage),
        "job_failure_reasons": classifications,
        "worker_recovery_ms": distribution(recovery),
    }


def prometheus_text(snapshot):
    metrics = (
        ("queue_depth", snapshot["queue_depth"]),
        ("queue_saturation_ratio", snapshot["queue_saturation"]),
        ("workers_online", snapshot["workers_online"]),
        ("managed_artifact_bytes", snapshot["artifact_storage_bytes"]),
    )
    lines = []
    for name, value in metrics:
        lines.extend([f"# TYPE researchhub_{name} gauge", f"researchhub_{name} {value}"])
    lines.append("# TYPE researchhub_jobs gauge")
    for state, count in sorted(snapshot["jobs_by_state"].items()):
        lines.append(f'researchhub_jobs{{state="{state}"}} {count}')
    lines.append("# TYPE researchhub_artifacts gauge")
    for state, count in sorted(snapshot["artifact_counts"].items()):
        lines.append(f'researchhub_artifacts{{state="{state}"}} {count}')
    return "\n".join(lines) + "\n"
