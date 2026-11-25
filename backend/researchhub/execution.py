"""Execution backend contract and the allowlisted local subprocess implementation."""
from dataclasses import dataclass
import multiprocessing
from multiprocessing.connection import Connection
from typing import Protocol

from .plugins import PLUGINS
from .resource_policy import requirements


class ExecutionBackend(Protocol):
    def submit(self, job): ...
    def poll(self, handle, timeout): ...
    def cancel(self, handle): ...
    def health(self): ...
    def capabilities(self): ...
    def resource_requirements(self, job): ...


@dataclass
class LocalExecution:
    process: multiprocessing.Process
    receiver: Connection


def execute_plugin(sender, plugin, parameters):
    try:
        outcome = {"result": PLUGINS[plugin](parameters)}
    except (KeyError, ValueError):
        outcome = {"error": "invalid_plugin_input"}
    except Exception:
        outcome = {"error": "plugin_failure", "retryable": True}
    with sender:
        sender.send(outcome)


class LocalExecutionBackend:
    def __init__(self, resources):
        self.context = multiprocessing.get_context("spawn")
        self.resources = resources

    def health(self):
        return {"ready": bool(PLUGINS), "backend": "local", "start_method": self.context.get_start_method()}

    def capabilities(self):
        return self.resources

    def resource_requirements(self, job):
        return requirements(job["plugin"], job["capability"], job["cpu_units"], job["memory_units"], job["priority"])

    def submit(self, job):
        if job["plugin"] not in PLUGINS:
            raise ValueError("Unknown execution plugin")
        requested = self.resource_requirements(job)
        if (requested["capability"] not in self.resources["capabilities"]
                or requested["cpu_units"] > self.resources["cpu_units"]
                or requested["memory_units"] > self.resources["memory_units"]):
            raise ValueError("Execution backend resources do not match the job")
        receiver, sender = self.context.Pipe(duplex=False)
        process = self.context.Process(target=execute_plugin, args=(sender, job["plugin"], job["parameters"]))
        try:
            process.start()
        except BaseException:
            receiver.close()
            process.close()
            raise
        finally:
            sender.close()
        return LocalExecution(process, receiver)

    def poll(self, handle, timeout):
        if not handle.receiver.poll(timeout):
            return None
        try:
            return handle.receiver.recv()
        except EOFError:
            return {"error": "executor_exited", "retryable": True}

    def cancel(self, handle):
        handle.receiver.close()
        if handle.process.is_alive():
            try:
                handle.process.kill()
            except ProcessLookupError:
                pass
        handle.process.join()
        handle.process.close()
