import hashlib
import json
import os
import platform
import time
from importlib.metadata import PackageNotFoundError, version
from uuid import uuid4

from sqlalchemy import and_, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import events, jobs


LEASE_MS = 10_000
ACTIVE = ("RUNNING", "CANCEL_REQUESTED")
READY = ("QUEUED", "RETRYING")
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
           provenance=None):
    if not 1 <= len(key) <= 128 or not 1 <= max_attempts <= 8 or not 1 <= timeout_ms <= 300_000:
        raise ValueError("Invalid idempotency key or retry settings")
    body = json.dumps([plugin, parameters, max_attempts, timeout_ms, provenance],
                      sort_keys=True, allow_nan=False, separators=(",", ":"))
    fingerprint = hashlib.sha256(body.encode()).hexdigest()
    timestamp = now_ms(connection)
    insert = pg_insert if connection.dialect.name == "postgresql" else sqlite_insert
    inserted = connection.execute(
        insert(jobs).values(
            id=str(uuid4()), project_id=project_id, idempotency_key=key,
            fingerprint=fingerprint, plugin=plugin, parameters=parameters, provenance=provenance,
            state="QUEUED", max_attempts=max_attempts, timeout_ms=timeout_ms,
            created_at=timestamp, available_at=timestamp,
        ).on_conflict_do_nothing(
            index_elements=[jobs.c.project_id, jobs.c.idempotency_key]
        )
    ).rowcount
    existing = connection.execute(select(jobs).where(
        jobs.c.project_id == project_id, jobs.c.idempotency_key == key,
    )).mappings().one()
    if inserted:
        record(connection, existing, "QUEUED", "submitted", timestamp)
    if existing["fingerprint"] != fingerprint:
        raise IdempotencyConflict("Idempotency key already used with different inputs")
    return existing


def locked_job(connection, job_id, project_id=None):
    query = select(jobs).where(jobs.c.id == job_id)
    if project_id is not None:
        query = query.where(jobs.c.project_id == project_id)
    return connection.execute(query.with_for_update()).mappings().one_or_none()


def claim(connection, worker):
    timestamp = now_ms(connection)
    job = connection.execute(
        select(jobs).where(jobs.c.state.in_(READY), jobs.c.available_at <= timestamp)
        .order_by(jobs.c.available_at, jobs.c.created_at, jobs.c.id)
        .limit(1).with_for_update(skip_locked=True)
    ).mappings().one_or_none()
    if job is None:
        return None
    deadline = timestamp + job["timeout_ms"]
    values = dict(
        state="RUNNING", attempt=job["attempt"] + 1, worker=worker,
        token=str(uuid4()), deadline=deadline, lease_until=min(deadline, timestamp + LEASE_MS),
    )
    connection.execute(jobs.update().where(jobs.c.id == job["id"]).values(**values))
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


def transition(connection, job, state, reason, timestamp, result=None):
    values = {"state": state}
    if state != "CANCEL_REQUESTED":
        values.update(worker=None, lease_until=None, deadline=None, token=None)
    if state == "RETRYING":
        values["available_at"] = timestamp + 250 * 2 ** (job["attempt"] - 1)
    if state == "SUCCEEDED":
        values["result"] = result
        values["manifest"] = manifest(job, result, timestamp)
    connection.execute(jobs.update().where(jobs.c.id == job["id"]).values(**values))
    record(connection, job, state, reason, timestamp)


def manifest(job, result, timestamp):
    payload = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
    runtime = {"python": platform.python_version()}
    if job["plugin"] == "age-association@1":
        for dependency in ("numpy", "pandas", "scipy"):
            try:
                runtime[dependency] = version(dependency)
            except PackageNotFoundError:
                runtime[dependency] = "unknown"
    return {
        "job_id": job["id"], "attempt": job["attempt"],
        "plugin_id": job["plugin"].split("@", 1)[0],
        "plugin_version": job["plugin"].split("@", 1)[-1],
        "inputs": job["parameters"], "dataset": job["provenance"],
        "code_version": os.getenv("RESEARCHHUB_CODE_VERSION", "unknown"),
        "runtime": runtime, "completed_at_ms": timestamp,
        "output_sha256": hashlib.sha256(payload.encode()).hexdigest(),
    }


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
        transition(connection, job, "SUCCEEDED", "result_committed", timestamp, result)
    return True


def recover(connection):
    timestamp = now_ms(connection)
    expired = connection.execute(select(jobs).where(and_(
        jobs.c.state.in_(ACTIVE),
        or_(jobs.c.lease_until <= timestamp, jobs.c.deadline <= timestamp),
    )).order_by(jobs.c.lease_until, jobs.c.id).limit(100)
        .with_for_update(skip_locked=True)).mappings().all()
    for job in expired:
        if job["state"] == "CANCEL_REQUESTED":
            transition(connection, job, "CANCELLED", "cancel_lease_expired", timestamp)
        else:
            reason = "deadline_exceeded" if timestamp >= job["deadline"] else "lease_expired"
            fail(connection, job, reason, timestamp, retryable=True)
    return len(expired)

