import os
import hashlib
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from researchhub.db import connect
from researchhub.finance import decide, request_funds
from researchhub.auth import hash_password
from researchhub.models import budgets, events, jobs, memberships, metadata, organizations, projects, users
from researchhub.queue import cancel, claim, finish, submit
from researchhub.models import workflow_runs
from researchhub.workflows import start

URL = os.environ.get("RESEARCHHUB_TEST_DATABASE")


@unittest.skipUnless(URL, "Requires a disposable PostgreSQL test database")
class PostgresIntegration(unittest.TestCase):
    def setUp(self):
        self.schema = "rh_" + uuid4().hex
        default = connect(URL)
        self.addCleanup(default.dispose)
        with default.begin() as conn:
            conn.execute(text("CREATE SCHEMA " + self.schema))

        def cleanup_schema():
            with default.begin() as conn:
                conn.execute(text("DROP SCHEMA " + self.schema + " CASCADE"))

        self.addCleanup(cleanup_schema)
        self.url = make_url(URL).update_query_dict({"options": "-csearch_path=" + self.schema})
        self.engine = connect(self.url)
        self.addCleanup(self.engine.dispose)
        metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            conn.execute(organizations.insert().values(id="org", name="Lab"))
            conn.execute(projects.insert().values(id="project", organization_id="org", name="Research"))
            conn.execute(budgets.insert().values(project_id="project", limit=100))
            conn.execute(users.insert(), [
                {"id": user, "username": user, "password_hash": "fixture"}
                for user in ("requester", "reviewer")
            ])

    def test_competing_claims_and_repeated_submissions(self):
        def enqueue(_):
            with self.engine.begin() as conn:
                return submit(conn, "project", "shared", "summary@1", {"observations": [1, 2]})["id"]

        def reserve(worker):
            with self.engine.begin() as conn:
                return claim(conn, str(worker))

        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(len(set(pool.map(enqueue, range(12)))), 1)
            leases = [job for job in pool.map(reserve, range(12)) if job]
        self.assertEqual(len(leases), 1)

    def test_budget_row_lock_prevents_overspending(self):
        with self.engine.begin() as conn:
            requests = [request_funds(conn, "project", "requester", key, 70, "Lab time") for key in ("a", "b")]

        def approve(request_id):
            try:
                with self.engine.begin() as conn:
                    return decide(conn, "project", request_id, "reviewer", True)
            except ValueError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(pool.map(approve, requests), ["APPROVED", "Insufficient project budget"])
        with self.engine.begin() as conn:
            self.assertEqual(conn.execute(select(budgets.c.spent)).scalar_one(), 70)

    def test_cancellation_and_completion_race_have_one_terminal_outcome(self):
        with self.engine.begin() as conn:
            job = submit(conn, "project", "race", "summary@1", {"observations": [1, 2]})
            lease = claim(conn, "worker")

        def cancel_job():
            with self.engine.begin() as conn:
                return cancel(conn, "project", job["id"])

        def complete_job():
            with self.engine.begin() as conn:
                return finish(conn, job["id"], lease["token"], result={"mean": "1.5"})

        with ThreadPoolExecutor(max_workers=2) as pool:
            cancellation = pool.submit(cancel_job)
            completion = pool.submit(complete_job)
            self.assertTrue(completion.result())
            self.assertIn(cancellation.result(), ("SUCCEEDED", "CANCEL_REQUESTED"))
        with self.engine.begin() as conn:
            state, result = conn.execute(select(jobs.c.state, jobs.c.result)).one()
            self.assertIn((state, result), (("CANCELLED", None), ("SUCCEEDED", {"mean": "1.5"})))

    def test_http_project_isolation_and_dataset_manifest(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from researchhub import api

        project, other = str(uuid4()), str(uuid4())
        password = "synthetic fixture only"
        with self.engine.begin() as conn:
            conn.execute(projects.insert(), [
                {"id": key, "organization_id": "org", "name": name}
                for key, name in ((project, "Primary"), (other, "Other"))
            ])
            for name, allowed in (("primary", project), ("other", other)):
                conn.execute(users.insert().values(id=name, username=name, password_hash=hash_password(password)))
                conn.execute(memberships.insert().values(project_id=allowed, user_id=name, role="pi"))
        with tempfile.TemporaryDirectory() as directory, patch.object(api, "engine", self.engine), patch.dict(
            os.environ, RESEARCHHUB_STORAGE=directory, RESEARCHHUB_CODE_VERSION="fixture",
        ), TestClient(api.app) as client:
            base = "/projects/" + project
            owner, outsider = ("primary", password), ("other", password)
            created = client.post(base + "/datasets", json={"name": "Synthetic observations"}, auth=owner)
            assert created.status_code == 200, created.text
            dataset_id = created.json()["id"]
            version_url = base + "/datasets/" + dataset_id + "/versions"
            version = client.post(version_url, content=b"value\n1\n2\n3\n",
                                  headers={"Content-Type": "text/csv"}, auth=owner)
            assert version.status_code == 200, version.text
            body = {"plugin": "summary@1", "dataset": {"id": dataset_id, "version": 1}}
            result = client.post(base + "/jobs", json=body, headers={"Idempotency-Key": "dataset-job"}, auth=owner)
            assert result.status_code == 200, result.text
            job_url = base + "/jobs/" + result.json()["id"]
            with self.engine.begin() as conn:
                lease = claim(conn, "manifest-worker")
                finish(conn, lease["id"], lease["token"], result={"mean": "2"})
            manifest = client.get(job_url + "/download/manifest", auth=owner).json()
            self.assertEqual(manifest["dataset"], {"id": dataset_id, "version": 1, "sha256": version.json()["checksum"]})
            self.assertEqual(manifest["inputs"], {"observations": [1, 2, 3]})
            self.assertEqual(manifest["output_sha256"], hashlib.sha256(b'{"mean":"2"}').hexdigest())
            self.assertEqual(manifest["plugin_version"], "1")
            self.assertEqual(manifest["code_version"], "fixture")
            for path in (base + "/jobs", job_url + "/events", job_url + "/download/manifest",
                         version_url + "/1", base + "/audit"):
                self.assertEqual(client.get(path, auth=outsider).status_code, 404)
            actions = {entry["action"] for entry in client.get(base + "/audit", auth=owner).json()}
            self.assertEqual(actions, {"dataset_registered", "dataset_uploaded", "job_submission", "job_artifact_download"})

    def launch(self, *args, **kwargs):
        environment = dict(os.environ, DATABASE_URL=self.url.render_as_string(hide_password=False))
        process = subprocess.Popen([sys.executable, "-B", *args], env=environment, **kwargs)

        def stop():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            if process.stdout is not None:
                process.stdout.close()

        self.addCleanup(stop)
        return process

    def test_scheduler_restart_preserves_parallel_roots_and_dependency(self):
        def node(*parents):
            return {"depends_on": list(parents), "plugin": "summary@1",
                    "parameters": {"observations": [1, 2, 3]}}

        with self.engine.begin() as conn:
            run = start(conn, "project", {"a": node(), "b": node(), "report": node("a", "b")})

        def status():
            with self.engine.connect() as conn:
                return conn.execute(select(workflow_runs).where(workflow_runs.c.id == run)).mappings().one()

        def wait_for(condition):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if condition():
                    return
                time.sleep(.1)
            self.fail("Timed out waiting for workflow state")

        first = self.launch("-m", "researchhub.scheduler", stdout=subprocess.DEVNULL)
        wait_for(lambda: all("job_id" in status()["nodes"][name] for name in ("a", "b")))
        first.kill()
        first.wait(timeout=10)
        snapshot = status()["nodes"]
        self.assertNotIn("job_id", snapshot["report"])
        self.launch("-m", "researchhub.worker", stdout=subprocess.DEVNULL)
        self.launch("-m", "researchhub.worker", stdout=subprocess.DEVNULL)
        self.launch("-m", "researchhub.scheduler", stdout=subprocess.DEVNULL)
        wait_for(lambda: status()["state"] == "SUCCEEDED")
        final = status()["nodes"]
        self.assertEqual({final[name]["job_id"] for name in ("a", "b")},
                         {snapshot[name]["job_id"] for name in ("a", "b")})
        self.assertNotIn(final["report"]["job_id"], {final["a"]["job_id"], final["b"]["job_id"]})

    def test_worker_computes_after_abrupt_process_loss(self):
        with self.engine.begin() as conn:
            job = submit(conn, "project", "restart", "summary@1", {"observations": [1, 2, 3]}, timeout_ms=2500)

        # A separate process takes a real lease and is killed before it can release it.
        script = (
            "import time; from researchhub.db import connect; from researchhub.queue import claim\n"
            "with connect().begin() as conn: job = claim(conn, 'terminated-worker')\n"
            "print(job['token'], flush=True); time.sleep(30)\n"
        )
        abandoned = self.launch("-c", script, stdout=subprocess.PIPE, text=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            reading = pool.submit(abandoned.stdout.readline)
            try:
                token = reading.result(timeout=12).strip()
            finally:
                abandoned.kill()
                abandoned.wait(timeout=10)
        self.assertTrue(token)
        self.launch("-m", "researchhub.worker", stdout=subprocess.DEVNULL)
        deadline = time.monotonic() + 16
        while time.monotonic() < deadline:
            with self.engine.begin() as conn:
                current = conn.execute(select(jobs).where(jobs.c.id == job["id"])).mappings().one()
                if current["state"] == "SUCCEEDED":
                    break
            time.sleep(.1)
        self.assertEqual(current["state"], "SUCCEEDED")
        self.assertEqual(current["attempt"], 2)
        self.assertEqual(current["result"]["mean"], "2")
        with self.engine.begin() as conn:
            self.assertFalse(finish(conn, job["id"], token, result={"stale": True}))
            history = conn.execute(select(events.c.reason).where(events.c.job_id == job["id"])).scalars().all()
            self.assertIn("deadline_exceeded", history)

