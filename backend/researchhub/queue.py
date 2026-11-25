import hashlib
import json
import os
import platform
import time
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from uuid import uuid4

from sqlalchemy import and_, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .artifacts import StorageQuotaExceeded, enqueue
from .models import events, jobs
from .notifications import enqueue as notify
from .observability import correlation_id, emit
from .resource_policy import ACTIVE, READY, admit, candidate, dispatch_project, requirements, scheduling_lock


LEASE_MS = 10_000
TERMINAL = ("SUCCEEDED", "FAILED", "CANCELLED")


class IdempotencyConflict(ValueError):
    pass


def now_ms(connection):
    if connection.dialect.name == "postgresql":
        return connection.execute(
            text("SELECT floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint")
        ).scalar_one()
    return int(time.time() * 1000)


def record(connection, job, state, reason, timestamp):
    connection.execute(events.insert().values(
        job_id=job["id"], attempt=job["attempt"], state=state,
        reason=reason, timestamp=timestamp,
    ))


def submit(connection, project_id, key, plugin, parameters, *, max_attempts=3, timeout_ms=30_000,
           provenance=None, capability=None, cpu_units=1, memory_units=1, priority=0,
           trace_id=None, workflow_run_id=None):
    if not 1 <= len(key) <= 128 or not 1 <= max_attempts <= 8 or not 1 <= timeout_ms <= 300_000:
        raise ValueError("Invalid idempotency key or retry settings")
    resources = requirements(plugin, capability, cpu_units, memory_units, priority)
    inputs = [plugin, parameters, max_attempts, timeout_ms]
    if provenance is not None:
        inputs.append(provenance)
    if resources != requirements(plugin, None, 1, 1, 0):
        inputs.append({"resources": resources})
    body = json.dumps(inputs,
                      sort_keys=True, allow_nan=False, separators=(",", ":"))
    fingerprint = hashlib.sha256(body.encode()).hexdigest()
    scheduling_lock(connection)
    existing = connection.execute(select(jobs).where(
        jobs.c.project_id == project_id, jobs.c.idempotency_key == key,
    )).mappings().one_or_none()
    if existing is not None:
        if existing["fingerprint"] != fingerprint:
            raise IdempotencyConflict("Idempotency key already used with different inputs")
        return existing
    admit(connection, project_id, resources)
    timestamp = now_ms(connection)
    insert = pg_insert if connection.dialect.name == "postgresql" else sqlite_insert
    inserted = connection.execute(
        insert(jobs).values(
            id=str(uuid4()), project_id=project_id, idempotency_key=key,
            fingerprint=fingerprint, plugin=plugin, parameters=parameters, provenance=provenance,
            state="QUEUED", max_attempts=max_attempts, timeout_ms=timeout_ms,
            created_at=timestamp, available_at=timestamp, correlation_id=correlation_id(trace_id),
            workflow_run_id=workflow_run_id, **resources,
        ).on_conflict_do_nothing(
            index_elements=[jobs.c.project_id, jobs.c.idempotency_key]
        )
    ).rowcount
    existing = connection.execute(select(jobs).where(
        jobs.c.project_id == project_id, jobs.c.idempotency_key == key,
    )).mappings().one()
    if inserted:
        record(connection, existing, "QUEUED", "submitted", timestamp)
        emit("job_enqueued", correlation_id=existing["correlation_id"], job_id=existing["id"],
             workflow_run_id=workflow_run_id)
    if existing["fingerprint"] != fingerprint:
        raise IdempotencyConflict("Idempotency key already used with different inputs")
    return existing


def locked_job(connection, job_id, project_id=None):
    query = select(jobs).where(jobs.c.id == job_id)
    if project_id is not None:
        query = query.where(jobs.c.project_id == project_id)
    return connection.execute(query.with_for_update()).mappings().one_or_none()


def claim(connection, worker, capabilities=("GENERAL", "GENOMICS"), cpu_units=32, memory_units=32, *, project_id=None):
    scheduling_lock(connection)
    timestamp = now_ms(connection)
    job = candidate(connection, timestamp, capabilities, cpu_units, memory_units, project_id)
    if job is None:
        return None
    deadline = timestamp + job["timeout_ms"]
    values = dict(
        state="RUNNING", attempt=job["attempt"] + 1, worker=worker,
        token=str(uuid4()), deadline=deadline, lease_until=min(deadline, timestamp + LEASE_MS),
    )
    connection.execute(jobs.update().where(jobs.c.id == job["id"]).values(**values))
    dispatch_project(connection, job["project_id"])
    claimed = dict(job, **values)
    record(connection, claimed, "RUNNING", "claimed", timestamp)
    return claimed


def owns(job, token, timestamp):
    return (job is not None and job["state"] in ACTIVE and job["token"] == token
            and timestamp < min(job["deadline"], job["lease_until"]))


def heartbeat(connection, job_id, token):
    job = locked_job(connection, job_id)
    timestamp = now_ms(connection)
    if not owns(job, token, timestamp):
        return "LOST"
    if job["state"] == "RUNNING":
        connection.execute(jobs.update().where(jobs.c.id == job_id).values(
            lease_until=min(job["deadline"], timestamp + LEASE_MS),
        ))
    return job["state"]


def transition(connection, job, state, reason, timestamp, result=None, artifact_id=None):
    values = {"state": state}
    if state != "CANCEL_REQUESTED":
        values.update(worker=None, lease_until=None, deadline=None, token=None)
    if state == "RETRYING":
        values["available_at"] = timestamp + 250 * 2 ** (job["attempt"] - 1)
    if state == "SUCCEEDED":
        values["result"] = result
        values["manifest"] = manifest(job, result, timestamp)
        if artifact_id is not None:
            values["manifest"]["output_artifact_id"] = artifact_id
    connection.execute(jobs.update().where(jobs.c.id == job["id"]).values(**values))
    record(connection, job, state, reason, timestamp)


def manifest(job, result, timestamp):
    payload = encode_result(result)
    runtime = {"python": platform.python_version()}
    if job["plugin"] == "age-association@1" or job["plugin"].startswith("genomics-"):
        for dependency in ("numpy", "pandas", "scipy"):
            try:
                runtime[dependency] = version(dependency)
            except PackageNotFoundError:
                runtime[dependency] = "unknown"
    provenance = job["provenance"]
    result_manifest = {
        "job_id": job["id"], "attempt": job["attempt"],
        "correlation_id": job["correlation_id"], "workflow_run_id": job["workflow_run_id"],
        "plugin_id": job["plugin"].split("@", 1)[0],
        "plugin_version": job["plugin"].split("@", 1)[-1],
        "inputs": job["parameters"],
        "dataset": {key: value for key, value in provenance.items() if key != "artifact_id"} if provenance else provenance,
        "code_version": os.getenv("RESEARCHHUB_CODE_VERSION") or source_version(),
        "runtime": runtime, "completed_at_ms": timestamp,
        "output_sha256": hashlib.sha256(payload).hexdigest(),
    }
    if provenance and provenance.get("artifact_id"):
        result_manifest["input_artifact_id"] = provenance["artifact_id"]
    return result_manifest


def encode_result(result):
    return json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@lru_cache(maxsize=1)
def source_version():
    digest = hashlib.sha256()
    source = Path(__file__).parent
    for path in sorted(source.glob("*.py")):
        digest.update(path.name.encode() + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return "sha256:" + digest.hexdigest()


def cancel(connection, project_id, job_id):
    job = locked_job(connection, job_id, project_id)
    if job is None:
        raise LookupError("Job not found")
    state = job["state"]
    if state in READY or state == "RUNNING":
        state = "CANCEL_REQUESTED" if state == "RUNNING" else "CANCELLED"
        transition(connection, job, state, "cancel_requested", now_ms(connection))
    return state


def fail(connection, job, reason, timestamp, retryable):
    retry = retryable and job["attempt"] < job["max_attempts"]
    state = "RETRYING" if retry else "FAILED"
    if state == "FAILED" and retryable:
        record(connection, job, "FAILED", reason, timestamp)
        reason = "dead_letter"
    transition(connection, job, state, reason, timestamp)
    if state == "FAILED" and os.getenv("RESEARCHHUB_DEMO_MODE") != "1":
        notify(connection, job["project_id"], "JOB_FAILED", job["id"], "A research job failed",
               timestamp, job["correlation_id"])


def finish(connection, job_id, token, *, result=None, error=None, retryable=False):
    job = locked_job(connection, job_id)
    timestamp = now_ms(connection)
    if not owns(job, token, timestamp):
        return False
    if job["state"] == "CANCEL_REQUESTED":
        transition(connection, job, "CANCELLED", "worker_cancelled", timestamp)
    elif error is not None:
        fail(connection, job, error, timestamp, retryable)
    else:
        artifact_id = None
        if os.getenv("RESEARCHHUB_DEMO_MODE") != "1":
            try:
                artifact_id = enqueue(connection, job["project_id"], encode_result(result), timestamp,
                                      kind="RESULT", content_type="application/json", job_id=job_id,
                                      trace_id=job["correlation_id"])
            except StorageQuotaExceeded:
                fail(connection, job, "artifact_quota_exceeded", timestamp, False)
                return True
            except ValueError:
                fail(connection, job, "invalid_artifact_output", timestamp, False)
                return True
        transition(connection, job, "SUCCEEDED", "result_committed", timestamp, result, artifact_id)
    return True


def recover(connection, *, project_id=None):
    timestamp = now_ms(connection)
    query = select(jobs).where(and_(
        jobs.c.state.in_(ACTIVE),
        or_(jobs.c.lease_until <= timestamp, jobs.c.deadline <= timestamp),
    ))
    if project_id is not None:
        query = query.where(jobs.c.project_id == project_id)
    expired = connection.execute(query.order_by(jobs.c.lease_until, jobs.c.id).limit(100)
                                 .with_for_update(skip_locked=True)).mappings().all()
    for job in expired:
        if job["state"] == "CANCEL_REQUESTED":
            transition(connection, job, "CANCELLED", "cancel_lease_expired", timestamp)
        else:
            reason = "deadline_exceeded" if timestamp >= job["deadline"] else "lease_expired"
            fail(connection, job, reason, timestamp, retryable=True)
    return len(expired)

