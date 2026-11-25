"""Measure fixed synthetic Genomics, Mobility and summary work on one host."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from tempfile import TemporaryDirectory
import json
import os
from pathlib import Path
import socket
import time
from uuid import uuid4

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from .auth import hash_password
from .benchmark import percentile, process, wait_until
from .db import connect
from .demo_fixture import DATA
from .models import events, jobs, organizations, projects, users, workflow_runs
from .registry import register, upload
from .storage import LocalStorage

MOBILITY = (b"participant_id,timestamp_utc,latitude,longitude,steps\n"
            b"synthetic01,2025-01-01T00:00:00Z,0,0,10\n"
            b"synthetic01,2025-01-01T00:10:00Z,0.001,0,20\n"
            b"synthetic01,2025-01-01T00:11:00Z,2,0,30\n")


def run(base_url, workers, submissions_per_project):
    schema = "benchmark_" + uuid4().hex
    base = connect(base_url)
    with base.begin() as connection:
        engine_version = connection.execute(text("SHOW server_version")).scalar_one()
        connection.execute(text("CREATE SCHEMA " + schema))
    scoped = make_url(base_url).update_query_dict({"options": "-csearch_path=" + schema})
    engine = connect(scoped)
    try:
        os.environ["DATABASE_URL"] = scoped.render_as_string(hide_password=False)
        command.upgrade(Config("alembic.ini"), "head")
        with ExitStack() as stack:
            root = stack.enter_context(TemporaryDirectory(prefix="researchhub-bench-"))
            environment = dict(os.environ, RESEARCHHUB_STORAGE=root,
                               RESEARCHHUB_WORKER_CAPABILITIES="GENERAL,GENOMICS,GEOSPATIAL")
            project_ids = {kind: str(uuid4()) for kind in ("summary", "genomics", "mobility")}
            data_ids = {}
            password = uuid4().hex
            with engine.begin() as connection:
                connection.execute(organizations.insert().values(id="bench", name="Synthetic benchmark"))
                connection.execute(users.insert().values(id="bench", username="bench", platform_admin=1,
                                                         password_hash=hash_password(password)))
                for kind, project in project_ids.items():
                    connection.execute(projects.insert().values(id=project, organization_id="bench", name=kind))
                for kind, data in (("genomics", DATA), ("mobility", MOBILITY)):
                    project = project_ids[kind]
                    dataset_id = register(connection, project, "bench", kind)
                    upload(connection, LocalStorage(Path(root)), project, dataset_id, data)
                    data_ids[kind] = dataset_id
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            process(stack, environment, "-m", "uvicorn", "researchhub.api:app", "--port", str(port),
                    "--no-access-log")
            process(stack, environment, "-m", "researchhub.scheduler")
            for _ in range(workers):
                process(stack, environment, "-m", "researchhub.worker")
            client = stack.enter_context(httpx.Client(base_url=f"http://127.0.0.1:{port}", auth=("bench", password)))

            def ready():
                try:
                    return client.get("/metrics").json()["workers_online"] == workers
                except (httpx.ConnectError, KeyError):
                    return False

            wait_until(ready, 25)

            def submit_work(item):
                index, kind = item
                started = time.perf_counter()
                path = "/projects/" + project_ids[kind]
                if kind == "summary":
                    response = client.post(path + "/jobs", headers={"Idempotency-Key": str(index)}, json={
                        "plugin": "summary@1", "parameters": {"observations": list(range(64))},
                        "priority": (index % 3) * 5, "cpu_units": 1 + index % 2,
                    })
                else:
                    response = client.post(path + "/research-workflows", json={
                        "discipline": kind, "dataset": {"id": data_ids[kind], "version": 1},
                    })
                response.raise_for_status()
                return (time.perf_counter() - started) * 1000

            def completed():
                with engine.connect() as connection:
                    runs = connection.execute(select(workflow_runs)).mappings().all()
                    rows = connection.execute(select(jobs)).mappings().all()
                if (len(runs) == submissions_per_project * 2 and len(rows) == submissions_per_project * 11
                        and all(row["state"] == "SUCCEEDED" for row in [*runs, *rows])):
                    return runs, rows
                return None

            items = [(index, kind) for index in range(submissions_per_project) for kind in project_ids]
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=4) as pool:
                request_times = list(pool.map(submit_work, items))
            runs, rows = wait_until(completed, 150)
            elapsed = time.perf_counter() - started
            with engine.connect() as connection:
                claims = connection.execute(select(events.c.job_id, events.c.timestamp).where(
                    events.c.reason == "claimed",
                ).order_by(events.c.timestamp, events.c.id)).all()
            by_id = {row["id"]: row for row in rows}
            waits = [timestamp - by_id[job_id]["created_at"] for job_id, timestamp in claims]
            allocations = Counter()
            for job_id, _ in claims[:len(claims) // 2]:
                row = by_id[job_id]
                allocations[row["project_id"]] += row["cpu_units"]
            shares = [allocations[project] for project in project_ids.values()]
            fairness = sum(shares)**2 / (len(shares) * sum(value**2 for value in shares))
            workflow_times = [row["completed_at"] - row["created_at"] for row in runs]
            return {"postgres": engine_version, "workers": workers, "jobs": len(rows), "workflows": len(runs),
                    "jobs_per_second": round(len(rows) / elapsed, 2),
                    "api_p50_p95_p99_ms": [percentile(request_times, value) for value in (.5, .95, .99)],
                    "queue_wait_p95_ms": percentile(waits, .95),
                    "workflow_p95_ms": percentile(workflow_times, .95),
                    "first_half_cpu_units": dict(zip(project_ids, shares)),
                    "first_half_jain_index": round(fairness, 3)}
    finally:
        os.environ["DATABASE_URL"] = base_url
        engine.dispose()
        with base.begin() as connection:
            connection.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        base.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submissions-per-project", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.submissions_per_project <= 20:
        parser.error("Choose 1-20 submissions per project")
    for workers in (1, 2, 4):
        print(json.dumps(run(os.environ["DATABASE_URL"], workers, args.submissions_per_project)), flush=True)


if __name__ == "__main__":
    main()
