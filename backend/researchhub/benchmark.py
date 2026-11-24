"""Run a loopback HTTP and PostgreSQL benchmark in an isolated schema."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import math
import os
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from .auth import hash_password
from .db import connect
from .models import events, jobs, organizations, projects, users


def percentile(values, quantile):
    return round(sorted(values)[math.ceil(len(values) * quantile) - 1], 2)


def process(stack, environment, *args, stdout=subprocess.DEVNULL):
    child = subprocess.Popen([sys.executable, "-B", *args], env=environment, stdout=stdout)

    def stop():
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)
        if child.stdout is not None:
            child.stdout.close()

    stack.callback(stop)
    return child


def wait_until(condition, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(.05)
    raise TimeoutError("Benchmark operation did not finish")


def run_case(base_url, count, concurrency, worker_count):
    schema = "benchmark_" + uuid4().hex
    base = connect(base_url)
    with base.begin() as conn:
        conn.execute(text("CREATE SCHEMA " + schema))
        postgres_version = conn.execute(text("SHOW server_version")).scalar_one()
    url = make_url(base_url).update_query_dict({"options": "-csearch_path=" + schema})
    environment = dict(os.environ, DATABASE_URL=url.render_as_string(hide_password=False))
    engine = connect(url)
    original_url = os.environ["DATABASE_URL"]
    try:
        os.environ.update(DATABASE_URL=environment["DATABASE_URL"])
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        os.environ.update(DATABASE_URL=original_url)

    try:
        with ExitStack() as stack:
            project = str(uuid4())
            password = uuid4().hex
            with engine.begin() as conn:
                conn.execute(organizations.insert().values(id="bench", name="Benchmark"))
                conn.execute(projects.insert().values(id=project, organization_id="bench", name="Benchmark"))
                conn.execute(users.insert().values(
                    id="bench", username="bench", password_hash=hash_password(password), platform_admin=1,
                ))
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            process(stack, environment, "-m", "uvicorn", "researchhub.api:app", "--port", str(port), "--no-access-log")
            client = stack.enter_context(httpx.Client(base_url=f"http://127.0.0.1:{port}", auth=("bench", password)))

            def ready():
                try:
                    return client.get("/readyz").status_code == 200
                except httpx.ConnectError:
                    return False

            wait_until(ready, 20)
            for _ in range(worker_count):
                process(stack, environment, "-m", "researchhub.worker")
            wait_until(lambda: client.get("/metrics").json()["workers_online"] == worker_count, 20)

            def send(index):
                start = time.perf_counter()
                response = client.post(f"/projects/{project}/jobs", headers={"Idempotency-Key": str(index)},
                                       json={"plugin": "summary@1", "parameters": {"observations": list(range(64))}})
                response.raise_for_status()
                return (time.perf_counter() - start) * 1000, response.json()["id"]

            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                submissions = list(pool.map(send, range(count)))
            ids = [job_id for _, job_id in submissions]

            def completed():
                with engine.connect() as conn:
                    rows = conn.execute(select(jobs).where(jobs.c.id.in_(ids))).mappings().all()
                    return rows if len(rows) == count and all(row["state"] == "SUCCEEDED" for row in rows) else None

            results = wait_until(completed, 120)
            elapsed = time.perf_counter() - started
            with engine.connect() as conn:
                claimed = dict(conn.execute(select(events.c.job_id, events.c.timestamp).where(
                    events.c.job_id.in_(ids), events.c.reason == "claimed",
                )).all())
            assert len(claimed) == count and all(row["attempt"] == 1 for row in results)

            script = (
                "from researchhub.db import connect; from researchhub.queue import submit, claim\n"
                f"with connect().begin() as c: submit(c, {project!r}, 'recovery', 'summary@1', "
                "{'observations':[1,2]}, timeout_ms=2500); "
                "job = claim(c, 'abandoned')\n"
                "print(job['id'], flush=True)\n"
                "import time; time.sleep(60)\n"
            )
            holder = process(stack, environment, "-c", script, stdout=subprocess.PIPE)
            lost_job = holder.stdout.readline().decode().strip()
            if not lost_job:
                raise RuntimeError("Fixture worker did not claim the recovery job")
            holder.kill()
            killed_at = time.perf_counter()
            holder.wait(timeout=10)

            def recovered():
                with engine.connect() as conn:
                    return conn.execute(select(jobs.c.attempt).where(
                        jobs.c.id == lost_job, jobs.c.state == "SUCCEEDED",
                    )).scalar_one_or_none()

            assert wait_until(recovered, 25) == 2
            recovery = (time.perf_counter() - killed_at) * 1000
            return {
                "postgres": postgres_version, "workers": worker_count, "jobs": count, "concurrency": concurrency,
                "jobs_per_second": round(count / elapsed, 2),
                "queue_wait_p95_ms": percentile([claimed[row["id"]] - row["created_at"] for row in results], .95),
                "completion_p95_ms": percentile([
                    row["manifest"]["completed_at_ms"] - row["created_at"] for row in results
                ], .95),
                "api_p50_p95_p99_ms": [percentile([latency for latency, _ in submissions], p) for p in (.50, .95, .99)],
                "failure_to_success_ms": round(recovery, 2),
            }
    finally:
        engine.dispose()
        with base.begin() as conn:
            conn.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        base.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=24)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1 or args.concurrency < 1:
        parser.error("Jobs and concurrency must be positive")
    for count in (1, 2, 4):
        print(json.dumps(run_case(os.environ["DATABASE_URL"], args.jobs, args.concurrency, count)), flush=True)


if __name__ == "__main__":
    main()
