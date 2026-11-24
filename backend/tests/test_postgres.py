import os
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from researchhub.db import connect
from researchhub.finance import decide, request_funds
from researchhub.models import budgets, events, jobs, metadata, organizations, projects, users
from researchhub.queue import claim, finish, submit

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

