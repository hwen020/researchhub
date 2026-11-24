import json
import multiprocessing
import socket
import time
from uuid import uuid4

from sqlalchemy.exc import OperationalError

from .db import connect
from .plugins import PLUGINS
from .queue import claim, finish, heartbeat, recover


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
    worker = socket.gethostname()[:60] + "-" + uuid4().hex
    while True:
        try:
            with engine.begin() as connection:
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

