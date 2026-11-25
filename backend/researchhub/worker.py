import os
import time
from uuid import uuid4

from sqlalchemy.exc import OperationalError
from sqlalchemy.dialects.postgresql import insert

from .db import connect
from .demo_fixture import demo_project
from .execution import LocalExecutionBackend
from .models import workers
from .observability import emit
from .queue import claim, finish, heartbeat, now_ms, recover
from .resource_policy import CAPABILITIES


def worker_resources():
    capabilities = sorted(set(os.getenv("RESEARCHHUB_WORKER_CAPABILITIES", "GENERAL,GENOMICS").split(",")))
    cpu_units = int(os.getenv("RESEARCHHUB_WORKER_CPU_UNITS", "32"))
    memory_units = int(os.getenv("RESEARCHHUB_WORKER_MEMORY_UNITS", "32"))
    if not set(capabilities) <= set(CAPABILITIES) or not (1 <= cpu_units <= 1024 and 1 <= memory_units <= 1024):
        raise ValueError("Invalid worker capabilities or logical capacity")
    return {"capabilities": capabilities, "cpu_units": cpu_units, "memory_units": memory_units}


def report_worker(connection, worker, resources):
    timestamp = now_ms(connection)
    statement = insert(workers).values(id=worker, last_seen=timestamp, **resources)
    connection.execute(statement.on_conflict_do_update(
        index_elements=[workers.c.id], set_={"last_seen": timestamp, **resources},
    ))


def execute_attempt(engine, job, backend):
    try:
        handle = backend.submit(job)
    except ValueError:
        with engine.begin() as connection:
            finish(connection, job["id"], job["token"], error="invalid_execution_backend")
        return
    except OSError:
        with engine.begin() as connection:
            finish(connection, job["id"], job["token"], error="executor_unavailable", retryable=True)
        return
    emit("attempt_started", correlation_id=job["correlation_id"], job_id=job["id"],
         workflow_run_id=job["workflow_run_id"], attempt=job["attempt"])
    next_heartbeat = 0
    try:
        while True:
            if time.monotonic() >= next_heartbeat:
                with engine.begin() as connection:
                    report_worker(connection, job["worker"], backend.capabilities())
                    state = heartbeat(connection, job["id"], job["token"])
                if state == "LOST":
                    return
                if state == "CANCEL_REQUESTED":
                    outcome = {}
                    break
                next_heartbeat = time.monotonic() + 0.5
            outcome = backend.poll(handle, 0.1)
            if outcome is not None:
                break
        with engine.begin() as connection:
            committed = finish(connection, job["id"], job["token"], **outcome)
        emit("attempt_finished", correlation_id=job["correlation_id"], job_id=job["id"],
             workflow_run_id=job["workflow_run_id"], attempt=job["attempt"], committed=committed)
    finally:
        backend.cancel(handle)


def run():
    engine = connect()
    worker = uuid4().hex
    backend = LocalExecutionBackend(worker_resources())
    resources = backend.capabilities()
    if not backend.health()["ready"]:
        raise RuntimeError("Local execution backend is unavailable")
    project_id = demo_project()
    while True:
        try:
            with engine.begin() as connection:
                report_worker(connection, worker, resources)
                recover(connection, project_id=project_id)
                job = claim(connection, worker, project_id=project_id, **resources)
            if job is None:
                time.sleep(0.25)
            else:
                execute_attempt(engine, job, backend)
        except OperationalError:
            emit("database_unavailable", worker=worker)
            time.sleep(1)


if __name__ == "__main__":
    run()

