import json
import multiprocessing
import os
import time
from uuid import uuid4

from sqlalchemy.exc import OperationalError
from sqlalchemy.dialects.postgresql import insert

from .db import connect
from .demo_fixture import demo_project
from .plugins import PLUGINS
from .models import workers
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


def execute_plugin(sender, plugin, parameters):
    try:
        outcome = {"result": PLUGINS[plugin](parameters)}
    except (KeyError, ValueError):
        outcome = {"error": "invalid_plugin_input"}
    except Exception:
        outcome = {"error": "plugin_failure", "retryable": True}
    with sender:
        sender.send(outcome)


def execute_attempt(engine, job, resources):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=execute_plugin, args=(sender, job["plugin"], job["parameters"]))
    process.start()
    sender.close()
    next_heartbeat = 0
    try:
        while True:
            if time.monotonic() >= next_heartbeat:
                with engine.begin() as connection:
                    report_worker(connection, job["worker"], resources)
                    state = heartbeat(connection, job["id"], job["token"])
                if state == "LOST":
                    return
                if state == "CANCEL_REQUESTED":
                    outcome = {}
                    break
                next_heartbeat = time.monotonic() + 0.5
            if receiver.poll(0.1):
                try:
                    outcome = receiver.recv()
                except EOFError:
                    outcome = {"error": "executor_exited", "retryable": True}
                break
        with engine.begin() as connection:
            committed = finish(connection, job["id"], job["token"], **outcome)
        print(json.dumps({"event": "attempt_finished", "job_id": job["id"],
                          "attempt": job["attempt"], "committed": committed}), flush=True)
    finally:
        receiver.close()
        if process.is_alive():
            process.kill()
        process.join()
        process.close()


def run():
    engine = connect()
    worker = uuid4().hex
    resources = worker_resources()
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
                execute_attempt(engine, job, resources)
        except OperationalError:
            print(json.dumps({"event": "database_unavailable", "worker": worker}), flush=True)
            time.sleep(1)


if __name__ == "__main__":
    run()

