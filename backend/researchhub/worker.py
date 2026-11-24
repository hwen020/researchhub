import json
import multiprocessing
import time
from uuid import uuid4

from sqlalchemy.exc import OperationalError
from sqlalchemy.dialects.postgresql import insert

from .db import connect
from .plugins import PLUGINS
from .models import workers
from .queue import claim, finish, heartbeat, now_ms, recover


def report_worker(connection, worker):
    timestamp = now_ms(connection)
    statement = insert(workers).values(id=worker, last_seen=timestamp)
    connection.execute(statement.on_conflict_do_update(
        index_elements=[workers.c.id], set_={"last_seen": timestamp},
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


def execute_attempt(engine, job):
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
                    report_worker(connection, job["worker"])
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
    while True:
        try:
            with engine.begin() as connection:
                report_worker(connection, worker)
                recover(connection)
                job = claim(connection, worker)
            if job is None:
                time.sleep(0.25)
            else:
                execute_attempt(engine, job)
        except OperationalError:
            print(json.dumps({"event": "database_unavailable", "worker": worker}), flush=True)
            time.sleep(1)


if __name__ == "__main__":
    run()

